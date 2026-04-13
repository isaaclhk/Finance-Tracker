from unittest.mock import AsyncMock, patch

import pytest
from worker.bot.callbacks import CODE_BY_NAME


@pytest.mark.asyncio
async def test_ask_category_confirmation_basic():
    parsed = {
        "merchant": "BOBER TEA",
        "amount": 5.50,
        "card_or_account": "1234",
        "bank": "UOB",
        "date": "25/03/2026",
        "time": "14:15",
    }
    transaction = {"id": "42"}
    suggested = "Food & Drink"

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import ask_category_confirmation

        await ask_category_confirmation(
            transaction=transaction,
            suggested_category=suggested,
            parsed=parsed,
        )

    mock_send.assert_called_once()
    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "BOBER TEA" in text
    assert "$5.50" in text
    assert "Food & Drink" in text
    assert "UOB *1234" in text

    markup = mock_send.call_args.kwargs["reply_markup"]
    buttons = markup.inline_keyboard
    # First row: confirm suggested category
    assert "Food & Drink" in buttons[0][0].text
    code = CODE_BY_NAME["Food & Drink"]
    assert buttons[0][0].callback_data == f"cat:42:{code}"
    # Second row: pick another
    assert "Pick another" in buttons[1][0].text
    assert buttons[1][0].callback_data == "cat:42:OTHER"


@pytest.mark.asyncio
async def test_ask_category_confirmation_with_foreign_info():
    parsed = {
        "merchant": "GRAB THAILAND",
        "amount": 67.0,
        "card_or_account": "5678",
        "bank": "UOB",
        "date": "25/03/2026",
        "time": "",
    }
    transaction = {"id": "99"}
    foreign_info = {"currency": "THB", "original_amount": 350.0, "rate": 0.0383}

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import ask_category_confirmation

        await ask_category_confirmation(
            transaction=transaction,
            suggested_category="Transport",
            parsed=parsed,
            foreign_info=foreign_info,
        )

    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "GRAB THAILAND" in text
    assert "$67.00" in text
    assert "THB" in text
    assert "350.00" in text
    assert "0.0383" in text


@pytest.mark.asyncio
async def test_ask_category_confirmation_no_suggested_category():
    parsed = {
        "merchant": "UNKNOWN SHOP",
        "amount": 10.0,
        "card_or_account": "9999",
        "bank": "DBS",
        "date": "01/04/2026",
        "time": "",
    }
    transaction = {"id": "50"}

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import ask_category_confirmation

        await ask_category_confirmation(
            transaction=transaction,
            suggested_category=None,
            parsed=parsed,
        )

    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "not sure leh" in text

    markup = mock_send.call_args.kwargs["reply_markup"]
    buttons = markup.inline_keyboard
    # Only "Pick another" button, no confirm button
    assert len(buttons) == 1
    assert "Pick another" in buttons[0][0].text


@pytest.mark.asyncio
async def test_send_large_amount_confirmation_basic():
    parsed = {"merchant": "APPLE STORE", "amount": 2499.0}

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import send_large_amount_confirmation

        await send_large_amount_confirmation(parsed)

    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "APPLE STORE" in text
    assert "$2,499.00" in text
    assert "big purchase" in text.lower() or "Wah" in text


@pytest.mark.asyncio
async def test_send_large_amount_confirmation_with_foreign_info():
    parsed = {"merchant": "LOUIS VUITTON", "amount": 5000.0}
    foreign_info = {"currency": "EUR", "original_amount": 3200.0, "rate": 1.5625}

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import send_large_amount_confirmation

        await send_large_amount_confirmation(parsed, foreign_info=foreign_info)

    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "$5,000.00" in text
    assert "EUR" in text
    assert "3,200.00" in text


@pytest.mark.asyncio
async def test_send_large_amount_confirmation_foreign_rate_none():
    """When rate lookup failed, foreign line should not appear."""
    parsed = {"merchant": "SHOP", "amount": 1000.0}
    foreign_info = {"currency": "USD", "original_amount": 700.0, "rate": None}

    with patch("worker.bot.telegram_bot.send_message", new_callable=AsyncMock) as mock_send:
        from worker.bot.telegram_bot import send_large_amount_confirmation

        await send_large_amount_confirmation(parsed, foreign_info=foreign_info)

    text = mock_send.call_args.kwargs.get("text") or mock_send.call_args[0][0]
    assert "USD" not in text


@pytest.mark.asyncio
async def test_notify_pending_reviews_dispatches_category_confirmation():
    pending = [
        {
            "type": "category_confirmation",
            "transaction": {"id": "1"},
            "parsed": {"merchant": "TEST", "amount": 10.0},
            "suggested_category": "Food & Drink",
            "foreign_info": None,
            "large_amount": False,
        }
    ]

    with (
        patch(
            "worker.bot.telegram_bot.ask_category_confirmation",
            new_callable=AsyncMock,
        ) as mock_cat,
        patch(
            "worker.bot.telegram_bot.send_large_amount_confirmation",
            new_callable=AsyncMock,
        ) as mock_large,
        patch(
            "worker.bot.telegram_bot.notify_unknown_account",
            new_callable=AsyncMock,
        ) as mock_unknown,
    ):
        from worker.bot.telegram_bot import notify_pending_reviews

        await notify_pending_reviews(pending)

    mock_cat.assert_called_once_with(
        transaction={"id": "1"},
        suggested_category="Food & Drink",
        parsed={"merchant": "TEST", "amount": 10.0},
        foreign_info=None,
    )
    mock_large.assert_not_called()
    mock_unknown.assert_not_called()


@pytest.mark.asyncio
async def test_notify_pending_reviews_large_amount():
    parsed = {"merchant": "ROLEX", "amount": 15000.0}
    pending = [
        {
            "type": "category_confirmation",
            "transaction": {"id": "2"},
            "parsed": parsed,
            "suggested_category": "Shopping",
            "foreign_info": None,
            "large_amount": True,
        }
    ]

    with (
        patch(
            "worker.bot.telegram_bot.ask_category_confirmation",
            new_callable=AsyncMock,
        ) as mock_cat,
        patch(
            "worker.bot.telegram_bot.send_large_amount_confirmation",
            new_callable=AsyncMock,
        ) as mock_large,
    ):
        from worker.bot.telegram_bot import notify_pending_reviews

        await notify_pending_reviews(pending)

    mock_cat.assert_called_once()
    mock_large.assert_called_once_with(parsed, foreign_info=None)


@pytest.mark.asyncio
async def test_notify_pending_reviews_unknown_account():
    parsed = {"card_or_account": "9999", "bank": "HSBC", "merchant": "SHOP", "amount": 50.0}
    pending = [{"type": "unknown_account", "parsed": parsed}]

    with (
        patch(
            "worker.bot.telegram_bot.ask_category_confirmation",
            new_callable=AsyncMock,
        ) as mock_cat,
        patch(
            "worker.bot.telegram_bot.notify_unknown_account",
            new_callable=AsyncMock,
        ) as mock_unknown,
    ):
        from worker.bot.telegram_bot import notify_pending_reviews

        await notify_pending_reviews(pending)

    mock_cat.assert_not_called()
    mock_unknown.assert_called_once_with(parsed)
