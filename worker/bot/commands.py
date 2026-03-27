import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from worker.integrations import firefly_client, ibkr_flex
from worker.services.transaction_processor import process_new_emails

logger = logging.getLogger(__name__)


async def _update_account_balance(account_name: str, new_balance: float) -> str | None:
    try:
        accounts = await firefly_client.get_accounts()
    except Exception:
        return None

    # Only match asset and liability accounts (skip revenue/expense/system accounts)
    candidates = [
        acct
        for acct in accounts
        if acct.get("attributes", {}).get("type") in ("asset", "liability")
    ]

    # Prefer exact match, then substring match
    matched = None
    for acct in candidates:
        name = acct.get("attributes", {}).get("name", "")
        if name.lower() == account_name.lower():
            matched = acct
            break
    if not matched:
        for acct in candidates:
            name = acct.get("attributes", {}).get("name", "")
            if account_name.lower() in name.lower():
                matched = acct
                break

    if not matched:
        return None

    acct_name = matched["attributes"]["name"]
    current = float(matched["attributes"].get("current_balance", 0))
    diff = new_balance - current

    if abs(diff) < 0.01:
        return None

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
        return f"{acct_name}: ${current:,.2f} → ${new_balance:,.2f}"
    except Exception:
        return None


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄  Checking...")

    result = await process_new_emails()

    ibkr_msg = ""
    try:
        ibkr_data = await ibkr_flex.fetch_ibkr_data()
        if ibkr_data and ibkr_data["total_equity"] > 0:
            updated = await _update_account_balance("IBKR", ibkr_data["total_equity"])
            if updated:
                ibkr_msg = f"\n📈  IBKR: {updated}"
            else:
                ibkr_msg = f"\n📈  IBKR: ${ibkr_data['total_equity']:,.2f} (no change)"
    except ibkr_flex.IBKRTokenError as e:
        ibkr_msg = f"\n⚠️  IBKR token expired: {e}"

    lines = ["<b>✅ Done!</b>", "──────────"]
    lines.append(f"📬 <b>{result.new_count}</b> new transaction(s)")
    lines.append(f"🏷️ <b>{result.auto_categorized}</b> auto-categorized")
    if result.pending_review:
        lines.append(f"👆 <b>{len(result.pending_review)}</b> need your input")
    if result.errors:
        lines.append(f"⚠️ {result.errors} error(s)")
    if ibkr_msg:
        lines.append(ibkr_msg)

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def _get_account_data() -> tuple[list[tuple], list[tuple], float]:
    accounts = await firefly_client.get_accounts()
    assets = []
    liabilities = []
    total = 0.0

    for acct in accounts:
        attrs = acct.get("attributes", {})
        name = attrs.get("name", "Unknown")
        acct_type = attrs.get("type", "")
        balance = float(attrs.get("current_balance", 0))
        last_activity = attrs.get("last_activity") or attrs.get("updated_at", "")

        date_str = ""
        if last_activity:
            try:
                dt = date.fromisoformat(last_activity[:10])
                date_str = dt.strftime("%d %b %Y")
            except ValueError:
                pass

        if acct_type == "asset":
            assets.append((name, balance, date_str))
            total += balance
        elif acct_type == "liability":
            balance = -abs(balance)
            liabilities.append((name, balance, date_str))
            total += balance

    return assets, liabilities, total


async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        assets, liabilities, total = await _get_account_data()
    except Exception:
        await update.message.reply_text("Failed to fetch account balances.")
        return

    lines = ["<b>💰 Balances</b>", "──────────"]

    for name, bal, _ in assets:
        lines.append(f"\n🏦 {name}\n<b>${bal:,.2f}</b>")

    for name, bal, _ in liabilities:
        lines.append(f"\n💳 {name}\n<b>${bal:,.2f}</b>")

    lines.append("\n──────────")
    lines.append(f"📊 Net Worth: <b>${total:,.2f}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def handle_lastupdate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        assets, liabilities, _ = await _get_account_data()
    except Exception:
        await update.message.reply_text("Failed to fetch accounts.")
        return

    lines = ["<b>📅 Last Updated</b>", "──────────"]

    for name, _, ds in assets + liabilities:
        lines.append(f"\n{name}\n<b>{ds or 'No activity yet'}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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
            items.append(f"  ${amount:,.2f} · {desc}")

    header = f"<b>🧾 Spending — {period_label}</b>"
    if category_filter:
        header += f" ({category_filter})"
    header += "\n──────────"

    if items:
        lines = [header, ""]
        lines.extend(items[:15])
        if len(items) > 15:
            lines.append(f"\n  ... and {len(items) - 15} more")
        lines.append("\n──────────")
        lines.append(f"💵 Total: <b>${total:,.2f}</b>")
        msg = "\n".join(lines)
    else:
        msg = f"{header}\n\nNo transactions found."

    await update.message.reply_text(msg, parse_mode="HTML")

    # Daily spending chart
    if items:
        from collections import defaultdict

        from worker.bot.charts import generate_daily_spending

        daily: dict[date, float] = defaultdict(float)
        for txn in txns:
            for t in txn.get("attributes", {}).get("transactions", []):
                if t.get("type") != "withdrawal":
                    continue
                cat = (t.get("category_name") or "").lower()
                if category_filter and category_filter.lower() not in cat:
                    continue
                txn_date_str = t.get("date", "")[:10]
                if txn_date_str:
                    txn_date = date.fromisoformat(txn_date_str)
                    daily[txn_date] += float(t.get("amount", 0))

        chart_buf = generate_daily_spending(dict(daily), period_label)
        if chart_buf:
            await update.message.reply_photo(photo=chart_buf)


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

    net = income_this - expense_this
    lines = [
        f"<b>📊 {start_this.strftime('%B %Y')}</b>",
        "──────────",
        "",
        f"📥 Income: <b>${income_this:,.2f}</b>",
        f"📤 Expenses: <b>${expense_this:,.2f}</b>",
        f"{'📈' if net >= 0 else '📉'} Net: <b>${net:,.2f}</b>",
    ]

    if expense_last > 0:
        change = ((expense_this - expense_last) / expense_last) * 100
        arrow = "⬆️" if change > 0 else "⬇️"
        lines.append(f"\n{arrow} vs last month: <b>{abs(change):.0f}%</b>")

    sorted_cats = sorted(cats_this.items(), key=lambda x: x[1], reverse=True)
    if sorted_cats:
        lines.append("\n<b>🏷️ By Category</b>")
        lines.append("──────────")
        for cat, amount in sorted_cats[:10]:
            lines.append(f"  {cat}: <b>${amount:,.2f}</b>")

    sorted_merchants = sorted(merchants_this.items(), key=lambda x: x[1], reverse=True)
    if sorted_merchants:
        lines.append("\n<b>🏪 Top Merchants</b>")
        lines.append("──────────")
        for merchant, amount in sorted_merchants[:5]:
            lines.append(f"  {merchant}: <b>${amount:,.2f}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    # Charts
    from worker.bot.charts import generate_category_pie, generate_monthly_trend

    pie_buf = generate_category_pie(cats_this)
    if pie_buf:
        await update.message.reply_photo(photo=pie_buf)

    monthly_data = await _get_monthly_expense_data(
        today, months=6, current_total=expense_this, last_total=expense_last
    )
    trend_buf = generate_monthly_trend(monthly_data)
    if trend_buf:
        await update.message.reply_photo(photo=trend_buf)


async def _get_monthly_expense_data(
    reference_date: date,
    months: int = 6,
    current_total: float = 0,
    last_total: float = 0,
) -> dict[str, float]:
    result = {}
    current_start = reference_date.replace(day=1)
    last_start = (current_start - timedelta(days=1)).replace(day=1)

    for i in range(months - 1, 1, -1):
        month_start = (current_start - timedelta(days=30 * i)).replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)

        try:
            txns = await firefly_client.get_transactions(start_date=month_start, end_date=month_end)
            total = sum(
                float(t.get("amount", 0))
                for txn in txns
                for t in txn.get("attributes", {}).get("transactions", [])
                if t.get("type") == "withdrawal"
            )
            result[month_start.strftime("%b %Y")] = total
        except Exception:
            result[month_start.strftime("%b %Y")] = 0

    result[last_start.strftime("%b %Y")] = last_total
    result[current_start.strftime("%b %Y")] = current_total
    return result


async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /update <account> <balance>\n"
            "Examples:\n"
            "  /update syfe 8500\n"
            "  /update ibkr 45200\n"
            '  /update "Syfe Cash" 8500.50'
        )
        return

    try:
        balance = float(args[-1])
    except ValueError:
        await update.message.reply_text("Invalid balance. Must be a number.")
        return

    account_name = " ".join(args[:-1]).strip('"').strip("'")
    result = await _update_account_balance(account_name, balance)

    if result:
        await update.message.reply_text(f"✅  Updated {result}")
    else:
        await update.message.reply_text(
            f"❌  Cannot update '{account_name}'\nAccount not found or balance unchanged."
        )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>👋 Hello! I'm Mdm Huat</b>\n"
        "──────────\n"
        "\n"
        "🔄 /refresh\n"
        "Fetch new transactions\n"
        "\n"
        "💰 /balance\n"
        "Account balances\n"
        "\n"
        "🧾 /spent [period] [category]\n"
        "Show spending\n"
        "<i>e.g. /spent this month food</i>\n"
        "\n"
        "📊 /summary\n"
        "Monthly spending summary\n"
        "\n"
        "✏️ /update [account] [amount]\n"
        "Manually set balance\n"
        "<i>e.g. /update syfe 8500</i>\n"
        "\n"
        "📅 /lastupdate\n"
        "Last activity dates\n"
        "\n"
        "❓ /help\n"
        "This message\n"
        "\n"
        "──────────\n"
        "Or just ask me anything!",
        parse_mode="HTML",
    )
