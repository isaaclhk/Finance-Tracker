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
            handle_lastupdate,
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
        _application.add_handler(CommandHandler("lastupdate", auth_required(handle_lastupdate)))
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
    await send_message(
        f"⚠️ Aiyo, cannot read this one\n"
        f"──────────\n"
        f"🏪 {merchant} · <b>${amount}</b>\n\n"
        f"Check the email manually lah",
        parse_mode="HTML",
    )


async def notify_unknown_account(parsed: dict):
    card = parsed.get("card_or_account", "?")
    bank = parsed.get("bank", "?")
    merchant = parsed.get("merchant", "?")
    amount = parsed.get("amount", "?")
    await send_message(
        f"❓ Eh, which account is this?\n"
        f"──────────\n"
        f"💳 Card *{card} ({bank})\n"
        f"🏪 {merchant} · <b>${amount}</b>\n\n"
        f"Add this card to ACCOUNT_MAP in .env",
        parse_mode="HTML",
    )


async def send_large_amount_confirmation(parsed: dict):
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", 0)
    await send_message(
        f"💰 Wah, big purchase sia!\n──────────\n🏪 {merchant}\n💵 <b>${amount:,.2f}</b>",
        parse_mode="HTML",
    )


async def ask_category_confirmation(
    transaction: dict, suggested_category: str | None, parsed: dict
):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from worker.bot.callbacks import CODE_BY_NAME

    txn_id = transaction.get("id", "0")
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", 0)
    card = parsed.get("card_or_account", "")
    bank = parsed.get("bank", "")
    txn_date = parsed.get("date", "")
    txn_time = parsed.get("time", "")

    time_str = f" {txn_time}" if txn_time else ""

    text = (
        f"<b>🆕 New merchant ah!</b>\n"
        f"──────────\n"
        f"🏪 {merchant}\n"
        f"💵 <b>${amount:,.2f}</b> · {bank} *{card}\n"
        f"📅 {txn_date}{time_str}\n"
        f"──────────\n"
        f"💡 I think is: <b>{suggested_category or 'not sure leh'}</b>"
    )

    buttons = []
    if suggested_category and suggested_category in CODE_BY_NAME:
        code = CODE_BY_NAME[suggested_category]
        buttons.append(
            [
                InlineKeyboardButton(
                    f"✅ Yes, {suggested_category}", callback_data=f"cat:{txn_id}:{code}"
                )
            ]
        )
    buttons.append([InlineKeyboardButton("📋 Pick another", callback_data=f"cat:{txn_id}:OTHER")])

    await send_message(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
