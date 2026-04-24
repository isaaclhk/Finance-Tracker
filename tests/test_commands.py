from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from worker.bot.commands import _parse_period, _parse_single_date, _update_account_balance
from worker.utils.time import today_sgt

# ── _parse_period tests ─────────────────────────────────────────────


def test_parse_period_today():
    result = _parse_period("")
    assert result is not None
    start, end, label = result
    assert start == today_sgt()
    assert end == today_sgt()
    assert label == "today"


def test_parse_period_today_explicit():
    result = _parse_period("today")
    assert result is not None
    assert result[2] == "today"


def test_parse_period_yesterday():
    result = _parse_period("yesterday")
    assert result is not None
    assert result[2] == "yesterday"


def test_parse_period_this_week():
    result = _parse_period("this week")
    assert result is not None
    start, end, label = result
    assert label == "this week"
    assert start.weekday() == 0
    assert end == today_sgt()


def test_parse_period_last_week():
    result = _parse_period("last week")
    assert result is not None
    start, end, label = result
    assert label == "last week"
    assert start.weekday() == 0
    assert (end - start).days == 6


def test_parse_period_this_month():
    result = _parse_period("this month")
    assert result is not None
    start, end, label = result
    assert label == "this month"
    assert start.day == 1
    assert start.month == today_sgt().month


def test_parse_period_last_month():
    result = _parse_period("last month")
    assert result is not None
    start, end, label = result
    assert label == "last month"
    assert start.day == 1
    today = today_sgt()
    expected_month = today.month - 1 if today.month > 1 else 12
    assert start.month == expected_month


def test_parse_period_this_year():
    result = _parse_period("this year")
    assert result is not None
    start, end, label = result
    assert label == "this year"
    assert start.month == 1
    assert start.day == 1
    assert end == today_sgt()


def test_parse_period_last_year():
    result = _parse_period("last year")
    assert result is not None
    start, end, label = result
    assert label == "last year"
    assert start.year == today_sgt().year - 1


def test_parse_period_last_n_days():
    result = _parse_period("last 7 days")
    assert result is not None
    start, end, label = result
    assert label == "last 7 days"
    assert end == today_sgt()


def test_parse_period_last_n_months():
    result = _parse_period("last 3 months")
    assert result is not None
    start, end, label = result
    assert label == "last 3 months"
    assert end == today_sgt()


def test_parse_period_past_n_weeks():
    result = _parse_period("past 2 weeks")
    assert result is not None
    assert result[2] == "last 2 weeks"


def test_parse_period_month_name():
    result = _parse_period("january")
    assert result is not None
    start, end, label = result
    assert start.month == 1
    assert start.day == 1


def test_parse_period_month_abbr():
    result = _parse_period("feb")
    assert result is not None
    assert result[0].month == 2


def test_parse_period_month_with_year():
    result = _parse_period("march 2025")
    assert result is not None
    start, end, label = result
    assert start == date(2025, 3, 1)
    assert end == date(2025, 3, 31)


def test_parse_period_month_range():
    result = _parse_period("jan to mar")
    assert result is not None
    start, end, label = result
    assert start.month == 1
    assert end.month == 3
    assert "Jan" in label
    assert "Mar" in label


def test_parse_period_month_range_with_year():
    result = _parse_period("january to march 2025")
    assert result is not None
    start, end, label = result
    assert start == date(2025, 1, 1)
    assert end == date(2025, 3, 31)


def test_parse_period_month_range_abbr():
    result = _parse_period("feb to mar 2025")
    assert result is not None
    assert result[0].month == 2
    assert result[1] == date(2025, 3, 31)


def test_parse_period_month_range_dash():
    result = _parse_period("jan - mar 2025")
    assert result is not None
    assert result[0].month == 1
    assert result[1] == date(2025, 3, 31)


def test_parse_period_unknown_returns_none():
    result = _parse_period("some random text")
    assert result is None


def test_parse_single_date_named_day():
    result = _parse_single_date("1 jan 2026")
    assert result == date(2026, 1, 1)


def test_parse_single_date_relative_day():
    result = _parse_single_date("yesterday")
    assert result == today_sgt() - timedelta(days=1)


def test_parse_single_date_invalid_returns_none():
    result = _parse_single_date("this month")
    assert result is None


# ── _update_account_balance tests ───────────────────────────────────


def _make_account(name, balance, acct_type="asset"):
    return {
        "id": "1",
        "attributes": {
            "name": name,
            "type": acct_type,
            "current_balance": str(balance),
        },
    }


@pytest.mark.asyncio
async def test_update_asset_account_positive_diff():
    accounts = [_make_account("Syfe Cash+", 8000.0)]

    with (
        patch(
            "worker.bot.commands.firefly_client.get_accounts",
            new_callable=AsyncMock,
            return_value=accounts,
        ),
        patch(
            "worker.bot.commands.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        result = await _update_account_balance("syfe", 8500.0)

    assert result is not None
    assert "8,000.00" in result
    assert "8,500.00" in result

    payload = mock_create.call_args[0][0]
    txn = payload["transactions"][0]
    assert txn["type"] == "transfer"
    assert txn["amount"] == "500.0"
    assert txn["source_name"] == "Market Value Adjustment"
    assert txn["destination_name"] == "Syfe Cash+"


@pytest.mark.asyncio
async def test_update_asset_account_negative_diff():
    accounts = [_make_account("IBKR", 50000.0)]

    with (
        patch(
            "worker.bot.commands.firefly_client.get_accounts",
            new_callable=AsyncMock,
            return_value=accounts,
        ),
        patch(
            "worker.bot.commands.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        result = await _update_account_balance("IBKR", 45000.0)

    assert result is not None
    payload = mock_create.call_args[0][0]
    txn = payload["transactions"][0]
    assert txn["type"] == "transfer"
    assert txn["source_name"] == "IBKR"
    assert txn["destination_name"] == "Market Value Adjustment"


@pytest.mark.asyncio
async def test_update_liability_increase():
    accounts = [_make_account("UOB Credit Card", 500.0, "liabilities")]

    with (
        patch(
            "worker.bot.commands.firefly_client.get_accounts",
            new_callable=AsyncMock,
            return_value=accounts,
        ),
        patch(
            "worker.bot.commands.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        result = await _update_account_balance("UOB Credit Card", 800.0)

    assert result is not None
    payload = mock_create.call_args[0][0]
    txn = payload["transactions"][0]
    assert txn["type"] == "deposit"
    assert txn["source_name"] == "Market Value Adjustment"
    assert txn["destination_name"] == "UOB Credit Card"


@pytest.mark.asyncio
async def test_update_liability_decrease():
    accounts = [_make_account("DBS Card", 1000.0, "liabilities")]

    with (
        patch(
            "worker.bot.commands.firefly_client.get_accounts",
            new_callable=AsyncMock,
            return_value=accounts,
        ),
        patch(
            "worker.bot.commands.firefly_client.create_transaction",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        result = await _update_account_balance("DBS Card", 200.0)

    assert result is not None
    payload = mock_create.call_args[0][0]
    txn = payload["transactions"][0]
    assert txn["type"] == "withdrawal"
    assert txn["source_name"] == "DBS Card"
    assert txn["destination_name"] == "Market Value Adjustment"


@pytest.mark.asyncio
async def test_update_no_change_returns_none():
    accounts = [_make_account("Syfe Cash+", 8500.0)]

    with patch(
        "worker.bot.commands.firefly_client.get_accounts",
        new_callable=AsyncMock,
        return_value=accounts,
    ):
        result = await _update_account_balance("syfe", 8500.0)

    assert result is None


@pytest.mark.asyncio
async def test_update_account_not_found():
    accounts = [_make_account("OCBC Savings", 5000.0)]

    with patch(
        "worker.bot.commands.firefly_client.get_accounts",
        new_callable=AsyncMock,
        return_value=accounts,
    ):
        result = await _update_account_balance("nonexistent", 1000.0)

    assert result is None


@pytest.mark.asyncio
async def test_update_skips_revenue_accounts():
    accounts = [
        {
            "id": "1",
            "attributes": {
                "name": "Salary",
                "type": "revenue",
                "current_balance": "0",
            },
        }
    ]

    with patch(
        "worker.bot.commands.firefly_client.get_accounts",
        new_callable=AsyncMock,
        return_value=accounts,
    ):
        result = await _update_account_balance("Salary", 5000.0)

    assert result is None


@pytest.mark.asyncio
async def test_handle_spent_invalid_period_returns_usage_error():
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(args=["since", "christmas"])

    with patch(
        "worker.bot.commands.firefly_client.get_transactions",
        new_callable=AsyncMock,
    ) as mock_get:
        from worker.bot.commands import handle_spent

        await handle_spent(update, context)

    mock_get.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "Could not understand that period" in reply


@pytest.mark.asyncio
async def test_handle_summary_invalid_period_returns_usage_error():
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(args=["q1", "2026"])

    with patch(
        "worker.bot.commands.firefly_client.get_transactions",
        new_callable=AsyncMock,
    ) as mock_get:
        from worker.bot.commands import handle_summary

        await handle_summary(update, context)

    mock_get.assert_not_called()
    reply = update.message.reply_text.await_args.args[0]
    assert "Could not understand that period" in reply
