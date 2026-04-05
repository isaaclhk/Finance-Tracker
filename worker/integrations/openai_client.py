import json
import logging

from openai import AsyncOpenAI

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
  "amount": number (SGD value, no currency symbol),
  "merchant": string (merchant or payee name, cleaned up),
  "date": string (YYYY-MM-DD — dates in SG alerts are DD/MM, not MM/DD),
  "time": string (HH:MM or null),
  "card_or_account": string (last 4 digits of card or account identifier),
  "transaction_type": {_txn_types_str},
  "bank": "DBS" | "OCBC" | "UOB" | "Trust" | "Syfe" | "unknown",
  "suggested_category": one of: {_categories_str} | null
}}
If any field cannot be determined, use null."""

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
        except Exception:
            logger.exception("OpenAI parse_and_categorize failed")
            return None
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
    except Exception:
        logger.exception("OpenAI query failed")
        return "Sorry, I couldn't process that query right now."
