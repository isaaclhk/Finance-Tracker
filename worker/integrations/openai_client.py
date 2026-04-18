import json
import logging

from openai import AsyncOpenAI, OpenAIError

from worker.config import OPENAI_API_KEY, OPENAI_PARSE_MODEL, OPENAI_QUERY_MODEL

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
  "bank": "DBS" | "OCBC" | "UOB" | "Trust" | "Syfe" | "unknown",
  "suggested_category": one of: {_categories_str} | null
}}
If any field cannot be determined, use null.
If the email says "has been reversed", "reversal", or "transaction reversed",
use transaction_type="reversal" — the date/time fields refer to the ORIGINAL
charge, not the reversal notice. Use transaction_type="refund" only for
merchant-initiated refunds (e.g. "refund from <merchant>")."""

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
                max_tokens=200,
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


async def query(messages: list[dict]) -> str:
    client = get_client()
    try:
        response = await client.chat.completions.create(
            model=OPENAI_QUERY_MODEL,
            max_tokens=500,
            messages=messages,
        )
        return response.choices[0].message.content
    except OpenAIError:
        logger.exception("OpenAI query failed")
        return "Sorry, I couldn't process that query right now."
