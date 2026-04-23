from unittest.mock import AsyncMock, patch

import pytest
from worker.utils.dedup import is_duplicate


def _firefly_txn(
    amount,
    description,
    txn_date="2026-03-25",
    source_name="UOB Credit Card",
    destination_name="Merchant",
):
    return {
        "attributes": {
            "transactions": [
                {
                    "amount": str(amount),
                    "description": description,
                    "date": txn_date,
                    "source_name": source_name,
                    "destination_name": destination_name,
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
async def test_no_duplicate_different_account():
    existing = [_firefly_txn(5.50, "BOBER TEA ION ORCHARD", source_name="Trust Card")]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate(
            {
                "amount": 5.50,
                "merchant": "BOBER TEA",
                "date": "2026-03-25",
            },
            source_account="UOB Credit Card",
        )

    assert result is False


@pytest.mark.asyncio
async def test_duplicate_with_same_account_and_time_even_if_merchant_differs():
    existing = [
        _firefly_txn(
            5.50,
            "COFFEE",
            txn_date="2026-03-25T14:15:00",
            source_name="UOB Credit Card",
        )
    ]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate(
            {
                "amount": 5.50,
                "merchant": "BOBER TEA",
                "date": "2026-03-25",
                "time": "14:15",
            },
            source_account="UOB Credit Card",
        )

    assert result is True


@pytest.mark.asyncio
async def test_no_duplicate_same_merchant_amount_but_different_time():
    existing = [
        _firefly_txn(
            5.50,
            "BOBER TEA ION ORCHARD",
            txn_date="2026-03-25T14:15:00",
            source_name="UOB Credit Card",
        )
    ]

    with patch(
        "worker.utils.dedup.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await is_duplicate(
            {
                "amount": 5.50,
                "merchant": "BOBER TEA",
                "date": "2026-03-25",
                "time": "15:15",
            },
            source_account="UOB Credit Card",
        )

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
