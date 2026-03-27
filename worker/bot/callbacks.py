import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from worker.integrations import firefly_client
from worker.integrations.openai_client import CATEGORIES
from worker.services.categorizer import create_auto_rule

logger = logging.getLogger(__name__)

# Short code -> full category name
CATEGORY_CODES = {
    "FD": "Food & Drink",
    "GR": "Groceries",
    "TR": "Transport",
    "SH": "Shopping",
    "HE": "Health",
    "SU": "Subscriptions",
    "UT": "Utilities",
    "ED": "Education",
    "HO": "Housing",
    "MI": "Misc",
}

# Reverse lookup
CODE_BY_NAME = {v: k for k, v in CATEGORY_CODES.items()}


async def handle_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("cat:"):
        return

    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    _, txn_id, code = parts

    if code == "OTHER":
        await _show_all_categories(query, txn_id)
        return

    category = CATEGORY_CODES.get(code)
    if not category:
        await query.edit_message_text("Unknown category code.")
        return

    await _apply_category(query, txn_id, category)


async def _show_all_categories(query, txn_id: str):
    buttons = []
    row = []
    for name in CATEGORIES:
        code = CODE_BY_NAME.get(name, name[:2].upper())
        row.append(InlineKeyboardButton(name, callback_data=f"cat:{txn_id}:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))


async def _apply_category(query, txn_id: str, category: str):
    try:
        await firefly_client.update_transaction(
            int(txn_id),
            {"transactions": [{"category_name": category}]},
        )
    except Exception:
        logger.exception("Failed to update transaction %s", txn_id)
        await query.edit_message_text("Failed to categorize transaction.")
        return

    # Extract merchant from original message for auto-rule
    # Message format: line 0 = header, line 1 = separator, line 2 = "🏪 MERCHANT"
    original_text = query.message.text or ""
    lines = original_text.split("\n")
    merchant = ""
    for line in lines:
        if line.startswith("🏪"):
            merchant = line.replace("🏪", "").strip()
            break

    if merchant:
        await create_auto_rule(merchant, category)

    await query.edit_message_text(f"{original_text}\n\n✅ Ok, tagged as {category}!")
