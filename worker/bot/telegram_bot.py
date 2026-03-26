import logging

from telegram import Bot, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from worker.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_application: Application | None = None


def _is_authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    return chat_id == TELEGRAM_CHAT_ID


def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            return
        return await func(update, context)

    return wrapper


def get_application() -> Application:
    global _application
    if _application is None:
        from worker.bot.callbacks import handle_category_callback
        from worker.bot.commands import (
            handle_balance,
            handle_help,
            handle_refresh,
            handle_spent,
            handle_summary,
            handle_update,
        )
        from worker.bot.llm_query import handle_natural_query

        _application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        _application.add_handler(CommandHandler("refresh", auth_required(handle_refresh)))
        _application.add_handler(CommandHandler("balance", auth_required(handle_balance)))
        _application.add_handler(CommandHandler("spent", auth_required(handle_spent)))
        _application.add_handler(CommandHandler("summary", auth_required(handle_summary)))
        _application.add_handler(CommandHandler("update", auth_required(handle_update)))
        _application.add_handler(CommandHandler("help", auth_required(handle_help)))
        _application.add_handler(CallbackQueryHandler(auth_required(handle_category_callback)))
        _application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                auth_required(handle_natural_query),
            )
        )

    return _application


def get_bot() -> Bot:
    return get_application().bot


async def send_message(text: str, **kwargs):
    bot = get_bot()
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, **kwargs)


async def notify_parse_failure(parsed: dict):
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", "?")
    await send_message(f"Failed to parse transaction: {merchant} ${amount}")


async def notify_unknown_account(parsed: dict):
    card = parsed.get("card_or_account", "?")
    bank = parsed.get("bank", "?")
    merchant = parsed.get("merchant", "?")
    amount = parsed.get("amount", "?")
    await send_message(
        f"Unknown account: card/account {card} ({bank})\n"
        f"Transaction: {merchant} ${amount}\n"
        f"Please add this card to the account map."
    )


async def send_large_amount_confirmation(parsed: dict):
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", 0)
    await send_message(f"Large transaction detected: ${amount:,.2f} at {merchant}")


async def ask_category_confirmation(
    transaction: dict, suggested_category: str | None, parsed: dict
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    txn_id = transaction.get("id", "0")
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", 0)
    card = parsed.get("card_or_account", "")
    bank = parsed.get("bank", "")
    txn_date = parsed.get("date", "")
    txn_time = parsed.get("time", "")

    time_str = f", {txn_time}" if txn_time else ""

    text = (
        f"New merchant detected\n\n"
        f"{merchant}\n"
        f"SGD {amount:,.2f} — {bank} *{card}\n"
        f"{txn_date}{time_str}\n\n"
        f"Suggested: {suggested_category or 'Unknown'}"
    )

    # Short category codes for callback data (64-byte limit)
    quick_categories = [
        ("Food & Drink", "FD"),
        ("Groceries", "GR"),
        ("Transport", "TR"),
        ("Shopping", "SH"),
    ]

    buttons = []
    row = []
    for name, code in quick_categories:
        row.append(InlineKeyboardButton(name, callback_data=f"cat:{txn_id}:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("Other...", callback_data=f"cat:{txn_id}:OTHER")])

    await send_message(text, reply_markup=InlineKeyboardMarkup(buttons))
