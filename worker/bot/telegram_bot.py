import logging
from datetime import datetime

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
from worker.utils.time import now_sgt

logger = logging.getLogger(__name__)

_application: Application | None = None
_last_telegram_activity: datetime | None = None


def get_last_telegram_activity() -> datetime | None:
    return _last_telegram_activity


def _is_authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    return chat_id == TELEGRAM_CHAT_ID


def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        global _last_telegram_activity
        _last_telegram_activity = now_sgt()
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
            handle_income,
            handle_lastupdate,
            handle_refresh,
            handle_salary,
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
        _application.add_handler(CommandHandler("income", auth_required(handle_income)))
        _application.add_handler(CommandHandler("salary", auth_required(handle_salary)))
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
        f"Check the email yourself lah",
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


async def send_large_amount_confirmation(parsed: dict, foreign_info: dict | None = None):
    merchant = parsed.get("merchant", "Unknown")
    amount = parsed.get("amount", 0)
    extra = ""
    if foreign_info and foreign_info.get("rate") is not None:
        fc = foreign_info["currency"]
        fa = foreign_info["original_amount"]
        extra = f"\n💱 {fc} {fa:,.2f}"
    await send_message(
        f"💰 Wah, big purchase!\n──────────\n🏪 {merchant}\n💵 <b>${amount:,.2f}</b>{extra}",
        parse_mode="HTML",
    )


async def notify_pending_reviews(pending_review: list[dict]):
    for item in pending_review:
        if item["type"] == "category_confirmation":
            await ask_category_confirmation(
                transaction=item["transaction"],
                suggested_category=item.get("suggested_category"),
                parsed=item["parsed"],
                foreign_info=item.get("foreign_info"),
            )
            if item.get("large_amount"):
                await send_large_amount_confirmation(
                    item["parsed"], foreign_info=item.get("foreign_info")
                )
        elif item["type"] == "unknown_account":
            await notify_unknown_account(item["parsed"])
        elif item["type"] == "reversal_applied":
            await notify_reversal_applied(item["parsed"], item["deleted"])
        elif item["type"] == "reversal_orphan":
            await notify_reversal_orphan(item["parsed"])
        elif item["type"] == "reversal_ambiguous":
            await notify_reversal_ambiguous(item["parsed"], item["candidates"])


def _first_sub(group: dict) -> dict:
    txns = group.get("attributes", {}).get("transactions", [])
    return txns[0] if txns else {}


async def notify_reversal_applied(parsed: dict, deleted: dict):
    sub = _first_sub(deleted)
    amount = parsed.get("amount", "?")
    merchant = sub.get("description") or parsed.get("merchant") or "Unknown"
    txn_date = (sub.get("date") or parsed.get("date") or "")[:16].replace("T", " ")
    await send_message(
        f"↩️ Reversal applied — deleted original\n"
        f"──────────\n"
        f"🏪 {merchant}\n"
        f"💵 <b>${amount}</b>\n"
        f"📅 {txn_date}",
        parse_mode="HTML",
    )


async def notify_reversal_orphan(parsed: dict):
    amount = parsed.get("amount", "?")
    card = parsed.get("card_or_account", "?")
    bank = parsed.get("bank", "?")
    txn_date = parsed.get("date", "")
    txn_time = parsed.get("time", "")
    time_str = f" {txn_time}" if txn_time else ""
    await send_message(
        f"⚠️ Reversal but no matching charge found\n"
        f"──────────\n"
        f"💳 {bank} *{card}\n"
        f"💵 <b>${amount}</b>\n"
        f"📅 {txn_date}{time_str}\n\n"
        f"Check Firefly yourself lah",
        parse_mode="HTML",
    )


async def notify_reversal_ambiguous(parsed: dict, candidates: list[dict]):
    amount = parsed.get("amount", "?")
    lines = [f"❓ Reversal but {len(candidates)} possible matches", "──────────"]
    for group in candidates:
        sub = _first_sub(group)
        d = (sub.get("date") or "")[:16].replace("T", " ")
        desc = sub.get("description") or "?"
        lines.append(f"• {d} — {desc} (id {group.get('id')})")
    lines.append("")
    lines.append(f"💵 Amount: <b>${amount}</b>")
    lines.append("Delete the right one in Firefly yourself")
    await send_message("\n".join(lines), parse_mode="HTML")


async def ask_category_confirmation(
    transaction: dict,
    suggested_category: str | None,
    parsed: dict,
    foreign_info: dict | None = None,
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

    amount_line = f"💵 <b>${amount:,.2f}</b> · {bank} *{card}"
    if foreign_info:
        fc = foreign_info["currency"]
        fa = foreign_info["original_amount"]
        if foreign_info.get("rate") is not None:
            amount_line += f"\n    ({fc} {fa:,.2f} @ {foreign_info['rate']:.4f})"
        else:
            amount_line += f"\n    ⚠️ {fc} {fa:,.2f} (rate lookup failed)"

    text = (
        f"<b>🆕 New transaction</b>\n"
        f"──────────\n"
        f"🏪 {merchant}\n"
        f"{amount_line}\n"
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
