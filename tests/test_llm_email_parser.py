from unittest.mock import AsyncMock, patch

import pytest
from worker.integrations import openai_client
from worker.parsers import llm_email_parser


def test_parse_prompt_guides_reversal_classification():
    assert "reversal" in openai_client.TRANSACTION_TYPES
    prompt = openai_client.PARSE_SYSTEM_PROMPT.lower()
    assert "reversed" in prompt or "reversal" in prompt


def test_parse_prompt_guides_record_status_classification():
    assert "non_transaction" in openai_client.TRANSACTION_TYPES
    prompt = openai_client.PARSE_SYSTEM_PROMPT.lower()
    assert "record_status" in prompt
    assert "non_transaction" in prompt
    assert "needs_review" in prompt


def test_parse_prompt_guides_card_payment_classification():
    prompt = openai_client.PARSE_SYSTEM_PROMPT.lower()
    assert "trust bank" in prompt
    assert "uob absolute" in prompt
    assert "bill_payment" in prompt
    assert "paid card account" in prompt


def test_parse_prompt_guides_named_card_without_last_four():
    prompt = openai_client.PARSE_SYSTEM_PROMPT.lower()
    assert "known named cards" in prompt
    assert "trust link card" in prompt
    assert "needs_review" in prompt


@pytest.mark.asyncio
async def test_parse_reversal_email_passes_through():
    parsed = {
        "amount": 12.90,
        "merchant": None,
        "date": "2026-04-18",
        "time": "20:01",
        "card_or_account": "8106",
        "transaction_type": "reversal",
        "bank": "UOB",
        "suggested_category": None,
    }
    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize(
            "A transaction of 12.90 SGD made with your UOB card ending 8106 "
            "on 18 Apr 26, 8:01PM at  has been reversed.",
            "alerts@uob.com.sg",
        )
    assert result["transaction_type"] == "reversal"


@pytest.mark.asyncio
async def test_parse_success():
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

    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize("email body", "alerts@uob.com.sg")

    assert result == parsed
    assert result["record_status"] == "recordable"


@pytest.mark.asyncio
async def test_parse_non_transaction_passes_through_without_amount():
    parsed = {
        "record_status": "non_transaction",
        "non_transaction_reason": "paynow_duplicate_confirmation",
        "amount": None,
        "merchant": "Glynis",
        "transaction_type": "non_transaction",
        "bank": "UOB",
    }

    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize("email body", "alerts@uob.com.sg")

    assert result == parsed


@pytest.mark.asyncio
async def test_parse_needs_review_passes_through_without_amount():
    parsed = {
        "record_status": "needs_review",
        "non_transaction_reason": "appears financial but amount is missing",
        "amount": None,
        "merchant": "Unknown",
        "transaction_type": "unknown",
        "bank": "UOB",
    }

    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize("email body", "alerts@uob.com.sg")

    assert result == parsed


@pytest.mark.asyncio
async def test_parse_returns_none_on_failure():
    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await llm_email_parser.parse_and_categorize("bad email", "unknown@test.com")

    assert result is None


@pytest.mark.asyncio
async def test_parse_returns_none_on_non_numeric_amount():
    parsed = {"amount": "not a number", "merchant": "TEST"}

    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize("email", "sender")

    assert result is None


@pytest.mark.asyncio
async def test_parse_returns_none_on_invalid_record_status():
    parsed = {"record_status": "maybe", "amount": 5.50, "merchant": "TEST"}

    with patch(
        "worker.parsers.llm_email_parser.openai_client.parse_and_categorize",
        new_callable=AsyncMock,
        return_value=parsed,
    ):
        result = await llm_email_parser.parse_and_categorize("email", "sender")

    assert result is None
