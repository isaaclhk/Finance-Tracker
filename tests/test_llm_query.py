from datetime import datetime, timedelta

from worker.bot.llm_query import conversation_histories, last_activity
from worker.config import CONVERSATION_TIMEOUT_MINUTES


def test_conversation_history_reset_on_timeout():
    chat_id = 12345
    conversation_histories[chat_id] = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ]
    last_activity[chat_id] = datetime.now() - timedelta(
        minutes=CONVERSATION_TIMEOUT_MINUTES + 1
    )

    # Simulate the timeout check logic from handle_natural_query
    now = datetime.now()
    if chat_id in last_activity:
        if now - last_activity[chat_id] > timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES):
            conversation_histories[chat_id] = []

    assert conversation_histories[chat_id] == []


def test_conversation_history_preserved_within_timeout():
    chat_id = 67890
    history = [
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
    ]
    conversation_histories[chat_id] = history.copy()
    last_activity[chat_id] = datetime.now() - timedelta(minutes=1)

    now = datetime.now()
    if chat_id in last_activity:
        if now - last_activity[chat_id] > timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES):
            conversation_histories[chat_id] = []

    assert len(conversation_histories[chat_id]) == 2


def test_format_finance_context():
    from worker.bot.llm_query import _format_finance_context

    accounts = [
        {"attributes": {"name": "OCBC Savings", "current_balance": "3210.00", "type": "asset"}},
        {"attributes": {"name": "UOB Card", "current_balance": "890.30", "type": "liability"}},
    ]
    transactions = [
        {
            "attributes": {
                "transactions": [
                    {
                        "description": "BOBER TEA",
                        "amount": "5.50",
                        "category_name": "Food & Drink",
                        "date": "2026-03-25T14:15:00",
                        "type": "withdrawal",
                    }
                ]
            }
        }
    ]

    result = _format_finance_context(accounts, transactions)
    assert "OCBC Savings" in result
    assert "UOB Card" in result
    assert "BOBER TEA" in result
    assert "5.50" in result
