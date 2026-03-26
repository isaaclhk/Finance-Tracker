from unittest.mock import AsyncMock, patch

import pytest

from worker.utils.dedup import is_duplicate


def _firefly_txn(amount, description, txn_date="2026-03-25"):
    return {
        "attributes": {
            "transactions": [
                {
                    "amount": str(amount),
                    "description": description,
                    "date": txn_date,
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_duplicate_found():
    existing = [_firefly_txn(5.50, "BOBER TEA ION ORCHARD")]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate({
            "amount": 5.50,
            "merchant": "BOBER TEA",
            "date": "2026-03-25",
        })

    assert result is True


@pytest.mark.asyncio
async def test_no_duplicate_different_amount():
    existing = [_firefly_txn(10.00, "BOBER TEA ION ORCHARD")]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate({
            "amount": 5.50,
            "merchant": "BOBER TEA",
            "date": "2026-03-25",
        })

    assert result is False


@pytest.mark.asyncio
async def test_no_duplicate_different_merchant():
    existing = [_firefly_txn(5.50, "STARBUCKS")]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate({
            "amount": 5.50,
            "merchant": "BOBER TEA",
            "date": "2026-03-25",
        })

    assert result is False


@pytest.mark.asyncio
async def test_no_duplicate_empty_existing():
    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await is_duplicate({
            "amount": 5.50,
            "merchant": "BOBER TEA",
            "date": "2026-03-25",
        })

    assert result is False


@pytest.mark.asyncio
async def test_no_date_returns_false():
    result = await is_duplicate({"amount": 5.50, "merchant": "TEST"})
    assert result is False
