from unittest.mock import AsyncMock, patch

import pytest
from worker.services.reversal_matcher import find_original_charge


def _group(group_id, txn_type, source, amount, date_str, description="SHOP"):
    return {
        "id": group_id,
        "attributes": {
            "transactions": [
                {
                    "type": txn_type,
                    "source_name": source,
                    "amount": str(amount),
                    "date": date_str,
                    "description": description,
                }
            ]
        },
    }


def _reversal(amount=12.90, time="20:01", merchant="", date_str="2026-04-18"):
    return {
        "amount": amount,
        "date": date_str,
        "time": time,
        "merchant": merchant,
        "card_or_account": "8106",
    }


@pytest.mark.asyncio
async def test_single_match_on_date_time_amount_card():
    existing = [
        _group("42", "withdrawal", "UOB One Account", 12.90, "2026-04-18T20:01:00"),
        _group("43", "withdrawal", "UOB One Account", 5.00, "2026-04-18T20:01:00"),
        _group("44", "withdrawal", "OCBC Savings", 12.90, "2026-04-18T20:01:00"),
    ]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(), "UOB One Account")
    assert len(result) == 1
    assert result[0]["id"] == "42"


@pytest.mark.asyncio
async def test_no_match_returns_empty():
    existing = [_group("1", "withdrawal", "UOB One Account", 99.99, "2026-04-18T20:01:00")]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(), "UOB One Account")
    assert result == []


@pytest.mark.asyncio
async def test_multiple_matches_same_minute():
    existing = [
        _group("1", "withdrawal", "UOB One Account", 12.90, "2026-04-18T20:01:00", "SHOP A"),
        _group("2", "withdrawal", "UOB One Account", 12.90, "2026-04-18T20:01:00", "SHOP B"),
    ]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(merchant=""), "UOB One Account")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_merchant_tiebreaker_narrows_multiple():
    existing = [
        _group("1", "withdrawal", "UOB One Account", 12.90, "2026-04-18T20:01:00", "STARBUCKS"),
        _group("2", "withdrawal", "UOB One Account", 12.90, "2026-04-18T20:01:00", "MCDONALDS"),
    ]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(merchant="Starbucks"), "UOB One Account")
    assert len(result) == 1
    assert result[0]["id"] == "1"


@pytest.mark.asyncio
async def test_excludes_deposits_and_transfers():
    existing = [
        _group("1", "deposit", "UOB One Account", 12.90, "2026-04-18T20:01:00"),
        _group("2", "transfer", "UOB One Account", 12.90, "2026-04-18T20:01:00"),
    ]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(), "UOB One Account")
    assert result == []


@pytest.mark.asyncio
async def test_excludes_wrong_card():
    existing = [_group("1", "withdrawal", "Trust Card", 12.90, "2026-04-18T20:01:00")]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(), "UOB One Account")
    assert result == []


@pytest.mark.asyncio
async def test_excludes_wrong_date():
    existing = [_group("1", "withdrawal", "UOB One Account", 12.90, "2026-04-17T20:01:00")]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(), "UOB One Account")
    assert result == []


@pytest.mark.asyncio
async def test_excludes_wrong_time():
    existing = [_group("1", "withdrawal", "UOB One Account", 12.90, "2026-04-18T15:30:00")]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(time="20:01"), "UOB One Account")
    assert result == []


@pytest.mark.asyncio
async def test_matches_date_only_when_time_missing():
    existing = [_group("1", "withdrawal", "UOB One Account", 12.90, "2026-04-18T15:30:00")]
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        result = await find_original_charge(_reversal(time=None), "UOB One Account")
    assert len(result) == 1


@pytest.mark.asyncio
async def test_no_date_returns_empty():
    with patch(
        "worker.services.reversal_matcher.firefly_client.get_transactions",
        new_callable=AsyncMock,
    ) as mock_get:
        result = await find_original_charge({"amount": 10.0}, "UOB One Account")
    assert result == []
    mock_get.assert_not_called()
