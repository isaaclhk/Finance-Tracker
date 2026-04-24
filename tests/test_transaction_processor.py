import json
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
    assert txn["destination_name"] == "Merchant Spend"
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


def test_build_firefly_payload_external_fund_transfer_uses_generic_expense_account():
    validated = {
        "amount": 42.0,
        "merchant": "External Payee",
        "date": "2026-03-25",
        "time": None,
        "transaction_type": "fund_transfer",
    }
    payload = _build_firefly_payload(validated, "UOB One Account")
    txn = payload["transactions"][0]

    assert txn["type"] == "withdrawal"
    assert txn["description"] == "External Payee"
    assert txn["source_name"] == "UOB One Account"
    assert txn["destination_name"] == "Merchant Spend"


def test_build_firefly_payload_true_transfer_preserves_destination_account():
    validated = {
        "amount": 100.0,
        "merchant": "OCBC Child Savings Account",
        "date": "2026-03-25",
        "time": None,
        "transaction_type": "fund_transfer",
    }
    payload = _build_firefly_payload(validated, "UOB One Account")
    txn = payload["transactions"][0]

    assert txn["type"] == "transfer"
    assert txn["source_name"] == "UOB One Account"
    assert txn["destination_name"] == "OCBC Child Savings Account"


def test_build_firefly_payload_bill_payment_to_mapped_card():
    validated = {
        "amount": 250.0,
        "merchant": "Trust Card Payment",
        "date": "2026-03-25",
        "time": None,
        "destination_account": "Trust",
        "transaction_type": "bill_payment",
    }
    payload = _build_firefly_payload(validated, "UOB One Account")
    txn = payload["transactions"][0]

    assert txn["type"] == "withdrawal"
    assert txn["description"] == "Trust Card Payment"
    assert txn["source_name"] == "UOB One Account"
    assert txn["destination_name"] == "Trust Card"


def test_build_firefly_payload_bill_payment_to_direct_card_account_name():
    validated = {
        "amount": 250.0,
        "merchant": "UOB Absolute Cashback Amex Payment",
        "date": "2026-03-25",
        "time": None,
        "destination_account": "UOB Absolute Cashback Amex",
        "transaction_type": "bill_payment",
    }
    payload = _build_firefly_payload(validated, "UOB One Account")
    txn = payload["transactions"][0]

    assert txn["type"] == "withdrawal"
    assert txn["description"] == "UOB Absolute Cashback Amex Payment"
    assert txn["source_name"] == "UOB One Account"
    assert txn["destination_name"] == "UOB Absolute Cashback Amex"


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
    assert result.cursor_saved is True


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


@pytest.mark.asyncio
async def test_process_skips_uob_paynow_duplicate_confirmation():
    email = Email(
        message_id="uob-paynow-confirmation",
        sender="unialerts@uobgroup.com",
        subject="UOB - Your PayNow transfer to Glynis on 24-Apr-2026 is successful",
        body="",
        timestamp="2026-04-24T09:00:00+08:00",
    )

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
        ) as mock_parse,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T09:00:00+08:00")
    mock_parse.assert_not_called()
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_sends_uob_generic_alert_to_parser():
    email = Email(
        message_id="uob-generic",
        sender="unialerts@uobgroup.com",
        subject="UOB Personal Internet Banking Notification Alerts",
        body="You have successfully logged in to UOB Personal Internet Banking.",
        timestamp="2026-04-24T09:00:00+08:00",
    )

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_parse,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_not_called()
    mock_parse.assert_awaited_once_with(email.body, email.sender)
    assert result.cursor_saved is False
    assert result.deferred == 1
    assert result.pending_review[0]["type"] == "parse_failure"


@pytest.mark.asyncio
async def test_process_skips_parser_classified_non_transaction():
    email = Email(
        message_id="uob-parser-non-transaction",
        sender="alerts@example.com",
        subject="Bank notification",
        body="UOB - Your PayNow transfer to Glynis on 24-Apr-2026 is successful",
        timestamp="2026-04-24T09:00:00+08:00",
    )
    parsed = {
        "record_status": "non_transaction",
        "non_transaction_reason": "paynow_duplicate_confirmation",
        "amount": None,
        "merchant": "Glynis",
        "transaction_type": "non_transaction",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ) as mock_parse,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T09:00:00+08:00")
    mock_parse.assert_awaited_once_with(email.body, email.sender)
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_skips_trust_repayment_receipt_without_source():
    email = Email(
        message_id="trust-repayment-receipt",
        sender="Trust <from_us@trustbank.sg>",
        subject="Credit card repayment received",
        body="Your credit card repayment of SGD 1,283.30 has been received.",
        timestamp="2026-04-24T18:11:00+08:00",
    )
    parsed = {
        "record_status": "recordable",
        "amount": 1283.30,
        "merchant": "Credit Card Repayment",
        "date": "2026-04-24",
        "time": "18:11",
        "card_or_account": None,
        "transaction_type": "bill_payment",
        "bank": "Trust",
        "suggested_category": None,
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T18:11:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T18:11:00+08:00")
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.deferred == 0
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_skips_uob_absolute_repayment_receipt_without_source():
    email = Email(
        message_id="uob-absolute-repayment-receipt",
        sender="UOB Cards <uobcards@uobgroup.com>",
        subject="Credit Card Repayment",
        body="Your repayment of SGD 800.00 to UOB Absolute Cashback Amex has been received.",
        timestamp="2026-04-24T18:11:00+08:00",
    )
    parsed = {
        "record_status": "recordable",
        "amount": 800.00,
        "merchant": "UOB Absolute Cashback Amex",
        "date": "2026-04-24",
        "time": "18:11",
        "card_or_account": None,
        "transaction_type": "bill_payment",
        "bank": "UOB",
        "suggested_category": None,
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T18:11:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T18:11:00+08:00")
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.deferred == 0
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_records_uob_payment_to_trust_as_silent_bill_payment():
    email = Email(
        message_id="uob-trust-payment",
        sender="unialerts@uobgroup.com",
        subject="UOB Personal Internet Banking Notification Alerts",
        body=(
            "You made a PayNow transfer of SGD 1,283.30 to Trust Bank "
            "on your a/c ending 1076 at 6:11PM SGT, 24 Apr 26."
        ),
        timestamp="2026-04-24T18:11:00+08:00",
    )
    parsed = {
        "record_status": "recordable",
        "amount": 1283.30,
        "merchant": "Trust Bank",
        "date": "2026-04-24",
        "time": "18:11",
        "card_or_account": "1076",
        "transaction_type": "paynow",
        "bank": "UOB",
        "suggested_category": None,
    }
    firefly_txn = {
        "id": "88",
        "attributes": {"transactions": [{"description": "Trust Card Payment"}]},
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T18:11:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.is_duplicate",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_duplicate,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
            return_value=firefly_txn,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    payload = mock_create.await_args.args[0]
    txn = payload["transactions"][0]
    assert txn["type"] == "withdrawal"
    assert txn["description"] == "Trust Card Payment"
    assert txn["source_name"] == "UOB One Account"
    assert txn["destination_name"] == "Trust Card"
    mock_duplicate.assert_awaited_once()
    mock_save.assert_called_once_with(99999, "2026-04-24T18:11:00+08:00")
    assert result.cursor_saved is True
    assert result.new_count == 1
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_records_payment_to_uob_absolute_as_silent_bill_payment():
    email = Email(
        message_id="ocbc-uob-absolute-payment",
        sender="OCBC Alerts <alerts@ocbc.com>",
        subject="Funds transfer alert",
        body=(
            "You transferred SGD 800.00 to UOB Absolute Cashback Amex "
            "from your account ending 9012 on 24 Apr 2026."
        ),
        timestamp="2026-04-24T18:11:00+08:00",
    )
    parsed = {
        "record_status": "recordable",
        "amount": 800.00,
        "merchant": "UOB Absolute Cashback Amex",
        "date": "2026-04-24",
        "time": "18:11",
        "card_or_account": "9012",
        "transaction_type": "fund_transfer",
        "bank": "OCBC",
        "suggested_category": None,
    }
    firefly_txn = {
        "id": "89",
        "attributes": {"transactions": [{"description": "UOB Absolute Cashback Amex Payment"}]},
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T18:11:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
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
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    payload = mock_create.await_args.args[0]
    txn = payload["transactions"][0]
    assert txn["type"] == "withdrawal"
    assert txn["description"] == "UOB Absolute Cashback Amex Payment"
    assert txn["source_name"] == "OCBC Child Savings Account"
    assert txn["destination_name"] == "UOB Absolute Cashback Amex"
    mock_save.assert_called_once_with(99999, "2026-04-24T18:11:00+08:00")
    assert result.cursor_saved is True
    assert result.new_count == 1
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_needs_review_does_not_retry():
    email = Email(
        message_id="uob-needs-review",
        sender="unialerts@uobgroup.com",
        subject="UOB Personal Internet Banking Notification Alerts",
        body="A financial alert arrived but important details were unavailable.",
        timestamp="2026-04-24T09:00:00+08:00",
    )
    parsed = {
        "record_status": "needs_review",
        "non_transaction_reason": "missing amount and account details",
        "amount": None,
        "merchant": None,
        "transaction_type": "unknown",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ) as mock_parse,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T09:00:00+08:00")
    mock_parse.assert_awaited_once_with(email.body, email.sender)
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.deferred == 0
    assert result.pending_review == [{"type": "needs_review", "parsed": parsed, "email": email}]


@pytest.mark.asyncio
async def test_process_trust_bill_reminder_sends_once_and_saves_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "worker.services.bill_reminders.BILL_REMINDER_STATE_PATH",
        str(tmp_path / "bill_reminders.json"),
    )
    email = Email(
        message_id="trust-bill-1",
        sender="Trust <from_us@trustbank.sg>",
        subject="3 days left to pay your Trust credit card bill ⏰",
        body="Please pay your Trust credit card bill.",
        timestamp="2026-04-24T09:00:00+08:00",
    )

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
        ) as mock_parse,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T09:00:00+08:00")
    mock_parse.assert_not_called()
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.deferred == 0
    assert result.pending_review == [
        {
            "type": "bill_payment_reminder",
            "bank": "Trust",
            "account": "Trust credit card",
            "due_in_days": 3,
            "due_date": "2026-04-27",
            "key": "Trust:credit_card:2026-04-27",
            "subject": "3 days left to pay your Trust credit card bill ⏰",
        }
    ]


@pytest.mark.asyncio
async def test_process_trust_bill_reminder_skips_duplicate_due_date(tmp_path, monkeypatch):
    state_path = tmp_path / "bill_reminders.json"
    state_path.write_text(
        json.dumps({"sent": {"Trust:credit_card:2026-04-27": {"sent_at": "2026-04-24"}}})
    )
    monkeypatch.setattr(
        "worker.services.bill_reminders.BILL_REMINDER_STATE_PATH",
        str(state_path),
    )
    email = Email(
        message_id="trust-bill-2",
        sender="Trust <from_us@trustbank.sg>",
        subject="1 day left to pay your Trust credit card bill",
        body="Please pay your Trust credit card bill.",
        timestamp="2026-04-26T09:00:00+08:00",
    )

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-26T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
        ) as mock_parse,
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-26T09:00:00+08:00")
    mock_parse.assert_not_called()
    mock_create.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.pending_review == []


@pytest.mark.asyncio
async def test_process_trust_bill_reminder_fallback_dedupes_by_month(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "worker.services.bill_reminders.BILL_REMINDER_STATE_PATH",
        str(tmp_path / "bill_reminders.json"),
    )
    email = Email(
        message_id="trust-bill-fallback",
        sender="Trust <from_us@trustbank.sg>",
        subject="Reminder: pay your Trust credit card bill",
        body="Please pay your Trust credit card bill.",
        timestamp="2026-04-24T09:00:00+08:00",
    )

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-04-24T09:00:00+08:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
        ) as mock_parse,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_called_once_with(99999, "2026-04-24T09:00:00+08:00")
    mock_parse.assert_not_called()
    assert result.cursor_saved is True
    assert result.skipped == 1
    assert result.pending_review[0]["key"] == "Trust:credit_card:2026-04"
    assert result.pending_review[0]["due_date"] is None
    assert result.pending_review[0]["due_in_days"] is None


@pytest.mark.asyncio
async def test_process_holds_cursor_on_unknown_account():
    email = Email(
        message_id="unknown-account",
        sender="alerts@example.com",
        subject="Transaction Alert",
        body="You spent $5.50 at TEST",
        timestamp="2026-03-25T14:15:00",
    )
    parsed = {
        "amount": 5.50,
        "merchant": "TEST",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "9999",
        "transaction_type": "card_spending",
        "bank": "HSBC",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25T14:15:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_not_called()
    assert result.deferred == 1
    assert result.cursor_saved is False
    assert result.pending_review[0]["type"] == "unknown_account"


@pytest.mark.asyncio
async def test_process_holds_cursor_on_failed_foreign_conversion():
    email = Email(
        message_id="foreign-fail",
        sender="alerts@example.com",
        subject="Transaction Alert",
        body="You spent USD 50.00 at SHOP",
        timestamp="2026-03-25T14:15:00",
    )
    parsed = {
        "currency": "USD",
        "amount": 50.0,
        "merchant": "SHOP",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25T14:15:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
        patch(
            "worker.services.transaction_processor.llm_email_parser.parse_and_categorize",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "worker.services.transaction_processor.exchange_rate.convert_to_sgd",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "worker.services.transaction_processor.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_not_called()
    mock_create.assert_not_called()
    assert result.deferred == 1
    assert result.pending_review[0]["type"] == "conversion_failed"


@pytest.mark.asyncio
async def test_process_holds_cursor_on_processing_error():
    email = Email(
        message_id="firefly-fail",
        sender="alerts@example.com",
        subject="Transaction Alert",
        body="You spent $5.50 at TEST",
        timestamp="2026-03-25T14:15:00",
    )
    parsed = {
        "amount": 5.50,
        "merchant": "TEST",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
    }

    with (
        patch(
            "worker.services.transaction_processor.gmail_client.fetch_new_alerts",
            new_callable=AsyncMock,
            return_value=([email], 99999, "2026-03-25T14:15:00"),
        ),
        patch("worker.services.transaction_processor.gmail_client.save_cursor") as mock_save,
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
            side_effect=RuntimeError("firefly unavailable"),
        ),
    ):
        from worker.services.transaction_processor import process_new_emails

        result = await process_new_emails()

    mock_save.assert_not_called()
    assert result.errors == 1
    assert result.cursor_saved is False
    assert result.pending_review[0]["type"] == "processing_error"


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
