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
        "attributes": {
            "transactions": [{"description": "BOBER TEA", "amount": "5.50"}]
        },
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], None),
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
            return_value=([email], None),
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
