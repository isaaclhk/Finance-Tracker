import logging
from datetime import date, timedelta

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

    if data.startswith("date:"):
        await _handle_date_change(query, data)
        return

    if data.startswith("setdate:"):
        await _handle_set_date(query, data)
        return

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


async def _handle_date_change(query, data: str):
    # data format: "date:{txn_id}"
    txn_id = data.split(":", 1)[1]

    buttons = [
        [
            InlineKeyboardButton("Yesterday", callback_data=f"setdate:{txn_id}:1"),
            InlineKeyboardButton("2 days ago", callback_data=f"setdate:{txn_id}:2"),
        ],
        [
            InlineKeyboardButton("3 days ago", callback_data=f"setdate:{txn_id}:3"),
            InlineKeyboardButton("4 days ago", callback_data=f"setdate:{txn_id}:4"),
        ],
        [
            InlineKeyboardButton("5 days ago", callback_data=f"setdate:{txn_id}:5"),
            InlineKeyboardButton("6 days ago", callback_data=f"setdate:{txn_id}:6"),
        ],
        [
            InlineKeyboardButton("7 days ago", callback_data=f"setdate:{txn_id}:7"),
        ],
    ]

    original_text = query.message.text or ""
    await query.edit_message_text(
        f"{original_text}\n\n📅 Select date:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_set_date(query, data: str):
    # data format: "setdate:{txn_id}:{days_ago}"
    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    txn_id = parts[1]
    days_ago = int(parts[2])
    new_date = date.today() - timedelta(days=days_ago)

    try:
        await firefly_client.update_transaction(
            int(txn_id),
            {"transactions": [{"date": new_date.isoformat()}]},
        )
    except Exception:
        logger.exception("Failed to update transaction date %s", txn_id)
        await query.edit_message_text("❌ Failed to change date.")
        return

    # Update the message — replace "(today)" with the new date
    original_text = query.message.text or ""
    original_text = original_text.replace("(today)", f"({new_date.strftime('%d %b %Y')})")
    # Remove the "Select date:" line if present
    original_text = original_text.split("\n📅 Select date:")[0].strip()
    date_str = new_date.strftime("%d %b %Y")
    await query.edit_message_text(f"{original_text}\n\n📅 Date changed to {date_str}")
