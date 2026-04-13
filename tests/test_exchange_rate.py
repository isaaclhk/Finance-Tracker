from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from worker.integrations import exchange_rate


@pytest.fixture(autouse=True)
def reset_client():
    exchange_rate._client = None
    yield
    exchange_rate._client = None


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_convert_to_sgd_success():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response({"rates": {"SGD": 1.34}}))

    with patch.object(exchange_rate, "get_client", return_value=mock_client):
        result = await exchange_rate.convert_to_sgd(50.0, "USD")

    assert result == (67.0, 1.34)
    mock_client.get.assert_called_once_with(
        "/latest", params={"from": "USD", "to": "SGD", "amount": 1}
    )


@pytest.mark.asyncio
async def test_convert_to_sgd_returns_none_for_sgd():
    result = await exchange_rate.convert_to_sgd(100.0, "SGD")
    assert result is None


@pytest.mark.asyncio
async def test_convert_to_sgd_case_insensitive():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response({"rates": {"SGD": 1.80}}))

    with patch.object(exchange_rate, "get_client", return_value=mock_client):
        result = await exchange_rate.convert_to_sgd(100.0, "gbp")

    assert result == (180.0, 1.80)


@pytest.mark.asyncio
async def test_convert_to_sgd_returns_none_on_api_failure():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("API error"))

    with patch.object(exchange_rate, "get_client", return_value=mock_client):
        result = await exchange_rate.convert_to_sgd(50.0, "USD")

    assert result is None


@pytest.mark.asyncio
async def test_convert_to_sgd_rounds_to_2_decimals():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response({"rates": {"SGD": 0.00917}}))

    with patch.object(exchange_rate, "get_client", return_value=mock_client):
        result = await exchange_rate.convert_to_sgd(12000, "JPY")

    assert result is not None
    sgd_amount, rate = result
    assert sgd_amount == 110.04
    assert rate == 0.00917
