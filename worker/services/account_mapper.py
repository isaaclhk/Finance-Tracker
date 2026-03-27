import json
import logging

from worker.config import ACCOUNT_MAP_JSON

logger = logging.getLogger(__name__)

# Bank name fallbacks (always available)
_BANK_FALLBACKS: dict[str, str] = {
    "OCBC": "OCBC Child Savings Account",
    "UOB": "UOB One Account",
    "Trust": "Trust Card",
    "Syfe": "Syfe Cash",
}


def _load_account_map() -> dict[str, str]:
    custom: dict[str, str] = {}
    if ACCOUNT_MAP_JSON:
        try:
            custom = json.loads(ACCOUNT_MAP_JSON)
        except json.JSONDecodeError:
            logger.error("Invalid ACCOUNT_MAP JSON in env var")
    return {**_BANK_FALLBACKS, **custom}


ACCOUNT_MAP = _load_account_map()

# Maps transaction_type -> (firefly_type, source_role, dest_role)
TRANSACTION_TYPE_MAP: dict[str, tuple[str, str, str]] = {
    "card_spending": ("withdrawal", "liability", "expense"),
    "fund_transfer": ("transfer", "asset", "asset"),
    "atm_withdrawal": ("withdrawal", "asset", "expense"),
    "paynow": ("withdrawal", "asset", "expense"),
    "incoming": ("deposit", "revenue", "asset"),
    "refund": ("deposit", "revenue", "liability"),
    "bill_payment": ("transfer", "asset", "liability"),
    "giro": ("withdrawal", "asset", "expense"),
}


def map_to_firefly_account(parsed: dict) -> str | None:
    hint = parsed.get("card_or_account", "")
    if hint and hint in ACCOUNT_MAP:
        return ACCOUNT_MAP[hint]

    bank = parsed.get("bank", "unknown")
    if bank in ACCOUNT_MAP:
        return ACCOUNT_MAP[bank]

    return None


def get_firefly_transaction_type(
    transaction_type: str,
) -> tuple[str, str, str]:
    return TRANSACTION_TYPE_MAP.get(
        transaction_type,
        ("withdrawal", "asset", "expense"),
    )
