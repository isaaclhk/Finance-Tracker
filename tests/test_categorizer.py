from unittest.mock import AsyncMock, patch

import pytest

from worker.services.categorizer import categorize, create_auto_rule


def _firefly_txn(category_name=None):
    txn = {"description": "TEST", "amount": "5.50"}
    if category_name:
        txn["category_name"] = category_name
    return {"attributes": {"transactions": [txn]}}


def test_existing_category_no_confirmation():
    category, needs_confirm = categorize(_firefly_txn("Transport"), "Food & Drink")
    assert category == "Transport"
    assert needs_confirm is False


def test_suggested_category_needs_confirmation():
    category, needs_confirm = categorize(_firefly_txn(), "Food & Drink")
    assert category == "Food & Drink"
    assert needs_confirm is True


def test_no_category_needs_confirmation():
    category, needs_confirm = categorize(_firefly_txn(), None)
    assert category is None
    assert needs_confirm is True


@pytest.mark.asyncio
async def test_create_auto_rule_success():
    with patch(
        "worker.services.categorizer.firefly_client.create_rule",
        new_callable=AsyncMock,
    ) as mock_create:
        await create_auto_rule("BOBER TEA", "Food & Drink")

    mock_create.assert_called_once()
    args = mock_create.call_args
    assert "BOBER TEA" in args[0][0]
    assert args[0][1] == "BOBER TEA"
    assert args[0][2] == "Food & Drink"


@pytest.mark.asyncio
async def test_create_auto_rule_handles_error():
    with patch(
        "worker.services.categorizer.firefly_client.create_rule",
        new_callable=AsyncMock,
        side_effect=Exception("API error"),
    ):
        await create_auto_rule("BOBER TEA", "Food & Drink")
