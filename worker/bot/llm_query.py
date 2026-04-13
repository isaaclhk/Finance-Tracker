import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from worker.config import (
    BOT_PERSONALITY,
    CONVERSATION_HISTORY_LENGTH,
    CONVERSATION_TIMEOUT_MINUTES,
)
from worker.integrations import firefly_client, openai_client

logger = logging.getLogger(__name__)

conversation_histories: dict[int, list[dict]] = defaultdict(list)
last_activity: dict[int, datetime] = {}


def _format_finance_context(accounts: list[dict], transactions: list[dict]) -> str:
    lines = ["ACCOUNTS:"]
    for acct in accounts:
        attrs = acct.get("attributes", {})
        name = attrs.get("name", "?")
        balance = attrs.get("current_balance", "0")
        acct_type = attrs.get("type", "")
        if acct_type in ("asset", "liabilities"):
            lines.append(f"  {name}: ${balance}")

    lines.append("\nRECENT TRANSACTIONS (last 30 days):")
    for txn in transactions[:50]:
        attrs = txn.get("attributes", {})
        for t in attrs.get("transactions", []):
            desc = t.get("description", "?")
            amount = t.get("amount", "0")
            cat = t.get("category_name", "")
            txn_date = t.get("date", "")[:10]
            txn_type = t.get("type", "")
            lines.append(f"  {txn_date} | {desc} | ${amount} | {cat} | {txn_type}")

    return "\n".join(lines)


async def handle_natural_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    question = update.message.text
    now = datetime.now()

    # Check if this chat is waiting for a date input
    from worker.bot.callbacks import pending_date_input

    if chat_id in pending_date_input:
        await _handle_pending_date(update, chat_id, question)
        return

    # Reset history if inactive
    if chat_id in last_activity:
        if now - last_activity[chat_id] > timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES):
            conversation_histories.pop(chat_id, None)
    last_activity[chat_id] = now

    # Fetch financial data
    today = date.today()
    start = today - timedelta(days=30)
    try:
        accounts = await firefly_client.get_accounts()
        transactions = await firefly_client.get_transactions(start_date=start, end_date=today)
    except Exception:
        logger.exception("Failed to fetch financial data for query")
        await update.message.reply_text("Sorry, I couldn't fetch your financial data right now.")
        return

    finance_context = _format_finance_context(accounts, transactions)

    messages = [
        {
            "role": "system",
            "content": (
                f"{BOT_PERSONALITY}\n\n"
                f"Today's date is {today.isoformat()}.\n\n"
                f"FINANCIAL DATA:\n{finance_context}"
            ),
        },
        *conversation_histories[chat_id],
        {"role": "user", "content": question},
    ]

    answer = await openai_client.query(messages)

    # Update history
    history = conversation_histories[chat_id]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})

    # Trim to configured length
    max_messages = CONVERSATION_HISTORY_LENGTH * 2
    if len(history) > max_messages:
        conversation_histories[chat_id] = history[-max_messages:]

    await update.message.reply_text(answer)


async def _handle_pending_date(update, chat_id: int, text: str):
    from worker.bot.callbacks import pending_date_input
    from worker.bot.commands import _llm_parse_period, _parse_period

    txn_id = pending_date_input.pop(chat_id)

    # Parse the date
    result = _parse_period(text.strip())
    if not result:
        result = await _llm_parse_period(text.strip())

    if not result:
        await update.message.reply_text("Could not understand that date. Income kept as today.")
        return

    new_date = result[0]
    date_str = new_date.strftime("%d %b %Y")

    try:
        await firefly_client.update_transaction(
            int(txn_id),
            {"transactions": [{"date": new_date.isoformat()}]},
        )
        await update.message.reply_text(f"📅 Date set to {date_str}")
    except Exception:
        logger.exception("Failed to update transaction date %s", txn_id)
        await update.message.reply_text("❌ Failed to change date.")
