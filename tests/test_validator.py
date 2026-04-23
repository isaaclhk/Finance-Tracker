from worker.parsers.validator import (
    WARNING_LARGE_AMOUNT,
    WARNING_MISSING_DATE,
    validate_parsed_transaction,
)
from worker.utils.time import today_sgt


def _base_parsed(**overrides):
    data = {
        "amount": 25.00,
        "merchant": "TEST MERCHANT",
        "date": "2026-03-25",
        "time": "14:00",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
        "suggested_category": "Food & Drink",
    }
    data.update(overrides)
    return data


def test_valid_transaction():
    parsed = _base_parsed()
    result, warnings = validate_parsed_transaction(parsed)
    assert result is not None
    assert warnings == []


def test_missing_amount():
    parsed = _base_parsed(amount=None)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is None
    assert "missing_critical_fields" in warnings


def test_missing_card_or_account():
    parsed = _base_parsed(card_or_account=None)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is None
    assert "missing_critical_fields" in warnings


def test_amount_too_small():
    parsed = _base_parsed(amount=0.001)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is None
    assert "amount_too_small" in warnings


def test_amount_zero():
    parsed = _base_parsed(amount=0)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is None


def test_amount_too_large():
    parsed = _base_parsed(amount=100000)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is None
    assert "amount_too_large" in warnings


def test_large_amount_warning():
    parsed = _base_parsed(amount=6000)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is not None
    assert WARNING_LARGE_AMOUNT in warnings


def test_missing_date_defaults_to_today():
    parsed = _base_parsed(date=None)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is not None
    assert result["date"] == today_sgt().isoformat()
    assert WARNING_MISSING_DATE in warnings


def test_boundary_amount_at_threshold():
    parsed = _base_parsed(amount=5000)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is not None
    assert WARNING_LARGE_AMOUNT not in warnings


def test_boundary_amount_just_above_threshold():
    parsed = _base_parsed(amount=5000.01)
    result, warnings = validate_parsed_transaction(parsed)
    assert result is not None
    assert WARNING_LARGE_AMOUNT in warnings
