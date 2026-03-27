from worker.services.account_mapper import (
    get_firefly_transaction_type,
    map_to_firefly_account,
)


def test_map_by_bank_fallback():
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "OCBC"}) == "OCBC Child Savings Account"
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "UOB"}) == "UOB One Account"
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "Trust"}) == "Trust Card"


def test_map_unknown_returns_none():
    assert map_to_firefly_account({"card_or_account": "9999", "bank": "unknown"}) is None
    assert map_to_firefly_account({}) is None


def test_transaction_type_card_spending():
    t, src, dst = get_firefly_transaction_type("card_spending")
    assert t == "withdrawal"
    assert src == "liability"
    assert dst == "expense"


def test_transaction_type_incoming():
    t, src, dst = get_firefly_transaction_type("incoming")
    assert t == "deposit"
    assert src == "revenue"
    assert dst == "asset"


def test_transaction_type_bill_payment():
    t, src, dst = get_firefly_transaction_type("bill_payment")
    assert t == "transfer"


def test_transaction_type_unknown_defaults():
    t, src, dst = get_firefly_transaction_type("something_new")
    assert t == "withdrawal"
