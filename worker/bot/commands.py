import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from worker.integrations import firefly_client, ibkr_flex
from worker.services.transaction_processor import process_new_emails

logger = logging.getLogger(__name__)


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Refreshing...")

    result = await process_new_emails()

    # Try API first, fall back to email-parsed data
    ibkr_data = await ibkr_flex.fetch_ibkr_data() or result.ibkr_data
    ibkr_msg = ""
    if ibkr_data:
        ibkr_msg = f"\nIBKR portfolio: ${ibkr_data['total_equity']:,.2f}"

    msg = (
        f"Found {result.new_count} new transaction(s). "
        f"{result.auto_categorized} categorized automatically, "
        f"{len(result.pending_review)} pending review."
    )
    if result.errors:
        msg += f"\n{result.errors} error(s) encountered."
    msg += ibkr_msg

    await update.message.reply_text(msg)


async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        accounts = await firefly_client.get_accounts()
    except Exception:
        await update.message.reply_text("Failed to fetch account balances.")
        return

    lines = ["Account Balances\n"]
    total = 0.0

    for acct in accounts:
        attrs = acct.get("attributes", {})
        name = attrs.get("name", "Unknown")
        acct_type = attrs.get("type", "")
        balance = float(attrs.get("current_balance", 0))

        if acct_type == "asset":
            icon = "Bank"
        elif acct_type == "liability":
            icon = "Card"
            balance = -abs(balance)
        else:
            continue

        lines.append(f"  {icon}: {name}: ${balance:,.2f}")
        total += balance

    lines.append(f"\nNet Worth: ${total:,.2f}")
    await update.message.reply_text("\n".join(lines))


def _parse_period(args: list[str]) -> tuple[date, date, str]:
    today = date.today()
    text = " ".join(args).lower().strip()

    if not text or text == "today":
        return today, today, "today"

    if text == "this week":
        start = today - timedelta(days=today.weekday())
        return start, today, "this week"

    if text == "this month":
        start = today.replace(day=1)
        return start, today, "this month"

    if text == "last month":
        first_this_month = today.replace(day=1)
        last_day_prev = first_this_month - timedelta(days=1)
        first_prev = last_day_prev.replace(day=1)
        return first_prev, last_day_prev, "last month"

    return today, today, text


async def handle_spent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []

    # Separate period args from category
    category_filter = None
    period_args = []
    known_periods = {"today", "this", "last", "week", "month"}

    for arg in args:
        if arg.lower() in known_periods:
            period_args.append(arg)
        else:
            category_filter = arg

    start, end, period_label = _parse_period(period_args)

    try:
        txns = await firefly_client.get_transactions(start_date=start, end_date=end)
    except Exception:
        await update.message.reply_text("Failed to fetch transactions.")
        return

    total = 0.0
    items = []

    for txn in txns:
        attrs = txn.get("attributes", {})
        for t in attrs.get("transactions", []):
            if t.get("type") != "withdrawal":
                continue

            cat = (t.get("category_name") or "").lower()
            if category_filter and category_filter.lower() not in cat:
                continue

            amount = float(t.get("amount", 0))
            desc = t.get("description", "Unknown")
            total += amount
            items.append(f"  ${amount:,.2f} — {desc}")

    header = f"Spending {period_label}"
    if category_filter:
        header += f" ({category_filter})"
    header += f": ${total:,.2f}\n"

    if items:
        msg = header + "\n".join(items[:20])
        if len(items) > 20:
            msg += f"\n... and {len(items) - 20} more"
    else:
        msg = header + "No transactions found."

    await update.message.reply_text(msg)


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    start_this = today.replace(day=1)
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    start_prev = last_prev.replace(day=1)

    try:
        this_month = await firefly_client.get_transactions(start_date=start_this, end_date=today)
        last_month = await firefly_client.get_transactions(
            start_date=start_prev, end_date=last_prev
        )
    except Exception:
        await update.message.reply_text("Failed to fetch summary data.")
        return

    def _summarize(txns):
        by_category = {}
        by_merchant = {}
        total_expense = 0.0
        total_income = 0.0

        for txn in txns:
            for t in txn.get("attributes", {}).get("transactions", []):
                amount = float(t.get("amount", 0))
                desc = t.get("description", "Unknown")
                cat = t.get("category_name") or "Uncategorized"
                txn_type = t.get("type", "")

                if txn_type == "withdrawal":
                    total_expense += amount
                    by_category[cat] = by_category.get(cat, 0) + amount
                    by_merchant[desc] = by_merchant.get(desc, 0) + amount
                elif txn_type == "deposit":
                    total_income += amount

        return total_income, total_expense, by_category, by_merchant

    income_this, expense_this, cats_this, merchants_this = _summarize(this_month)
    _, expense_last, _, _ = _summarize(last_month)

    lines = [f"Monthly Summary ({start_this.strftime('%B %Y')})\n"]
    lines.append(f"Income: ${income_this:,.2f}")
    lines.append(f"Expenses: ${expense_this:,.2f}")
    lines.append(f"Net: ${income_this - expense_this:,.2f}\n")

    if expense_last > 0:
        change = ((expense_this - expense_last) / expense_last) * 100
        direction = "up" if change > 0 else "down"
        lines.append(f"vs last month: {direction} {abs(change):.0f}%\n")

    sorted_cats = sorted(cats_this.items(), key=lambda x: x[1], reverse=True)
    lines.append("By category:")
    for cat, amount in sorted_cats[:10]:
        lines.append(f"  {cat}: ${amount:,.2f}")

    sorted_merchants = sorted(merchants_this.items(), key=lambda x: x[1], reverse=True)
    if sorted_merchants:
        lines.append("\nTop merchants:")
        for merchant, amount in sorted_merchants[:5]:
            lines.append(f"  {merchant}: ${amount:,.2f}")

    await update.message.reply_text("\n".join(lines))


async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /update <account> <balance>\n"
            "Examples:\n"
            "  /update syfe 8500\n"
            "  /update ibkr 45200\n"
            '  /update "Syfe Core" 8500.50'
        )
        return

    # Parse balance (last arg) and account name (everything before it)
    try:
        balance = float(args[-1])
    except ValueError:
        await update.message.reply_text("Invalid balance. Must be a number.")
        return

    account_name = " ".join(args[:-1]).strip('"').strip("'")

    # Find matching account in Firefly III
    try:
        accounts = await firefly_client.get_accounts()
    except Exception:
        await update.message.reply_text("Failed to fetch accounts.")
        return

    matched = None
    for acct in accounts:
        attrs = acct.get("attributes", {})
        name = attrs.get("name", "")
        if name.lower() == account_name.lower() or account_name.lower() in name.lower():
            matched = acct
            break

    if not matched:
        names = [a["attributes"]["name"] for a in accounts if "attributes" in a]
        await update.message.reply_text(
            f"Account '{account_name}' not found.\nAvailable accounts: {', '.join(names)}"
        )
        return

    acct_name = matched["attributes"]["name"]
    current = float(matched["attributes"].get("current_balance", 0))
    diff = balance - current

    if abs(diff) < 0.01:
        await update.message.reply_text(f"{acct_name} is already at ${balance:,.2f}")
        return

    # Create a correction transaction to adjust the balance
    if diff > 0:
        payload = {
            "transactions": [
                {
                    "type": "deposit",
                    "date": date.today().isoformat(),
                    "amount": str(abs(diff)),
                    "description": f"Balance adjustment for {acct_name}",
                    "source_name": "Balance Adjustment",
                    "destination_name": acct_name,
                }
            ]
        }
    else:
        payload = {
            "transactions": [
                {
                    "type": "withdrawal",
                    "date": date.today().isoformat(),
                    "amount": str(abs(diff)),
                    "description": f"Balance adjustment for {acct_name}",
                    "source_name": acct_name,
                    "destination_name": "Balance Adjustment",
                }
            ]
        }

    try:
        await firefly_client.create_transaction(payload)
    except Exception:
        await update.message.reply_text("Failed to update balance.")
        return

    await update.message.reply_text(f"Updated {acct_name}: ${current:,.2f} → ${balance:,.2f}")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available commands:\n\n"
        "/refresh — Fetch new transactions from email\n"
        "/balance — Show all account balances\n"
        "/spent [period] [category] — Show spending\n"
        "  Examples: /spent today, /spent this month food\n"
        "/summary — Monthly spending summary\n"
        "/update <account> <balance> — Manually set account balance\n"
        "  Examples: /update syfe 8500, /update ibkr 45200\n"
        "/help — Show this message\n\n"
        "Or just ask me anything about your finances!"
    )
