from unittest.mock import AsyncMock, patch

import pytest
from worker.integrations.gmail_client import Email
from worker.services.transaction_processor import ProcessResult, _build_firefly_payload


def test_build_firefly_payload_withdrawal():
    validated = {
        "amount": 5.50,
        "merchant": "BOBER TEA",
        "date": "2026-03-25",
        "time": "14:15",
        "transaction_type": "card_spending",
    }
    payload = _build_firefly_payload(validated, "UOB Credit Card")
    txn = payload["transactions"][0]

    assert txn["type"] == "withdrawal"
    assert txn["amount"] == "5.5"
    assert txn["description"] == "BOBER TEA"
    assert txn["source_name"] == "UOB Credit Card"
    assert txn["destination_name"] == "BOBER TEA"
    assert "14:15" in txn["date"]


def test_build_firefly_payload_deposit():
    validated = {
        "amount": 3000,
        "merchant": "Salary",
        "date": "2026-03-25",
        "time": None,
        "transaction_type": "incoming",
    }
    payload = _build_firefly_payload(validated, "OCBC Savings")
    txn = payload["transactions"][0]

    assert txn["type"] == "deposit"
    assert txn["source_name"] == "Salary"
    assert txn["destination_name"] == "OCBC Savings"


@pytest.mark.asyncio
async def test_process_new_emails_success():
    email = Email(
        message_id="123",
        sender="alerts@uob.com.sg",
        subject="Transaction Alert",
        body="You spent $5.50 at BOBER TEA",
        timestamp="2026-03-25T14:15:00",
    )
    parsed = {
        "amount": 5.50,
        "merchant": "BOBER TEA",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
        "suggested_category": "Food & Drink",
    }
    firefly_txn = {
        "id": "42",
        "attributes": {"transactions": [{"description": "BOBER TEA", "amount": "5.50"}]},
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25T14:15:00"),
        ),
        patch(
            "worker.services.transaction_processor.gmail_client.save_cursor",
        ),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.is_duplicate",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
            return_value=firefly_txn,
        ),
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    assert isinstance(result, ProcessResult)
    assert result.new_count == 1
    assert len(result.pending_review) == 1
    assert result.pending_review[0]["type"] == "category_confirmation"


@pytest.mark.asyncio
async def test_process_skips_duplicates():
    email = Email(
        message_id="123",
        sender="alerts@uob.com.sg",
        subject="Alert",
        body="$5.50 at TEST",
        timestamp="2026-03-25",
    )
    parsed = {
        "amount": 5.50,
        "merchant": "TEST",
        "date": "2026-03-25",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25"),
        ),
        patch(
            "worker.services.transaction_processor.gmail_client.save_cursor",
        ),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.is_duplicate",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    assert result.new_count == 0


def test_build_firefly_payload_with_foreign_info():
    validated = {
        "amount": 67.0,
        "merchant": "GRAB THAILAND",
        "date": "2026-03-25",
        "time": None,
        "transaction_type": "card_spending",
    }
    foreign_info = {"currency": "THB", "original_amount": 350.0, "rate": 0.0383}
    payload = _build_firefly_payload(validated, "UOB Credit Card", foreign_info)
    txn = payload["transactions"][0]

    assert txn["amount"] == "67.0"
    assert txn["foreign_currency_code"] == "THB"
    assert txn["foreign_amount"] == "350.0"


def test_build_firefly_payload_no_foreign_fields_on_failed_conversion():
    validated = {
        "amount": 50.0,
        "merchant": "SHOP",
        "date": "2026-03-25",
        "time": None,
        "transaction_type": "card_spending",
    }
    foreign_info = {"currency": "USD", "original_amount": 50.0, "rate": None}
    payload = _build_firefly_payload(validated, "UOB Credit Card", foreign_info)
    txn = payload["transactions"][0]

    assert "foreign_currency_code" not in txn
    assert "foreign_amount" not in txn


@pytest.mark.asyncio
async def test_process_reversal_deletes_single_match():
    email = Email(
        message_id="rev1",
        sender="alerts@uob.com.sg",
        subject="Reversal",
        body="A transaction of 12.90 SGD ... has been reversed.",
        timestamp="2026-04-19T09:00:00",
    )
    parsed = {
        "amount": 12.90,
        "merchant": None,
        "date": "2026-04-18",
        "time": "20:01",
        "card_or_account": "8106",
        "transaction_type": "reversal",
        "bank": "UOB",
    }
    original = {"id": "42", "attributes": {"transactions": [{"description": "SHOP"}]}}

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-19T09:00:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor"),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.reversal_matcher.find_original_charge",
            new_callable=AsyncMock,
            return_value=[original],
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.delete_transaction",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_delete.assert_awaited_once_with("42")
    mock_create.assert_not_called()
    assert result.new_count == 0
    assert len(result.pending_review) == 1
    assert result.pending_review[0]["type"] == "reversal_applied"


@pytest.mark.asyncio
async def test_process_reversal_orphan_when_no_match():
    email = Email(
        message_id="rev2",
        sender="alerts@uob.com.sg",
        subject="Reversal",
        body="...has been reversed.",
        timestamp="2026-04-19T09:00:00",
    )
    parsed = {
        "amount": 12.90,
        "merchant": None,
        "date": "2026-04-18",
        "time": "20:01",
        "card_or_account": "8106",
        "transaction_type": "reversal",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-19T09:00:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor"),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.reversal_matcher.find_original_charge",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.delete_transaction",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_delete.assert_not_called()
    mock_create.assert_not_called()
    assert len(result.pending_review) == 1
    assert result.pending_review[0]["type"] == "reversal_orphan"


@pytest.mark.asyncio
async def test_process_reversal_ambiguous_when_multiple_matches():
    email = Email(
        message_id="rev3",
        sender="alerts@uob.com.sg",
        subject="Reversal",
        body="...has been reversed.",
        timestamp="2026-04-19T09:00:00",
    )
    parsed = {
        "amount": 12.90,
        "merchant": None,
        "date": "2026-04-18",
        "time": "20:01",
        "card_or_account": "8106",
        "transaction_type": "reversal",
        "bank": "UOB",
    }
    candidates = [
        {"id": "42", "attributes": {"transactions": [{"description": "A"}]}},
        {"id": "43", "attributes": {"transactions": [{"description": "B"}]}},
    ]

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-19T09:00:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor"),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.reversal_matcher.find_original_charge",
            new_callable=AsyncMock,
            return_value=candidates,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.delete_transaction",
            new_callable=AsyncMock,
        ) as mock_delete,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_delete.assert_not_called()
    assert len(result.pending_review) == 1
    assert result.pending_review[0]["type"] == "reversal_ambiguous"
    assert len(result.pending_review[0]["candidates"]) == 2


@pytest.mark.asyncio
async def test_process_new_emails_foreign_currency():
    email = Email(
        message_id="456",
        sender="alerts@uob.com.sg",
        subject="Transaction Alert",
        body="You spent USD 50.00 at OVERSEAS SHOP",
        timestamp="2026-03-25T14:15:00",
    )
    parsed = {
        "currency": "USD",
        "amount": 50.0,
        "merchant": "OVERSEAS SHOP",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
        "suggested_category": "Shopping",
    }
    firefly_txn = {
        "id": "99",
        "attributes": {"transactions": [{"description": "OVERSEAS SHOP", "amount": "67.00"}]},
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25T14:15:00"),
        ),
        patch(
            "worker.services.transaction_processor.gmail_client.save_cursor",
        ),
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.exchange_rate.convert_to_sgd",
            new_callable=AsyncMock,
            return_value=(67.0, 1.34),
        ),
        patch(
            "worker.services.transaction_processor.is_duplicate",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
            return_value=firefly_txn,
        ),
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    assert result.new_count == 1
    review = result.pending_review[0]
    assert review["foreign_info"]["currency"] == "USD"
    assert review["foreign_info"]["original_amount"] == 50.0
    assert review["foreign_info"]["rate"] == 1.34
    # Amount should have been converted to SGD
    assert review["parsed"]["amount"] == 67.0
