from worker.services.account_config import resolve_account_hint
from worker.services.card_rules import resolve_card_source_account

# Maps parser transaction_type -> Firefly transaction type.
TRANSACTION_TYPE_MAP: dict[str, str] = {
    "card_spending": "withdrawal",
    "fund_transfer": "transfer",
    "atm_withdrawal": "withdrawal",
    "paynow": "withdrawal",
    "incoming": "deposit",
    "refund": "deposit",
    "bill_payment": "withdrawal",
    "giro": "withdrawal",
}


def map_to_firefly_account(parsed: dict) -> str | None:
    hint = parsed.get("card_or_account", "")
    source_account = resolve_account_hint(hint) or resolve_card_source_account(hint)
    if source_account:
        return source_account

    bank = parsed.get("bank", "unknown")
    return resolve_account_hint(bank)


def get_firefly_transaction_type(transaction_type: str) -> str:
    return TRANSACTION_TYPE_MAP.get(transaction_type, "withdrawal")
