from unittest.mock import AsyncMock, patch

import pytest

from worker.parsers import llm_email_parser


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
