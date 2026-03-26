import logging
from dataclasses import dataclass, field

from worker.integrations import firefly_client, gmail_client, ibkr_flex
from worker.parsers import llm_email_parser
from worker.parsers.validator import WARNING_LARGE_AMOUNT, validate_parsed_transaction
from worker.services.account_mapper import get_firefly_transaction_type, map_to_firefly_account
from worker.services.categorizer import categorize
from worker.utils.dedup import is_duplicate

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    new_count: int = 0
    auto_categorized: int = 0
    pending_review: list[dict] = field(default_factory=list)
    errors: int = 0
    ibkr_data: dict | None = None


def _build_firefly_payload(validated: dict, source_account: str) -> dict:
    firefly_type, _, _ = get_firefly_transaction_type(validated.get("transaction_type", "unknown"))

    merchant = validated.get("merchant", "Unknown")

    txn = {
        "type": firefly_type,
        "date": validated["date"],
        "amount": str(validated["amount"]),
        "description": merchant,
        "source_name": source_account,
        "destination_name": merchant,
    }

    if validated.get("time"):
        txn["date"] = f"{validated['date']}T{validated['time']}:00"

    if firefly_type == "deposit":
        txn["source_name"] = merchant
        txn["destination_name"] = source_account

    if firefly_type == "transfer":
        txn["destination_name"] = source_account
        txn["source_name"] = source_account

    return {"transactions": [txn]}


async def process_new_emails() -> ProcessResult:
    result = ProcessResult()

    try:
        emails = await gmail_client.fetch_new_alerts()
    except Exception:
        logger.exception("Failed to fetch emails")
        result.errors += 1
        return result

    for email in emails:
        # Check if this is an IBKR Flex report email
        if ibkr_flex.is_ibkr_email(email.sender) and email.attachments:
            ibkr_data = ibkr_flex.parse_ibkr_from_email(email.attachments)
            if ibkr_data:
                result.ibkr_data = ibkr_data
                logger.info("Parsed IBKR data from email: equity=%.2f", ibkr_data["total_equity"])
            continue

        try:
            parsed = await llm_email_parser.parse_and_categorize(email.body, email.sender)
            if parsed is None:
                result.errors += 1
                continue

            validated, warnings = validate_parsed_transaction(parsed)
            if validated is None:
                logger.warning("Validation failed: %s", warnings)
                result.errors += 1
                continue

            source_account = map_to_firefly_account(validated)
            if source_account is None:
                result.pending_review.append(
                    {
                        "type": "unknown_account",
                        "parsed": validated,
                    }
                )
                continue

            if await is_duplicate(validated):
                continue

            payload = _build_firefly_payload(validated, source_account)
            firefly_txn = await firefly_client.create_transaction(payload)

            suggested = validated.get("suggested_category")
            category, needs_confirmation = categorize(firefly_txn, suggested)

            result.new_count += 1

            if needs_confirmation:
                result.pending_review.append(
                    {
                        "type": "category_confirmation",
                        "transaction": firefly_txn,
                        "suggested_category": category,
                        "parsed": validated,
                        "large_amount": WARNING_LARGE_AMOUNT in warnings,
                    }
                )
            else:
                result.auto_categorized += 1

        except Exception:
            logger.exception("Failed to process email %s", email.message_id)
            result.errors += 1

    return result
