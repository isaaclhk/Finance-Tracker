import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from worker.integrations import openai_client


@pytest.fixture(autouse=True)
def reset_client():
    openai_client._client = None
    yield
    openai_client._client = None


def _make_completion(content: str):
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_parse_and_categorize_success():
    expected = {
        "currency": "SGD",
        "amount": 5.50,
        "merchant": "BOBER TEA",
        "date": "2026-03-25",
        "time": "14:15",
        "card_or_account": "1234",
        "transaction_type": "card_spending",
        "bank": "UOB",
        "suggested_category": "Food & Drink",
    }

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_completion(json.dumps(expected))
    )

    with patch.object(openai_client, "get_client", return_value=mock_client):
        result = await openai_client.parse_and_categorize("test email body", "alerts@uob.com.sg")

    assert result == expected


@pytest.mark.asyncio
async def test_parse_and_categorize_retries_on_bad_json():
    expected = {"amount": 10.0, "merchant": "TEST", "date": "2026-03-25"}

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_completion("not valid json {"),
            _make_completion(json.dumps(expected)),
        ]
    )

    with patch.object(openai_client, "get_client", return_value=mock_client):
        result = await openai_client.parse_and_categorize("body", "sender")

    assert result == expected
    assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_parse_and_categorize_returns_none_after_two_failures():
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_completion("bad json"),
            _make_completion("still bad"),
        ]
    )

    with patch.object(openai_client, "get_client", return_value=mock_client):
        result = await openai_client.parse_and_categorize("body", "sender")

    assert result is None
