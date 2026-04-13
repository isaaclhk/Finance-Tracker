from worker.services.categorizer import get_suggested_category


def _firefly_txn(category_name=None):
    txn = {"description": "TEST", "amount": "5.50"}
    if category_name:
        txn["category_name"] = category_name
    return {"attributes": {"transactions": [txn]}}


def test_existing_firefly_category_used_as_suggestion():
    result = get_suggested_category(_firefly_txn("Transport"), "Food & Drink")
    assert result == "Transport"


def test_llm_suggestion_when_no_firefly_category():
    result = get_suggested_category(_firefly_txn(), "Food & Drink")
    assert result == "Food & Drink"


def test_none_when_no_category():
    result = get_suggested_category(_firefly_txn(), None)
    assert result is None
