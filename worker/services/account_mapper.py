ACCOUNT_MAP: dict[str, str] = {
    # Credit cards → Liability accounts (replace XXXX with real last 4 digits)
    # "XXXX": "UOB Credit Card",
    # "YYYY": "Trust Bank Card",
    # Bank accounts → Asset accounts
    # "CCCC": "OCBC Savings",
    # "DDDD": "UOB Savings",
    # Fallbacks by bank name
    "OCBC": "OCBC Savings",
    "UOB": "UOB Savings",
    "Trust": "Trust Bank Card",
    "Syfe": "Syfe Cash",
}

# Maps transaction_type -> (firefly_type, source_role, dest_role)
# source_role/dest_role: "asset", "liability", "expense", "revenue"
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
