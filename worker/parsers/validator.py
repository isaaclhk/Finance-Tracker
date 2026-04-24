from worker.config import (
    VALIDATION_LARGE_AMOUNT_THRESHOLD,
    VALIDATION_MAX_AMOUNT,
    VALIDATION_SMALL_AMOUNT_MIN,
)
from worker.utils.time import today_sgt

WARNING_LARGE_AMOUNT = "large_amount"
WARNING_MISSING_DATE = "missing_date"


def validate_parsed_transaction(parsed: dict) -> tuple[dict | None, list[str]]:
    warnings: list[str] = []

    source_hint_available = parsed.get("card_or_account") is not None
    bill_payment_with_bank = (
        parsed.get("transaction_type") == "bill_payment" and parsed.get("bank") is not None
    )
    if parsed.get("amount") is None or not (source_hint_available or bill_payment_with_bank):
        return None, ["missing_critical_fields"]

    amount = parsed["amount"]

    if amount <= VALIDATION_SMALL_AMOUNT_MIN:
        return None, ["amount_too_small"]

    if amount > VALIDATION_MAX_AMOUNT:
        return None, ["amount_too_large"]

    if amount > VALIDATION_LARGE_AMOUNT_THRESHOLD:
        warnings.append(WARNING_LARGE_AMOUNT)

    if parsed.get("date") is None:
        parsed["date"] = today_sgt().isoformat()
        warnings.append(WARNING_MISSING_DATE)

    return parsed, warnings
