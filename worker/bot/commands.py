import calendar
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from worker.integrations import firefly_client, ibkr_flex
from worker.services import salary
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
    current = Decimal(str(matched["attributes"].get("current_balance", 0)))
    target = Decimal(str(new_balance))
    diff = target - current

    if abs(diff) < Decimal("0.01"):
        return None

    # Use transfer so it doesn't count as income/expense
    adjustment_account = "Market Value Adjustment"
    if diff > 0:
        source = adjustment_account
        destination = acct_name
    else:
        source = acct_name
        destination = adjustment_account

    payload = {
        "transactions": [
            {
                "type": "transfer",
                "date": date.today().isoformat(),
                "amount": str(abs(diff)),
                "description": f"Balance adjustment for {acct_name}",
                "source_name": source,
                "destination_name": destination,
            }
        ]
    }

    try:
        await firefly_client.create_transaction(payload)
        return f"{acct_name}: ${current:,.2f} → ${target:,.2f}"
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


async def _get_account_data() -> tuple[list[tuple], list[tuple], Decimal]:
    accounts = await firefly_client.get_accounts()
    assets = []
    liabilities = []
    total = Decimal("0")

    for acct in accounts:
        attrs = acct.get("attributes", {})
        name = attrs.get("name", "Unknown")
        acct_type = attrs.get("type", "")
        balance = Decimal(str(attrs.get("current_balance", 0)))
        last_activity = attrs.get("last_activity") or attrs.get("updated_at", "")

        date_str = ""
        if last_activity:
            try:
                dt = datetime.fromisoformat(last_activity)
                date_str = dt.strftime("%d %b %Y %H:%M")
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


MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTH_ABBR = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def _parse_period(text: str) -> tuple[date, date, str] | None:
    today = date.today()
    text = text.lower().strip()

    if not text or text == "today":
        return today, today, "today"

    if text == "yesterday":
        d = today - timedelta(days=1)
        return d, d, "yesterday"

    if text == "this week":
        start = today - timedelta(days=today.weekday())
        return start, today, "this week"

    if text == "last week":
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return start, end, "last week"

    if text == "this month":
        return today.replace(day=1), today, "this month"

    if text == "last month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev, "last month"

    if text == "this year":
        return today.replace(month=1, day=1), today, "this year"

    if text == "last year":
        start = today.replace(year=today.year - 1, month=1, day=1)
        end = today.replace(year=today.year - 1, month=12, day=31)
        return start, end, "last year"

    # "last N days/weeks/months"
    m = re.match(r"(?:last|past)\s+(\d+)\s+(day|week|month)s?", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == "day":
            start = today - timedelta(days=n)
        elif unit == "week":
            start = today - timedelta(weeks=n)
        elif unit == "month":
            start = (today.replace(day=1) - timedelta(days=30 * (n - 1))).replace(day=1)
        return start, today, f"last {n} {unit}s"

    # Month-to-month range: "jan to mar", "january to march 2025", "feb - apr"
    range_match = re.match(r"([a-z]+)\s*(?:to|-)\s*([a-z]+)\s*(\d{4})?", text)
    if range_match:
        start_month = _resolve_month(range_match.group(1))
        end_month = _resolve_month(range_match.group(2))
        year = int(range_match.group(3)) if range_match.group(3) else today.year
        if start_month and end_month:
            start = date(year, start_month, 1)
            last_day = calendar.monthrange(year, end_month)[1]
            end = min(date(year, end_month, last_day), today)
            start_name = calendar.month_abbr[start_month]
            end_name = calendar.month_abbr[end_month]
            return start, end, f"{start_name}–{end_name} {year}"

    # Single month: "january", "feb", "march 2025"
    single_match = re.match(r"([a-z]+)\s*(\d{4})?$", text)
    if single_match:
        month_num = _resolve_month(single_match.group(1))
        if month_num:
            year = int(single_match.group(2)) if single_match.group(2) else today.year
            start = date(year, month_num, 1)
            last_day = calendar.monthrange(year, month_num)[1]
            end = min(date(year, month_num, last_day), today)
            return start, end, f"{calendar.month_name[month_num]} {year}"

    return None


def _resolve_month(text: str) -> int | None:
    text = text.lower().strip()
    if text in MONTH_NAMES:
        return MONTH_NAMES[text]
    if text in MONTH_ABBR:
        return MONTH_ABBR[text]
    return None


async def _llm_parse_period(text: str) -> tuple[date, date, str] | None:
    today = date.today()
    prompt = (
        f"Today is {today.isoformat()}. "
        f'The user wants to see spending for: "{text}". '
        f"Return JSON with exactly: "
        f'{{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": "short description"}}. '
        f"Only return JSON, nothing else."
    )
    try:
        from worker.integrations import openai_client

        result = await openai_client.parse_and_categorize(prompt, "system")
        if result and "start" in result and "end" in result:
            start = date.fromisoformat(result["start"])
            end = date.fromisoformat(result["end"])
            label = result.get("label", text)
            return start, min(end, today), label
    except Exception:
        pass
    return None


async def handle_spent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    raw_text = " ".join(args).strip()

    # Split category filter from period text
    # Try the full text as a period first, then try without the last word as category
    category_filter = None
    result = _parse_period(raw_text)

    if result is None and len(args) > 1:
        # Last word might be a category filter
        category_filter = args[-1]
        result = _parse_period(" ".join(args[:-1]))

    if result is None:
        # LLM fallback
        result = await _llm_parse_period(raw_text)

    if result is None:
        result = (date.today(), date.today(), raw_text or "today")

    start, end, period_label = result

    try:
        txns = await firefly_client.get_transactions(start_date=start, end_date=end)
    except Exception:
        await update.message.reply_text("Failed to fetch transactions.")
        return

    total = Decimal("0")
    items = []

    for txn in txns:
        attrs = txn.get("attributes", {})
        for t in attrs.get("transactions", []):
            if t.get("type") != "withdrawal":
                continue

            cat = (t.get("category_name") or "").lower()
            if category_filter and category_filter.lower() not in cat:
                continue

            amount = Decimal(str(t.get("amount", 0)))
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


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    args = context.args or []
    raw_text = " ".join(args).strip()

    # Parse period or default to this month
    result = _parse_period(raw_text) if raw_text else None
    if result is None and raw_text:
        result = await _llm_parse_period(raw_text)
    if result is None:
        result = (today.replace(day=1), today, "this month")

    start, end, period_label = result

    # Compute a comparison period of the same length, ending just before start
    period_days = (end - start).days
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days)

    try:
        txns = await firefly_client.get_transactions(start_date=start, end_date=end)
        prev_txns = await firefly_client.get_transactions(start_date=prev_start, end_date=prev_end)
    except Exception:
        await update.message.reply_text("Failed to fetch summary data.")
        return

    def _summarize(txn_list):
        by_category: dict[str, Decimal] = {}
        by_merchant: dict[str, Decimal] = {}
        total_expense = Decimal("0")
        total_income = Decimal("0")

        for txn in txn_list:
            for t in txn.get("attributes", {}).get("transactions", []):
                amount = Decimal(str(t.get("amount", 0)))
                desc = t.get("description", "Unknown")
                cat = t.get("category_name") or "Uncategorized"
                txn_type = t.get("type", "")

                if txn_type == "withdrawal":
                    total_expense += amount
                    by_category[cat] = by_category.get(cat, Decimal("0")) + amount
                    by_merchant[desc] = by_merchant.get(desc, Decimal("0")) + amount
                elif txn_type == "deposit":
                    total_income += amount

        return total_income, total_expense, by_category, by_merchant

    income, expense, cats, merchants = _summarize(txns)
    _, expense_prev, _, _ = _summarize(prev_txns)

    net = income - expense
    lines = [
        f"<b>📊 {period_label}</b>",
        "──────────",
        "",
        f"📥 Income: <b>${income:,.2f}</b>",
        f"📤 Expenses: <b>${expense:,.2f}</b>",
        f"{'📈' if net >= 0 else '📉'} Net: <b>${net:,.2f}</b>",
    ]

    if expense_prev > 0:
        change = float((expense - expense_prev) / expense_prev * 100)
        arrow = "⬆️" if change > 0 else "⬇️"
        lines.append(f"\n{arrow} vs previous period: <b>{abs(change):.0f}%</b>")

    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)
    if sorted_cats:
        lines.append("\n<b>🏷️ By Category</b>")
        lines.append("──────────")
        for cat, amount in sorted_cats[:10]:
            lines.append(f"  {cat}: <b>${amount:,.2f}</b>")

    sorted_merchants = sorted(merchants.items(), key=lambda x: x[1], reverse=True)
    if sorted_merchants:
        lines.append("\n<b>🏪 Top Merchants</b>")
        lines.append("──────────")
        for merchant, amount in sorted_merchants[:5]:
            lines.append(f"  {merchant}: <b>${amount:,.2f}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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


async def handle_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /income <amount> <source> [account]\n"
            "Examples:\n"
            "  /income 5000 Salary\n"
            "  /income 2000 Bonus\n"
            "  /income 200 Interest ocbc"
        )
        return

    try:
        amount = Decimal(args[0])
    except Exception:
        await update.message.reply_text("Invalid amount. Must be a number.")
        return

    # If last arg looks like an account name (>2 args), use it
    if len(args) > 2:
        source = " ".join(args[1:-1])
        account_name = args[-1]
        # Check if last arg is actually an account
        try:
            accounts = await firefly_client.get_accounts()
            matched = None
            for acct in accounts:
                attrs = acct.get("attributes", {})
                if attrs.get("type") not in ("asset", "liability"):
                    continue
                name = attrs.get("name", "")
                if account_name.lower() in name.lower():
                    matched = name
                    break
            if not matched:
                # Last arg is part of source name, not an account
                source = " ".join(args[1:])
                matched = salary.DEFAULT_ACCOUNT
        except Exception:
            source = " ".join(args[1:])
            matched = salary.DEFAULT_ACCOUNT
    else:
        source = " ".join(args[1:])
        matched = salary.DEFAULT_ACCOUNT

    payload = {
        "transactions": [
            {
                "type": "deposit",
                "date": date.today().isoformat(),
                "amount": str(amount),
                "description": source,
                "source_name": source,
                "destination_name": matched,
            }
        ]
    }

    try:
        await firefly_client.create_transaction(payload)
        await update.message.reply_text(
            f"✅ <b>${amount:,.2f}</b> from {source}\n→ {matched}",
            parse_mode="HTML",
        )
    except Exception:
        await update.message.reply_text("❌ Failed to record income.")


async def handle_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []

    if not args:
        # Show current config
        salaries = salary.get_salaries()
        if not salaries:
            await update.message.reply_text(
                "<b>💼 Salary Config</b>\n──────────\n\nNo salaries configured.\n"
                "Use /salary add <name> <amount> <day>",
                parse_mode="HTML",
            )
            return

        lines = ["<b>💼 Salary Config</b>", "──────────"]
        for s in salaries:
            lines.append(
                f"\n{s['name']}\n"
                f"<b>${s['amount']:,.2f}</b> on day {s['day']}\n"
                f"→ {s.get('account', salary.DEFAULT_ACCOUNT)}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    action = args[0].lower()

    if action == "add":
        if len(args) < 4:
            await update.message.reply_text(
                "Usage: /salary add <name> <amount> <day>\ne.g. /salary add Isaac 5000 25"
            )
            return
        name = args[1]
        try:
            amount = float(args[2])
            day = int(args[3])
        except ValueError:
            await update.message.reply_text("Invalid amount or day.")
            return
        if not 1 <= day <= 28:
            await update.message.reply_text("Day must be between 1 and 28.")
            return
        result = salary.add_salary(name, amount, day)
        await update.message.reply_text(f"✅ {result}")

    elif action == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: /salary remove <name>")
            return
        name = args[1]
        result = salary.remove_salary(name)
        await update.message.reply_text(f"✅ {result}")

    elif action == "set":
        if len(args) < 3:
            await update.message.reply_text("Usage: /salary set <name> <amount>")
            return
        name = args[1]
        try:
            amount = float(args[2])
        except ValueError:
            await update.message.reply_text("Invalid amount.")
            return
        result = salary.set_salary_amount(name, amount)
        await update.message.reply_text(f"✅ {result}")

    else:
        await update.message.reply_text(
            "Usage:\n"
            "  /salary — view config\n"
            "  /salary add <name> <amount> <day>\n"
            "  /salary remove <name>\n"
            "  /salary set <name> <amount>"
        )


HELP_DETAILS = {
    "spent": (
        "<b>🧾 /spent [period] [category]</b>\n"
        "──────────\n"
        "List transactions for a period.\n"
        "\n"
        "<b>Periods (instant):</b>\n"
        "  today, yesterday\n"
        "  this week, last week\n"
        "  this month, last month\n"
        "  this year, last year\n"
        "  last N days/weeks/months\n"
        "  jan, february, mar 2025\n"
        "  jan to mar, feb - jun 2025\n"
        "\n"
        "<b>Anything else</b> → AI interprets it\n"
        '<i>e.g. "since christmas", "Q1 2026"</i>\n'
        "\n"
        "<b>Category filter</b> (optional, last word):\n"
        "  /spent this month food\n"
        "  /spent last week transport"
    ),
    "summary": (
        "<b>📊 /summary [period]</b>\n"
        "──────────\n"
        "Income vs expenses, category breakdown,\n"
        "top merchants.\n"
        "\n"
        "Accepts the same periods as /spent.\n"
        "Defaults to this month.\n"
        "\n"
        "Includes comparison vs the previous\n"
        "period of the same length.\n"
        "\n"
        "<b>Examples:</b>\n"
        "  /summary\n"
        "  /summary last month\n"
        "  /summary jan to mar"
    ),
    "update": (
        "<b>✏️ /update [account] [amount]</b>\n"
        "──────────\n"
        "Manually set an account balance.\n"
        "Fuzzy-matches the account name.\n"
        "\n"
        "<b>Examples:</b>\n"
        "  /update syfe 8500\n"
        "  /update ibkr 45200\n"
        '  /update "Syfe Cash" 8500.50'
    ),
    "refresh": (
        "<b>🔄 /refresh</b>\n"
        "──────────\n"
        "Fetches new bank alert emails,\n"
        "parses transactions, and updates\n"
        "IBKR portfolio via Flex Query API.\n"
        "\n"
        "<b>Automatic:</b>\n"
        "  Emails: every 5 min\n"
        "  IBKR: once a day"
    ),
    "balance": (
        "<b>💰 /balance</b>\n"
        "──────────\n"
        "Shows all account balances\n"
        "(savings, investments, cards)\n"
        "and net worth."
    ),
    "lastupdate": (
        "<b>📅 /lastupdate</b>\n"
        "──────────\n"
        "Shows when each account was\n"
        "last updated (last transaction date)."
    ),
    "income": (
        "<b>📥 /income [amount] [source] [account]</b>\n"
        "──────────\n"
        "Record one-off incoming money.\n"
        "Default account: UOB One Account.\n"
        "\n"
        "<b>Examples:</b>\n"
        "  /income 5000 Salary\n"
        "  /income 2000 Bonus\n"
        "  /income 200 Interest ocbc"
    ),
    "salary": (
        "<b>💼 /salary</b>\n"
        "──────────\n"
        "View and manage recurring salaries.\n"
        "Auto-deposits on the configured day\n"
        "each month to UOB One Account.\n"
        "\n"
        "<b>Commands:</b>\n"
        "  /salary — view config\n"
        "  /salary add [name] [amount] [day]\n"
        "  /salary remove [name]\n"
        "  /salary set [name] [amount]\n"
        "\n"
        "<b>Examples:</b>\n"
        "  /salary add Isaac 5000 25\n"
        "  /salary add Wife 4000 28\n"
        "  /salary set Isaac 5500"
    ),
}


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    cmd = args[0].lstrip("/") if args else ""

    if cmd in HELP_DETAILS:
        await update.message.reply_text(HELP_DETAILS[cmd], parse_mode="HTML")
        return

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
        "\n"
        "📊 /summary [period]\n"
        "Spending summary\n"
        "\n"
        "📥 /income [amount] [source]\n"
        "Record incoming money\n"
        "\n"
        "💼 /salary\n"
        "Manage recurring salaries\n"
        "\n"
        "✏️ /update [account] [amount]\n"
        "Set balance manually\n"
        "\n"
        "📅 /lastupdate\n"
        "Last activity dates\n"
        "\n"
        "──────────\n"
        "Type <b>/help [command]</b> for details\n"
        "<i>e.g. /help spent</i>\n"
        "\n"
        "Or just ask me anything!",
        parse_mode="HTML",
    )
