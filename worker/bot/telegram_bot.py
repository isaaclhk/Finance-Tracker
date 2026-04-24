import logging
from datetime import datetime
from html import escape

import httpx
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
from worker.integrations import firefly_client
from worker.utils.time import now_sgt

logger = logging.getLogger(__name__)

_application: Application | None = None
_last_telegram_activity: datetime | None = None


def _h(value: object) -> str:
    return escape(str(value), quote=False)


def _email_field(email: object, name: str, default: str = "?") -> str:
    return str(getattr(email, name, default) or default)


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
                auth_required(handle_plain_text),
            )
        )

    return _application


def get_bot() -> Bot:
    return get_application().bot


async def send_message(text: str, **kwargs):
    bot = get_bot()
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, **kwargs)


async def handle_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from worker.bot.callbacks import pending_date_input

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    if chat_id in pending_date_input:
        await _handle_pending_date_reply(update, chat_id, text)
        return

    await update.message.reply_text("Use /help or a slash command.")


async def _handle_pending_date_reply(update: Update, chat_id: int, text: str):
    from worker.bot.callbacks import pending_date_input
    from worker.bot.commands import SUPPORTED_DATE_EXAMPLES, _parse_single_date

    txn_id = pending_date_input.get(chat_id)
    new_date = _parse_single_date(text)
    if txn_id is None:
        return

    if not new_date:
        await update.message.reply_text(
            f"Could not understand that date. Try: {SUPPORTED_DATE_EXAMPLES}."
        )
        return

    try:
        await firefly_client.update_transaction(
            int(txn_id),
            {"transactions": [{"date": new_date.isoformat()}]},
        )
    except httpx.HTTPStatusError:
        logger.exception("Failed to update transaction date %s", txn_id)
        await update.message.reply_text("Failed to change date.")
        return

    pending_date_input.pop(chat_id, None)
    await update.message.reply_text(f"Date set to {new_date.strftime('%d %b %Y')}")


async def notify_parse_failure(email: object):
    sender = _h(_email_field(email, "sender"))
    subject = _h(_email_field(email, "subject", "Bank alert"))
    await send_message(
        f"<b>⚠️ Bank alert not recorded yet</b>\n"
        f"──────────\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n\n"
        f"I could not read this alert reliably, so I will retry it on the next poll.",
        parse_mode="HTML",
    )


async def notify_unknown_account(parsed: dict):
    card = _h(parsed.get("card_or_account") or "?")
    bank = _h(parsed.get("bank") or "?")
    merchant = _h(parsed.get("merchant") or "?")
    amount = parsed.get("amount", "?")
    await send_message(
        f"<b>❓ Account needs mapping</b>\n"
        f"──────────\n"
        f"💳 Card *{card} ({bank})\n"
        f"🏪 {merchant} · <b>${amount}</b>\n\n"
        f"This is not recorded yet. Add this card/account to ACCOUNT_MAP; "
        f"I will retry it on the next poll.",
        parse_mode="HTML",
    )


async def notify_validation_failed(parsed: dict, warnings: list[str]):
    merchant = _h(parsed.get("merchant") or "Unknown")
    amount = parsed.get("amount", "?")
    reason = _h(", ".join(warnings) or "validation_failed")
    await send_message(
        f"<b>⚠️ Transaction not recorded yet</b>\n"
        f"──────────\n"
        f"🏪 {merchant}\n"
        f"💵 <b>${amount}</b>\n"
        f"Reason: {reason}\n\n"
        f"I will retry it on the next poll so it does not get lost.",
        parse_mode="HTML",
    )


async def notify_needs_review(email: object, parsed: dict):
    sender = _h(_email_field(email, "sender"))
    subject = _h(_email_field(email, "subject", "Bank alert"))
    reason = _h(parsed.get("non_transaction_reason") or "missing transaction details")
    await send_message(
        f"<b>⚠️ Bank alert needs review</b>\n"
        f"──────────\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Reason: {reason}\n\n"
        f"I did not record this alert. I will not keep retrying it automatically.",
        parse_mode="HTML",
    )


async def notify_conversion_failed(parsed: dict, foreign_info: dict):
    merchant = _h(parsed.get("merchant") or "Unknown")
    currency = _h(foreign_info.get("currency", "?"))
    amount = foreign_info.get("original_amount", "?")
    await send_message(
        f"<b>⚠️ Currency conversion unavailable</b>\n"
        f"──────────\n"
        f"🏪 {merchant}\n"
        f"💱 {currency} {amount}\n\n"
        f"I did not record this as SGD. I will retry when rates are available.",
        parse_mode="HTML",
    )


async def notify_processing_error(email: object):
    sender = _h(_email_field(email, "sender"))
    subject = _h(_email_field(email, "subject", "Bank alert"))
    await send_message(
        f"<b>⚠️ Bank alert processing failed</b>\n"
        f"──────────\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n\n"
        f"I kept the Gmail cursor in place so this alert can be retried.",
        parse_mode="HTML",
    )


async def notify_bill_payment_reminder(reminder: dict):
    bank = _h(reminder.get("bank") or "Bank")
    account = _h(reminder.get("account") or "credit card")
    days_left = reminder.get("due_in_days")
    due_date = reminder.get("due_date")

    if days_left is None:
        due_line = "Payment is due soon."
    else:
        day_word = "day" if days_left == 1 else "days"
        due_line = f"Payment is due in {days_left} {day_word}."

    if due_date:
        due_line = f"{due_line} Due date: {_h(due_date)}."

    await send_message(
        f"💳 <b>{bank} card bill reminder</b>\n"
        f"──────────\n"
        f"{due_line}\n"
        f"Please pay the {account} bill.",
        parse_mode="HTML",
    )


async def send_large_amount_confirmation(parsed: dict, foreign_info: dict | None = None):
    merchant = _h(parsed.get("merchant") or "Unknown")
    amount = parsed.get("amount", 0)
    extra = ""
    if foreign_info and foreign_info.get("rate") is not None:
        fc = foreign_info["currency"]
        fa = foreign_info["original_amount"]
        extra = f"\n💱 {fc} {fa:,.2f}"
    await send_message(
        f"💰 Large transaction noted\n──────────\n🏪 {merchant}\n💵 <b>${amount:,.2f}</b>{extra}",
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
        elif item["type"] == "parse_failure":
            await notify_parse_failure(item["email"])
        elif item["type"] == "validation_failed":
            await notify_validation_failed(item["parsed"], item.get("warnings", []))
        elif item["type"] == "needs_review":
            await notify_needs_review(item["email"], item["parsed"])
        elif item["type"] == "conversion_failed":
            await notify_conversion_failed(item["parsed"], item["foreign_info"])
        elif item["type"] == "processing_error":
            await notify_processing_error(item["email"])
        elif item["type"] == "bill_payment_reminder":
            await notify_bill_payment_reminder(item)
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
    merchant = _h(sub.get("description") or parsed.get("merchant") or "Unknown")
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
    card = _h(parsed.get("card_or_account") or "?")
    bank = _h(parsed.get("bank") or "?")
    txn_date = parsed.get("date", "")
    txn_time = parsed.get("time", "")
    time_str = f" {txn_time}" if txn_time else ""
    await send_message(
        f"⚠️ Reversal but no matching charge found\n"
        f"──────────\n"
        f"💳 {bank} *{card}\n"
        f"💵 <b>${amount}</b>\n"
        f"📅 {txn_date}{time_str}\n\n"
        f"Please check Firefly when convenient.",
        parse_mode="HTML",
    )


async def notify_reversal_ambiguous(parsed: dict, candidates: list[dict]):
    amount = parsed.get("amount", "?")
    lines = [f"❓ Reversal but {len(candidates)} possible matches", "──────────"]
    for group in candidates:
        sub = _first_sub(group)
        d = (sub.get("date") or "")[:16].replace("T", " ")
        desc = _h(sub.get("description") or "?")
        lines.append(f"• {d} — {desc} (id {group.get('id')})")
    lines.append("")
    lines.append(f"💵 Amount: <b>${amount}</b>")
    lines.append("Please delete the right one in Firefly.")
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
    merchant = _h(parsed.get("merchant") or "Unknown")
    amount = parsed.get("amount", 0)
    card = _h(parsed.get("card_or_account") or "")
    bank = _h(parsed.get("bank") or "")
    txn_date = parsed.get("date", "")
    txn_time = parsed.get("time", "")

    time_str = f" {txn_time}" if txn_time else ""
    suggested_label = _h(suggested_category) if suggested_category else "Not sure yet"

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
        f"💡 Suggested category: <b>{suggested_label}</b>"
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
    buttons.append(
        [InlineKeyboardButton("📋 Choose category", callback_data=f"cat:{txn_id}:OTHER")]
    )

    await send_message(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
