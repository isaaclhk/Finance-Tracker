import json
import logging

from openai import AsyncOpenAI, OpenAIError

from worker.config import OPENAI_API_KEY, OPENAI_PARSE_MODEL

logger = logging.getLogger(__name__)

TRANSACTION_TYPES = [
    "card_spending",
    "fund_transfer",
    "atm_withdrawal",
    "giro",
    "paynow",
    "incoming",
    "refund",
    "reversal",
    "bill_payment",
    "non_transaction",
    "unknown",
]

CATEGORIES = [
    "Food & Drink",
    "Groceries",
    "Transport",
    "Shopping",
    "Health",
    "Subscriptions",
    "Utilities",
    "Education",
    "Housing",
    "Misc",
]

_txn_types_str = " | ".join(f'"{t}"' for t in TRANSACTION_TYPES)
_categories_str = " | ".join(f'"{c}"' for c in CATEGORIES)

PARSE_SYSTEM_PROMPT = f"""Extract transaction details from this bank email alert.
Return JSON with exactly these fields:
{{
  "currency": string (ISO 4217 code e.g. "SGD", "USD", "JPY" — default "SGD"),
  "amount": number (transaction value in the stated currency, no currency symbol),
  "merchant": string (merchant or payee name, cleaned up),
  "date": string (YYYY-MM-DD — dates in SG alerts are DD/MM, not MM/DD),
  "time": string (HH:MM or null),
  "card_or_account": string (last 4 digits of card or account identifier),
  "destination_account": string (last 4 of destination card for bill payments, or null),
  "transaction_type": {_txn_types_str},
  "record_status": "recordable" | "non_transaction" | "needs_review",
  "non_transaction_reason": string | null,
  "bank": "DBS" | "OCBC" | "UOB" | "Trust" | "Syfe" | "unknown",
  "suggested_category": one of: {_categories_str} | null
}}
If any field cannot be determined, use null.
Use record_status="recordable" only when the email is a transaction that should be
recorded in Firefly. Use record_status="non_transaction" for login alerts, OTPs,
marketing messages, payment reminders, and duplicate confirmation emails that do
not themselves contain enough transaction details to record. Use
record_status="needs_review" when the email appears financial but is missing
critical transaction details.
For non_transaction emails, set transaction_type="non_transaction" and explain
the reason briefly in non_transaction_reason.
For known named cards without last 4 digits, use the card product as
card_or_account instead of marking the alert needs_review. For example, Trust
Link card means card_or_account="Trust Link Card".
If the email says "has been reversed", "reversal", or "transaction reversed",
use transaction_type="reversal" — the date/time fields refer to the ORIGINAL
charge, not the reversal notice. Use transaction_type="refund" only for
merchant-initiated refunds (e.g. "refund from <merchant>").
Payments to Trust Bank, Trust Card, Trust credit card, UOB Absolute, UOB
Absolute Cashback Amex, UOB Credit Card, or UOB Amex are bill_payment
transactions with destination_account set to the paid card account. A card-side
repayment receipt without a source account should be non_transaction because the
debit-side bank alert records the actual payment."""

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


async def parse_and_categorize(email_body: str, sender: str) -> dict | None:
    client = get_client()
    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model=OPENAI_PARSE_MODEL,
                max_tokens=300,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Sender: {sender}\n\nEmail body:\n{email_body}",
                    },
                ],
            )
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("JSON decode failed on attempt 1, retrying")
                continue
            logger.error("JSON decode failed on retry")
            return None
        except OpenAIError:
            logger.exception("OpenAI parse_and_categorize failed")
            return None
