import logging
import re
from dataclasses import dataclass, field

from worker.config import FIREFLY_MERCHANT_EXPENSE_ACCOUNT
from worker.integrations import exchange_rate, firefly_client, gmail_client
from worker.parsers import llm_email_parser
from worker.parsers.validator import WARNING_LARGE_AMOUNT, validate_parsed_transaction
from worker.services import bill_reminders, reversal_matcher
from worker.services.account_mapper import (
    ACCOUNT_MAP,
    get_firefly_transaction_type,
    map_to_firefly_account,
)
from worker.utils.dedup import is_duplicate

logger = logging.getLogger(__name__)

_UOB_PAYNOW_CONFIRMATION_RE = re.compile(
    r"\buob\s*-\s*your\s+paynow\s+transfer\s+to\b.+\bis\s+successfu\w*",
    re.IGNORECASE,
)


@dataclass
class ProcessResult:
    new_count: int = 0
    pending_review: list[dict] = field(default_factory=list)
    skipped: int = 0
    errors: int = 0
    deferred: int = 0
    cursor_saved: bool = False


def _email_field(email: object, name: str) -> str:
    return str(getattr(email, name, "") or "")


def _is_uob_non_transaction_alert(email: object) -> bool:
    sender = _email_field(email, "sender").lower()
    subject = _email_field(email, "subject").lower()
    content = f"{subject}\n{_email_field(email, 'body')}"

    if "unialerts@uobgroup.com" not in sender:
        return False
    return _UOB_PAYNOW_CONFIRMATION_RE.search(content) is not None


def _is_non_transaction(parsed: dict) -> bool:
    return parsed.get("record_status") == "non_transaction"


def _needs_review(parsed: dict) -> bool:
    return parsed.get("record_status") == "needs_review"


def _build_firefly_payload(
    validated: dict, source_account: str, foreign_info: dict | None = None
) -> dict:
    firefly_type = get_firefly_transaction_type(validated.get("transaction_type", "unknown"))

    merchant = validated.get("merchant") or "Unknown"

    # fund_transfer to an external party (not in ACCOUNT_MAP) should be a withdrawal,
    # not a Firefly transfer (which requires both accounts to be the user's own).
    if firefly_type == "transfer" and validated.get("transaction_type") == "fund_transfer":
        known_accounts = set(ACCOUNT_MAP.values())
        if merchant not in known_accounts:
            firefly_type = "withdrawal"

    txn = {
        "type": firefly_type,
        "date": validated["date"],
        "amount": str(validated["amount"]),
        "description": merchant,
        "source_name": source_account,
        "destination_name": FIREFLY_MERCHANT_EXPENSE_ACCOUNT,
    }

    if validated.get("time"):
        txn["date"] = f"{validated['date']}T{validated['time']}:00"

    if firefly_type == "deposit":
        txn["source_name"] = merchant
        txn["destination_name"] = source_account

    if firefly_type == "transfer" or validated.get("transaction_type") == "bill_payment":
        # For bill_payment: source is bank account, destination is credit card
        txn["source_name"] = source_account
        dest_hint = validated.get("destination_account", "")
        dest_account = ACCOUNT_MAP.get(dest_hint) if dest_hint else None
        txn["destination_name"] = dest_account or merchant

    if foreign_info and foreign_info.get("rate") is not None:
        txn["foreign_currency_code"] = foreign_info["currency"]
        txn["foreign_amount"] = str(foreign_info["original_amount"])

    return {"transactions": [txn]}


async def process_new_emails() -> ProcessResult:
    result = ProcessResult()
    should_save_cursor = True

    try:
        emails, new_history_id, latest_timestamp = await gmail_client.fetch_new_alerts()
    except Exception:
        logger.exception("Failed to fetch emails")
        result.errors += 1
        return result

    for email in sorted(emails, key=lambda e: e.timestamp or ""):
        try:
            if _is_uob_non_transaction_alert(email):
                result.skipped += 1
                continue

            reminder = bill_reminders.detect_trust_bill_reminder(email)
            if reminder:
                if bill_reminders.was_sent(reminder["key"]):
                    result.skipped += 1
                    continue

                bill_reminders.mark_sent(reminder)
                result.skipped += 1
                result.pending_review.append(reminder)
                continue

            parsed = await llm_email_parser.parse_and_categorize(email.body, email.sender)
            if parsed is None:
                should_save_cursor = False
                result.deferred += 1
                result.pending_review.append(
                    {
                        "type": "parse_failure",
                        "email": email,
                    }
                )
                continue

            if _is_non_transaction(parsed):
                result.skipped += 1
                continue

            if _needs_review(parsed):
                result.pending_review.append(
                    {
                        "type": "needs_review",
                        "parsed": parsed,
                        "email": email,
                    }
                )
                continue

            # Convert foreign currency to SGD before validation
            foreign_info = None
            currency = (parsed.get("currency") or "SGD").upper()
            if currency != "SGD" and parsed.get("amount") is not None:
                conversion = await exchange_rate.convert_to_sgd(parsed["amount"], currency)
                if conversion is not None:
                    sgd_amount, rate = conversion
                    foreign_info = {
                        "currency": currency,
                        "original_amount": parsed["amount"],
                        "rate": rate,
                    }
                    parsed["amount"] = sgd_amount
                else:
                    should_save_cursor = False
                    result.deferred += 1
                    foreign_info = {
                        "currency": currency,
                        "original_amount": parsed["amount"],
                        "rate": None,
                    }
                    result.pending_review.append(
                        {
                            "type": "conversion_failed",
                            "parsed": parsed,
                            "foreign_info": foreign_info,
                            "email": email,
                        }
                    )
                    continue

            validated, warnings = validate_parsed_transaction(parsed)
            if validated is None:
                logger.warning("Validation failed: %s", warnings)
                should_save_cursor = False
                result.deferred += 1
                result.pending_review.append(
                    {
                        "type": "validation_failed",
                        "parsed": parsed,
                        "warnings": warnings,
                        "email": email,
                    }
                )
                continue

            source_account = map_to_firefly_account(validated)
            if source_account is None:
                should_save_cursor = False
                result.deferred += 1
                result.pending_review.append(
                    {
                        "type": "unknown_account",
                        "parsed": validated,
                    }
                )
                continue

            if validated.get("transaction_type") == "reversal":
                candidates = await reversal_matcher.find_original_charge(validated, source_account)
                if len(candidates) == 1:
                    original = candidates[0]
                    await firefly_client.delete_transaction(original["id"])
                    result.pending_review.append(
                        {
                            "type": "reversal_applied",
                            "parsed": validated,
                            "deleted": original,
                        }
                    )
                elif len(candidates) == 0:
                    result.pending_review.append({"type": "reversal_orphan", "parsed": validated})
                else:
                    result.pending_review.append(
                        {
                            "type": "reversal_ambiguous",
                            "parsed": validated,
                            "candidates": candidates,
                        }
                    )
                continue

            if await is_duplicate(validated, source_account=source_account):
                continue

            payload = _build_firefly_payload(validated, source_account, foreign_info)
            firefly_txn = await firefly_client.create_transaction(payload)

            # Pick the best category suggestion: Firefly rule match > LLM > None
            suggested = validated.get("suggested_category")
            firefly_txns = firefly_txn.get("attributes", {}).get("transactions", [])
            category = (firefly_txns[0].get("category_name") if firefly_txns else None) or suggested

            result.new_count += 1
            result.pending_review.append(
                {
                    "type": "category_confirmation",
                    "transaction": firefly_txn,
                    "suggested_category": category,
                    "parsed": validated,
                    "large_amount": WARNING_LARGE_AMOUNT in warnings,
                    "foreign_info": foreign_info,
                }
            )

        except Exception:
            logger.exception("Failed to process email %s", email.message_id)
            should_save_cursor = False
            result.errors += 1
            result.pending_review.append(
                {
                    "type": "processing_error",
                    "email": email,
                }
            )

    # Save cursor only after all emails are processed
    if new_history_id and should_save_cursor:
        gmail_client.save_cursor(new_history_id, latest_timestamp)
        result.cursor_saved = True
    elif new_history_id:
        logger.warning(
            "Not advancing Gmail cursor because %d email(s) are deferred and %d errored",
            result.deferred,
            result.errors,
        )

    return result
