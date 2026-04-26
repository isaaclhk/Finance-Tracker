from worker.services.account_mapper import (
    get_firefly_transaction_type,
    map_to_firefly_account,
)


def test_map_by_bank_fallback():
    assert (
        map_to_firefly_account({"card_or_account": "9999", "bank": "OCBC"})
        == "OCBC Child Savings Account"
    )
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "UOB"}) == "UOB One Account"
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "Trust"}) == "Trust Card"


def test_map_known_credit_card_destination_aliases():
    assert (
        map_to_firefly_account({"card_or_account": "Trust Link", "bank": "unknown"})
        == "Trust Card"
    )
    assert (
        map_to_firefly_account({"card_or_account": "Trust Link Card", "bank": "unknown"})
        == "Trust Card"
    )
    assert (
        map_to_firefly_account({"card_or_account": "UOB Absolute", "bank": "unknown"})
        == "UOB Absolute Cashback Amex"
    )
    assert (
        map_to_firefly_account({"card_or_account": "UOB Credit Card", "bank": "unknown"})
        == "UOB Absolute Cashback Amex"
    )


def test_map_direct_firefly_account_name():
    assert (
        map_to_firefly_account({"card_or_account": "Trust Card", "bank": "unknown"})
        == "Trust Card"
    )


def test_map_unknown_returns_none():
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "unknown"}) is None
    assert map_to_firefly_account({}) is None


def test_transaction_type_card_spending():
    assert get_firefly_transaction_type("card_spending") == "withdrawal"


def test_transaction_type_incoming():
    assert get_firefly_transaction_type("incoming") == "deposit"


def test_transaction_type_bill_payment():
    assert get_firefly_transaction_type("bill_payment") == "withdrawal"


def test_transaction_type_unknown_defaults():
    assert get_firefly_transaction_type("something_new") == "withdrawal"
