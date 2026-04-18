from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from worker.integrations import firefly_client


@pytest.fixture(autouse=True)
def reset_client():
    firefly_client._client = None
    yield
    firefly_client._client = None


def _mock_response(data, status_code=200, total_pages=None):
    resp = MagicMock()
    resp.status_code = status_code
    body = {"data": data}
    if total_pages is not None:
        body["meta"] = {"pagination": {"total_pages": total_pages}}
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_get_accounts():
    accounts = [{"id": "1", "attributes": {"name": "OCBC Savings"}}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response(accounts, total_pages=1))

    with patch.object(firefly_client, "get_client", return_value=mock_client):
        result = await firefly_client.get_accounts()

    assert result == accounts
    mock_client.get.assert_called_once_with("/api/v1/accounts", params={"type": "all", "page": 1})


@pytest.mark.asyncio
async def test_get_transactions_with_dates():
    txns = [{"id": "1", "attributes": {"description": "Test"}}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response(txns))

    with patch.object(firefly_client, "get_client", return_value=mock_client):
        result = await firefly_client.get_transactions(
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 31)
        )

    assert result == txns
    mock_client.get.assert_called_once_with(
        "/api/v1/transactions",
        params={"page": 1, "start": "2026-03-01", "end": "2026-03-31"},
    )


@pytest.mark.asyncio
async def test_create_transaction():
    created = {"id": "42", "attributes": {"description": "BOBER TEA"}}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(created))
    payload = {"transactions": [{"description": "BOBER TEA", "amount": "5.50"}]}

    with patch.object(firefly_client, "get_client", return_value=mock_client):
        result = await firefly_client.create_transaction(payload)

    assert result == created
    mock_client.post.assert_called_once_with("/api/v1/transactions", json=payload)


@pytest.mark.asyncio
async def test_delete_transaction():
    mock_client = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    mock_client.delete = AsyncMock(return_value=resp)

    with patch.object(firefly_client, "get_client", return_value=mock_client):
        result = await firefly_client.delete_transaction("42")

    assert result is None
    mock_client.delete.assert_called_once_with("/api/v1/transactions/42")


@pytest.mark.asyncio
async def test_search_transactions():
    txns = [{"id": "1"}]
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response(txns))

    with patch.object(firefly_client, "get_client", return_value=mock_client):
        result = await firefly_client.search_transactions("BOBER TEA")

    assert result == txns
