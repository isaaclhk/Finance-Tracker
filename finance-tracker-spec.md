# Singapore Personal Finance Tracker — Project Specification

## Overview

Build a self-hosted personal finance tracking system for a Singapore-based couple with shared finances. The system automatically ingests bank transaction data from email alerts (OCBC, UOB, Trust Bank), investment data from IBKR (via Flex Query API), categorizes transactions using a hybrid Firefly III rules + LLM approach with user confirmation via Telegram, and provides a shared Telegram group bot for interaction and natural language queries. Firefly III serves as the financial data backend and dashboard. Syfe Cash is tracked via manual balance updates (`/update` command). Everything runs on a local homelab server via Docker Compose, with Cloudflare Tunnel for HTTPS access. Personal/private accounts (DBS) are excluded.

## Architecture

```
Bank transaction emails ──→ Gmail ──→ Python Worker (Homelab)
IBKR Flex Queries ─────────────────→       │
Syfe / manual updates ────────────→       │ (via /update command)
                                            │
                                  ┌─────────┴──────────┐
                                  │                    │
                            Known merchant?      Unknown merchant?
                                  │                    │
                            Auto-categorize      GPT-4.1 nano suggests
                            Push to Firefly      Ask user via Telegram
                                  │                    │
                                  │              User taps button
                                  │                    │
                                  └─────────┬──────────┘
                                            │
                                  Firefly III + SQLite (Homelab)
                                            │
                                  ┌─────────┴──────────┐
                                  │                    │
                          Firefly III Web UI     Telegram bot
                          (reports + admin)      (commands + LLM queries)
                                                       │
                                                GPT-4.1 mini
                                                (natural language answers)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Financial backend + dashboard | Firefly III (Docker image `fireflyiii/core:latest`) |
| Database | SQLite (embedded in Firefly III container) |
| Worker service | Python 3.11+ with FastAPI |
| Email integration | Gmail API (OAuth2) |
| Telegram bot | `python-telegram-bot` library |
| LLM categorization | OpenAI API — GPT-4.1 nano for categorization |
| LLM queries | OpenAI API — GPT-4.1 mini for natural language finance queries |
| IBKR data | IBKR Flex Web Service (XML reports via API) |
| Deployment | Local homelab server + Docker Compose |
| HTTPS | Cloudflare Tunnel (no port forwarding needed) |
| Mobile app | Firefly III web UI (bookmark on phone home screen) |

## Hosting — Local Homelab + Docker Compose

Two services run on a local homelab server using Docker Compose. Cloudflare Tunnel provides HTTPS access without port forwarding.

### Server

- Local homelab machine (Ubuntu 24.04 LTS)
- Docker + Docker Compose installed
- Cloudflare Tunnel (`cloudflared`) installed as a systemd service
- Domain: `finance.lam-lab.cc` (Cloudflare DNS with CNAME to tunnel)

### docker-compose.yml

```yaml
services:
  firefly:
    image: fireflyiii/core:latest
    restart: unless-stopped
    volumes:
      - firefly_upload:/var/www/html/storage/upload
      - firefly_db:/var/www/html/storage/database
    ports:
      - "127.0.0.1:8080:8080"  # Only accessible on localhost (via Cloudflare Tunnel)
    env_file:
      - .env
    environment:
      APP_KEY: ${APP_KEY}
      DB_CONNECTION: sqlite
      APP_URL: https://${DOMAIN}
      TRUSTED_PROXIES: "*"
      TZ: Asia/Singapore

  worker:
    build: ./worker
    restart: unless-stopped
    depends_on:
      - firefly
    volumes:
      - ./soul.md:/app/soul.md:ro
    env_file:
      - .env
    environment:
      FIREFLY_URL: http://firefly:8080
      FIREFLY_TOKEN: ${FIREFLY_TOKEN}
      GMAIL_CREDENTIALS: ${GMAIL_CREDENTIALS}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      IBKR_FLEX_TOKEN: ${IBKR_FLEX_TOKEN}
      IBKR_FLEX_QUERY_ID: ${IBKR_FLEX_QUERY_ID}
      VALIDATION_LARGE_AMOUNT_THRESHOLD: ${VALIDATION_LARGE_AMOUNT_THRESHOLD:-5000}
      VALIDATION_SMALL_AMOUNT_MIN: ${VALIDATION_SMALL_AMOUNT_MIN:-0.01}
      VALIDATION_MAX_AMOUNT: ${VALIDATION_MAX_AMOUNT:-50000}
      CONVERSATION_HISTORY_LENGTH: ${CONVERSATION_HISTORY_LENGTH:-5}
      CONVERSATION_TIMEOUT_MINUTES: ${CONVERSATION_TIMEOUT_MINUTES:-30}

volumes:
  firefly_upload:
  firefly_db:
```

### Cloudflare Tunnel (replaces Caddy)

HTTPS is handled by Cloudflare Tunnel instead of Caddy. The tunnel runs as a systemd service (`cloudflared`) and routes `finance.lam-lab.cc` to `http://localhost:8080`. No port forwarding or SSL certificates needed.

Config at `/etc/cloudflared/config.yml`:
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: finance.lam-lab.cc
    service: http://localhost:8080
  - service: http_status:404
```

### .env file (all secrets in one place, never committed to git)

```bash
# Domain
DOMAIN=finance.lam-lab.cc

# Firefly III
APP_KEY=<generated via: head -c 32 /dev/urandom | base64 | head -c 32>
FIREFLY_TOKEN=<Firefly III Personal Access Token>

# Gmail (label-based filtering — only reads emails with "Bank Alerts" label)
GMAIL_CREDENTIALS={"client_id":"...","client_secret":"...","refresh_token":"...","token":"...","token_uri":"..."}

# Telegram
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_CHAT_ID=<group chat ID, negative number>

# OpenAI
OPENAI_API_KEY=<OpenAI API key>

# IBKR
IBKR_FLEX_TOKEN=<IBKR Flex Web Service token, expires ~1 year>
IBKR_FLEX_QUERY_ID=<Flex Query ID>

# Account mapping (JSON: card last 4 digits → Firefly III account name)
# Bank name fallbacks (OCBC, UOB, Trust, Syfe) are built in
ACCOUNT_MAP={"1234": "UOB Credit Card", "5678": "Trust Card", "9012": "OCBC Savings", "0001": "UOB Savings"}

# Validation thresholds (optional, defaults shown)
VALIDATION_LARGE_AMOUNT_THRESHOLD=5000
VALIDATION_SMALL_AMOUNT_MIN=0.01
VALIDATION_MAX_AMOUNT=50000

# Conversation memory (optional, defaults shown)
CONVERSATION_HISTORY_LENGTH=5
CONVERSATION_TIMEOUT_MINUTES=30
```

## Python Worker Service — Detailed Specification

### Project Structure

```
finance-tracker/
├── docker-compose.yml
├── .env                       # Secrets and config (never commit)
├── .env.example               # Template with all env vars
├── soul.md                    # Bot personality definition (editable anytime)
├── pyproject.toml             # Project metadata, ruff config, uv settings
├── worker/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                    # FastAPI app + startup
│   ├── config.py                  # Environment variable loading + configurable thresholds
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── telegram_bot.py        # Telegram bot setup and handlers
│   │   ├── commands.py            # /refresh, /balance, /spent, /summary, /update, /lastupdate, /help
│   │   ├── callbacks.py           # Inline keyboard callback handlers (category confirmation)
│   │   └── llm_query.py           # Natural language query handler
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── llm_email_parser.py    # Universal LLM-based email parser (all banks + Syfe)
│   │   ├── validator.py           # Validation layer with configurable thresholds
│   │   └── statement_parser.py    # Monthly eStatement PDF parser (reconciliation)
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── gmail_client.py        # Gmail API connection and email fetching
│   │   ├── firefly_client.py      # Firefly III API wrapper
│   │   ├── ibkr_flex.py           # IBKR Flex Web Service client
│   │   └── openai_client.py       # OpenAI API wrapper for parsing, categorization + queries
│   ├── services/
│   │   ├── __init__.py
│   │   ├── transaction_processor.py  # Core logic: parse → validate → categorize → store
│   │   ├── categorizer.py            # Hybrid rule check + LLM categorization
│   │   ├── account_mapper.py         # Maps card/account hints to Firefly III accounts
│   │   └── reconciler.py             # Monthly eStatement reconciliation logic
│   └── utils/
│       ├── __init__.py
│       └── dedup.py               # Transaction deduplication logic
```

### requirements.txt

```
fastapi>=0.100.0
uvicorn>=0.23.0
python-telegram-bot>=20.0
google-api-python-client>=2.0.0
google-auth-oauthlib>=1.0.0
openai>=1.30.0
httpx>=0.24.0
pdfplumber>=0.9.0
python-dateutil>=2.8.0
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./worker/
CMD ["uvicorn", "worker.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## Email Parsing — LLM-Based Universal Parser

### Gmail API Integration (`gmail_client.py`)

- Connect to the user's Gmail account using OAuth2
- Filter by Gmail label instead of sender addresses — only reads emails with the **"Bank Alerts"** label (configurable via `GMAIL_LABEL` env var)
- Gmail filters auto-label incoming bank emails:
  - OCBC: `documents@ocbc.com`, `Notifications@ocbc.com`
  - UOB: `unialerts@uobgroup.com`
  - Trust Bank: TBD — verify actual sender address
- Multiple Gmail accounts forward alerts to one primary account; Gmail filters label them all as "Bank Alerts"
- Track the last processed email timestamp to avoid reprocessing (stored in a JSON cursor file)
- Supports email attachments extraction (for potential future use)

### Universal LLM Email Parser (`llm_email_parser.py`)

Instead of writing separate regex parsers for each bank, use a single GPT-4.1 nano call to parse ALL bank emails. This is resilient to email format changes and works for any bank without code modifications.

**Combined parsing + categorization in one call:**

```python
async def parse_and_categorize(email_body: str, sender: str) -> dict:
    response = await openai_client.chat.completions.create(
        model="gpt-4.1-nano",
        max_tokens=200,
        response_format={"type": "json_object"},
        messages=[{
            "role": "system",
            "content": """Extract transaction details from this bank email alert.
Return JSON with exactly these fields:
{
  "amount": number (SGD value, no currency symbol),
  "merchant": string (merchant or payee name, cleaned up),
  "date": string (ISO format YYYY-MM-DD),
  "time": string (HH:MM or null),
  "card_or_account": string (last 4 digits of card or account identifier),
  "transaction_type": "card_spending" | "fund_transfer" | "atm_withdrawal" | "giro" | "paynow" | "incoming" | "refund" | "bill_payment" | "unknown",
  "bank": "DBS" | "OCBC" | "UOB" | "Syfe" | "unknown",
  "suggested_category": one of: "Food & Drink" | "Groceries" | "Transport" | "Shopping" | "Health" | "Entertainment" | "Subscriptions" | "Utilities" | "Education" | "Housing" | "Insurance" | "Investments" | "Gifts" | "Travel" | "Misc" | null
}
If any field cannot be determined, use null."""
        }, {
            "role": "user",
            "content": f"Sender: {sender}\n\nEmail body:\n{email_body}"
        }]
    )
    return json.loads(response.choices[0].message.content)
```

**Why this is better than regex:**
- One parser handles all banks — no bank-specific code to maintain
- If a bank changes their email format, the LLM adapts without code changes
- Naturally handles edge cases (refunds, PayNow, GIRO, bill payments)
- Combined parsing + categorization in one call saves a second API request
- Cost: ~$0.0001 per email (~$0.05/month for 500 transactions)

### Validation Layer (`validator.py`)

LLMs can occasionally misparse amounts. A validation layer catches errors before they reach Firefly III. **All thresholds are configurable via environment variables.**

```python
# config.py — Configurable validation thresholds
VALIDATION_LARGE_AMOUNT_THRESHOLD = float(os.getenv("VALIDATION_LARGE_AMOUNT_THRESHOLD", "5000"))
VALIDATION_SMALL_AMOUNT_MIN = float(os.getenv("VALIDATION_SMALL_AMOUNT_MIN", "0.01"))
VALIDATION_MAX_AMOUNT = float(os.getenv("VALIDATION_MAX_AMOUNT", "50000"))
```

```python
# validator.py
async def validate_parsed_transaction(parsed: dict, telegram_bot) -> dict | None:
    # Reject if critical fields are missing
    if parsed.get("amount") is None or parsed.get("card_or_account") is None:
        await telegram_bot.notify_parse_failure(parsed)
        return None
    
    # Reject nonsensical amounts
    if parsed["amount"] <= VALIDATION_SMALL_AMOUNT_MIN:
        await telegram_bot.notify_parse_failure(parsed)
        return None
    
    if parsed["amount"] > VALIDATION_MAX_AMOUNT:
        await telegram_bot.notify_parse_failure(parsed)
        return None
    
    # Flag large amounts for confirmation (configurable threshold)
    if parsed["amount"] > VALIDATION_LARGE_AMOUNT_THRESHOLD:
        await telegram_bot.send_large_amount_confirmation(parsed)
    
    # Default date to today if missing
    if parsed.get("date") is None:
        parsed["date"] = date.today().isoformat()
    
    return parsed
```

### Account Mapping (`account_mapper.py`)

Maps the `card_or_account` field from the LLM to the correct Firefly III account. Configured via the `ACCOUNT_MAP` environment variable (JSON string).

Built-in bank name fallbacks are always available:
- `"OCBC"` → `"OCBC Savings"`
- `"UOB"` → `"UOB Savings"`
- `"Trust"` → `"Trust Card"`
- `"Syfe"` → `"Syfe Cash"`

Card-specific mappings are set via env var:
```bash
ACCOUNT_MAP={"8106": "UOB Credit Card", "5678": "Trust Card", "9012": "OCBC Savings", "0001": "UOB Savings"}
```

### Transaction Type Routing

The `transaction_type` from the LLM determines how the transaction is recorded in Firefly III:

| transaction_type | Firefly III type | Source → Destination |
|-----------------|------------------|---------------------|
| `card_spending` | Withdrawal | Credit Card (liability) → Merchant (expense) |
| `fund_transfer` | Transfer | Bank Account (asset) → Another account |
| `atm_withdrawal` | Withdrawal | Bank Account (asset) → "Cash" (expense) |
| `paynow` | Withdrawal | Bank Account (asset) → Recipient (expense) |
| `incoming` | Deposit | Payer (revenue) → Bank Account (asset) |
| `refund` | Deposit | Merchant (revenue) → Credit Card (liability) |
| `bill_payment` | Transfer | Bank Account (asset) → Credit Card (liability) |
| `giro` | Withdrawal | Bank Account (asset) → Payee (expense) |

### Monthly eStatement Reconciliation (`statement_parser.py` + `reconciler.py`)

- Detect when a monthly eStatement PDF arrives via email
- Use `pdfplumber` to extract transaction tables from the PDF
- Pass extracted text through the same LLM parser for consistent parsing
- For each transaction in the statement:
  - Check if it already exists in Firefly III (match on date + approximate amount + merchant)
  - If not found, it's likely a recurring/GIRO payment — add it
- This catches: subscriptions, insurance payments, loan repayments, GIRO deductions, credit card bill payments, and any transactions that didn't trigger email alerts

---

## Transaction Processing Pipeline (`transaction_processor.py`)

### Flow

```python
async def process_new_emails():
    # 1. Fetch new bank alert emails from Gmail
    emails = await gmail_client.fetch_new_alerts()
    
    new_count = 0
    for email in emails:
        # 2. Parse email using universal LLM parser (includes categorization)
        parsed = await llm_email_parser.parse_and_categorize(
            email.body, email.sender
        )
        if parsed is None:
            continue
        
        # 3. Validate parsed data (configurable thresholds)
        validated = await validator.validate_parsed_transaction(parsed, telegram_bot)
        if validated is None:
            continue
        
        # 4. Map to Firefly III account
        source_account = account_mapper.map_to_firefly_account(validated)
        if source_account is None:
            await telegram_bot.notify_unknown_account(validated)
            continue
        
        # 5. Check for duplicates
        if await dedup.is_duplicate(validated, firefly_client):
            continue
        
        # 6. Create transaction in Firefly III
        firefly_txn = await firefly_client.create_transaction(
            validated, source_account
        )
        
        # 7. Check if Firefly III auto-categorized via rules
        if firefly_txn.category is not None:
            # Known merchant — rule matched. Done silently.
            new_count += 1
            continue
        
        # 8. Use LLM's suggested category from Step 2
        suggested_category = validated.get("suggested_category")
        
        # 9. Ask user to confirm category via Telegram
        await telegram_bot.ask_category_confirmation(
            transaction=firefly_txn,
            suggested_category=suggested_category
        )
        
        new_count += 1
    
    return new_count
```

### Deduplication Logic (`dedup.py`)

Before inserting any transaction, check Firefly III for existing transactions matching:
- Same date (±1 day to handle timezone issues)
- Same amount (exact match)
- Similar description (fuzzy match on merchant name)

If all three match, skip the transaction. This prevents duplicates from:
- Email alerts being processed twice
- Monthly reconciliation re-adding transactions already captured via email alerts

---

## Categorization System (`categorizer.py`)

### Tier 1: Firefly III Rules (free, instant, no LLM needed)

Firefly III has a built-in rule engine. When a transaction is created via the API, rules execute automatically. The user sets up rules in Firefly III's web UI or they are auto-created by the system.

Example rules:
- Description contains "GRAB" → Category: Transport
- Description contains "NTUC" OR "FAIRPRICE" → Category: Groceries
- Description contains "NETFLIX" → Category: Subscriptions

Over time, auto-created rules handle most merchants — reducing LLM usage to near zero.

### Tier 2: LLM Suggestion (from the parsing step)

When Firefly III rules don't match (category remains null after creation), the system uses the `suggested_category` field that was already returned by the LLM during the parsing step. **No separate LLM call is needed** — categorization is combined with parsing in a single API request.

### Tier 3: User Confirmation via Telegram

After the LLM suggests a category, the bot sends an inline keyboard to the user:

```
🆕 New merchant detected

BOBER TEA ION ORCHARD
SGD 5.50 — UOB Card *1234
25 Mar 2026, 2:15 PM

Suggested: Food & Drink

[✅ Food & Drink] [🛒 Groceries]
[🚗 Transport]    [✏️ Other]
```

When the user taps a button:
1. Update the transaction's category in Firefly III
2. Auto-create a Firefly III rule: "description contains '{merchant}' → set category to '{chosen_category}'"
3. Next time this merchant appears, it auto-categorizes without LLM or user input

If user taps "Other", show the full category list as another inline keyboard.

---

## Telegram Bot — Detailed Specification

### Setup

- Create bot via @BotFather on Telegram
- Create a Telegram group chat with you, your wife, and the bot
- Bot only responds in the authorized group chat (check `TELEGRAM_CHAT_ID` on every message)
- Use `python-telegram-bot` library with async handlers
- Bot runs as part of the worker service (not a separate process)
- Both users can send commands, confirm categories, and ask questions
- Category confirmation: whoever taps the button first, it's done

### Commands

#### `/refresh`
Triggers a full data refresh:
1. Fetch and process new bank alert emails from Gmail (filtered by "Bank Alerts" label)
2. Pull latest IBKR data via Flex Query API and update balance in Firefly III
3. Reply with summary of new transactions and IBKR portfolio value
4. If IBKR token is expired, notify user to renew it

Automatic background tasks:
- Email polling: every 5 minutes
- IBKR update: daily at 7am SGT (after US market close data is available)

#### `/balance`
Shows all account balances (savings, investments, cards) and net worth. HTML formatted with bold amounts.

#### `/spent [period] [category]`
List transactions and total spending for a given period, with optional category filter.

**Instant periods (no LLM):**
- `today`, `yesterday`
- `this week`, `last week`
- `this month`, `last month`
- `this year`, `last year`
- `last N days/weeks/months` (e.g. `last 7 days`, `past 3 months`)
- Month names: `january`, `feb`, `march 2025`
- Month ranges: `jan to mar`, `feb - jun 2025`

**LLM fallback:** Unrecognized periods are sent to GPT-4.1 nano for interpretation (e.g. "since christmas", "Q1 2026").

**Category filter:** Optional last word (e.g. `/spent this month food`, `/spent last week transport`).

#### `/summary [period]`
Spending summary for a period (defaults to this month). Same period parsing as `/spent`.
- Total income vs total expenses
- Net (income - expenses)
- Comparison vs previous period of same length (% change)
- Breakdown by category (sorted by amount)
- Top 5 merchants by spend

#### `/update <account> <balance>`
Manually set an account balance. Creates a transfer transaction to/from "Market Value Adjustment" account so it doesn't affect spending reports.
- `/update syfe 8500` — set Syfe Cash balance to $8,500
- `/update ibkr 45200` — manually set IBKR portfolio value
- `/update "OCBC Savings" 3210.50` — exact account name with quotes

Fuzzy-matches the account name against Firefly III accounts.

#### `/lastupdate`
Shows the last activity date for each account.

#### `/help [command]`
Shows command overview, or detailed usage for a specific command (e.g. `/help spent`).

### Category Confirmation Callbacks

When the bot sends a category suggestion (inline keyboard):
- Handle button taps via callback queries
- Update Firefly III transaction with chosen category
- Auto-create Firefly III rule for the merchant
- Reply with confirmation: "✅ Categorized as Food & Drink. Rule created."

### Natural Language Queries (LLM-powered)

Any message that isn't a command gets routed to the LLM query handler with configurable personality and conversation memory.

#### Bot Personality (configurable)

The bot's personality is defined in `soul.md` — a plain Markdown file in the project root. The worker reads it on startup and uses it as the system prompt for all LLM queries. Edit the file anytime; restart the worker to apply changes.

```python
# config.py
SOUL_FILE_PATH = os.getenv("SOUL_FILE_PATH", "/app/soul.md")

def load_personality() -> str:
    try:
        with open(SOUL_FILE_PATH, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "You are a friendly personal finance assistant. Be concise and use SGD."

BOT_PERSONALITY = load_personality()
```

### soul.md file

This file lives at the project root and is mounted into the worker container as a read-only volume. Edit it directly on your VPS with any text editor — no code changes needed.

**Default soul.md:**

```markdown
# Finance Bot

You are a friendly personal finance assistant for a couple in Singapore.

## Communication Style
- Be concise and practical
- Use SGD for all amounts
- Give actionable insights when relevant
- Keep responses short — this is a Telegram chat, not a report

## When the couple is under budget
Celebrate briefly. A simple "Nice, on track this month!" is enough.

## When they're overspending
Be honest but not judgmental. Point out which category is growing 
and suggest a specific, practical adjustment.

## Formatting
- Use bullet points for lists
- Bold key numbers
- Use emojis sparingly — one per message max
```

**Example alternative: Singlish auntie style**

```markdown
# Auntie Money

You are Auntie Money, a warm Singaporean auntie who helps a couple 
manage their finances. You speak with occasional Singlish.

## Communication Style
- Warm and encouraging, like a favourite auntie
- Use Singlish naturally but don't overdo it
- Use SGD for all amounts
- Keep it real — don't sugarcoat bad spending

## Reactions
- Under budget: "Wah, steady lah! This month looking good."
- Overspending: "Aiyo, the food spending a bit jialat already. 
  Maybe cook more this week?"
- Big purchase: "Wah, this one not small ah. You sure or not?"

## Rules
- Never be mean, just honest
- Always suggest a practical fix, not just point out the problem
```

**To change personality:** edit `soul.md` on your VPS, then `docker compose restart worker`. Takes effect immediately.

The personality can be changed anytime without modifying any code — just edit the file and restart.

#### Conversation History (configurable)

The bot maintains a short conversation history per chat session to support multi-turn queries like:
- "How much did I spend on food?" → answer
- "What about transport?" → understands you're comparing categories

```python
# config.py
CONVERSATION_HISTORY_LENGTH = int(os.getenv("CONVERSATION_HISTORY_LENGTH", "5"))  # Number of exchanges to remember
CONVERSATION_TIMEOUT_MINUTES = int(os.getenv("CONVERSATION_TIMEOUT_MINUTES", "30"))  # Reset history after inactivity
```

```python
# bot/llm_query.py
from collections import defaultdict
from datetime import datetime, timedelta

# In-memory conversation history per chat
conversation_histories = defaultdict(list)
last_activity = defaultdict(datetime.now)

async def handle_natural_query(update, context):
    chat_id = update.effective_chat.id
    question = update.message.text
    
    # Reset history if inactive for too long
    if datetime.now() - last_activity[chat_id] > timedelta(minutes=CONVERSATION_TIMEOUT_MINUTES):
        conversation_histories[chat_id] = []
    last_activity[chat_id] = datetime.now()
    
    # Fetch relevant financial data from Firefly III
    accounts = await firefly_client.get_accounts()
    recent_transactions = await firefly_client.get_transactions(days=90)
    budgets = await firefly_client.get_budgets()
    categories_summary = await firefly_client.get_category_spending(days=30)
    
    # Build context
    finance_context = format_finance_context(
        accounts, recent_transactions, budgets, categories_summary
    )
    
    # Build messages with personality + history + new question
    messages = [
        {"role": "system", "content": f"""{BOT_PERSONALITY}

Today's date is {today}.

FINANCIAL DATA:
{finance_context}"""},
        *conversation_histories[chat_id],  # Previous exchanges
        {"role": "user", "content": question}
    ]
    
    response = await openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        max_tokens=500,
        messages=messages
    )
    
    answer = response.choices[0].message.content
    
    # Store in history (keep last N exchanges)
    conversation_histories[chat_id].append({"role": "user", "content": question})
    conversation_histories[chat_id].append({"role": "assistant", "content": answer})
    conversation_histories[chat_id] = conversation_histories[chat_id][-(CONVERSATION_HISTORY_LENGTH * 2):]
    
    await update.message.reply_text(answer)
```

**Configuration options:**
- `soul.md` — Bot personality file. Edit and restart worker to change personality. No code changes needed.
- `CONVERSATION_HISTORY_LENGTH` — Number of past exchanges to include (default: 5). Set to 0 to disable conversation memory entirely.
- `CONVERSATION_TIMEOUT_MINUTES` — Reset conversation history after this many minutes of inactivity (default: 30). Prevents stale context from confusing the bot.

**Note:** Conversation history is stored in-memory only. It resets when the worker restarts. This is intentional — financial data lives in Firefly III, not in chat history. The conversation history only exists to support multi-turn follow-up questions.

Example multi-turn conversation:
```
You: "How much did I spend on food this month?"
Bot: "Food this month: $487 across 32 transactions. That's 15% 
     more than last month's $423."

You: "What about transport?"
Bot: "Transport this month: $320 across 18 transactions. That's 
     actually 8% less than last month — nice lah!"

You: "Which category should I cut back on?"
Bot: "Food is the one growing fastest — up 15%. Most of the increase 
     is GrabFood orders (12 this month vs 7 last month). Maybe cook 
     a bit more? Transport is already trending down, so steady."
```

Example queries the user can ask:
- "How am I doing this month vs last month?"
- "What's my biggest expense category?"
- "How much am I spending on subscriptions?"
- "At this rate, how much will I save by December?"
- "Any unusual transactions this week?"
- "What's my average daily spend?"

### Proactive Alerts (Optional Enhancement)

The bot can also proactively message the user:
- When a transaction above a certain amount is detected (e.g., > $500)
- When daily/weekly spending exceeds a user-defined budget
- When a new recurring transaction is detected

---

## IBKR Integration (`ibkr_flex.py`)

### Flex Web Service

IBKR Flex Queries allow downloading activity reports as XML via HTTP — no TWS or Gateway needed.

Setup:
1. In IBKR Client Portal → Reports → Flex Queries → Create new query
2. Configure to include: Account balances, positions, trades, cash transactions
3. Note the Query ID
4. Generate a Flex Web Service Token in Account Settings

Fetching:
```python
async def fetch_ibkr_flex():
    # Step 1: Request report generation
    request_url = (
        f"https://ndcdyn.interactivebrokers.com/AccountManagement/FlexStatementService.SendRequest"
        f"?t={FLEX_TOKEN}&q={FLEX_QUERY_ID}&v=3"
    )
    resp = await httpx.get(request_url)
    reference_code = parse_reference_code(resp.text)
    
    # Step 2: Wait briefly, then fetch the report
    await asyncio.sleep(5)
    statement_url = (
        f"https://ndcdyn.interactivebrokers.com/AccountManagement/FlexStatementService.GetStatement"
        f"?t={FLEX_TOKEN}&q={reference_code}&v=3"
    )
    resp = await httpx.get(statement_url)
    
    # Step 3: Parse XML and push to Firefly III
    positions = parse_flex_xml(resp.text)
    await update_firefly_ibkr_accounts(positions)
```

### What to Track in Firefly III

- Asset account "IBKR Portfolio" — balance updated automatically
- Balance changes are recorded as transfers to/from "Market Value Adjustment" account (not deposits/withdrawals) so they don't affect spending reports
- IBKR token expires ~yearly; bot notifies via Telegram when expired
- Daily auto-update at 7am SGT; also updates on `/refresh`

---

## Firefly III Configuration

### Accounts to Create

Asset accounts:
- OCBC Child Savings Account (SGD)
- UOB One Account (SGD)
- IBKR Portfolio (SGD) — updated automatically via Flex Query API (daily at 7am SGT) and on `/refresh`
- Syfe Cash (SGD) — updated manually via `/update syfe <balance>`
- Market Value Adjustment (SGD) — counterpart for investment balance transfers, ignore this account

Liability accounts:
- UOB Absolute Cashback Amex (SGD)
- Trust Card (SGD)
- (Add future shared credit cards here as liability accounts)

Revenue accounts (auto-created on first transaction):
- Salary
- Dividends
- Interest

Note: DBS accounts are personal/private and excluded from tracking.

Expense accounts: auto-created per merchant by Firefly III

**Important:** Balance adjustments for IBKR/Syfe use transfer transactions (not deposits/withdrawals) to/from the "Market Value Adjustment" account. This ensures investment value changes don't appear as income or expenses in spending reports.

### Categories

Create these categories in Firefly III:
- Food & Drink
- Groceries
- Transport
- Shopping
- Health
- Subscriptions
- Utilities
- Education
- Housing
- Misc

Note: No "Investments" category needed — money flowing into investment accounts (IBKR, Syfe) is tracked as transfers between accounts, not expenses.

### Auto-categorization Rules

Initial rules to create (the system will auto-create more over time):

| Trigger (description contains) | Category |
|-------------------------------|----------|
| GRAB, GOJEK, COMFORT, CDG | Transport |
| NTUC, FAIRPRICE, COLD STORAGE, GIANT, SHENG SIONG | Groceries |
| NETFLIX, SPOTIFY, YOUTUBE, DISNEY | Subscriptions |
| GUARDIAN, WATSONS, UNITY | Health |
| STARBUCKS, KOPITIAM, FOODPANDA, DELIVEROO, GRABFOOD | Food & Drink |
| SHELL, SPC, ESSO, CALTEX | Transport |
| SINGTEL, STARHUB, M1, SIMBA | Utilities |
| SP GROUP, SP SERVICES | Utilities |

---

## Deployment Steps

### 1. Homelab Server Setup

1. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   newgrp docker
   ```
2. Install Cloudflare Tunnel:
   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared.deb
   cloudflared tunnel login
   cloudflared tunnel create finance-tracker
   ```
3. Configure the tunnel at `/etc/cloudflared/config.yml` and install as service:
   ```bash
   sudo cloudflared service install
   sudo systemctl enable cloudflared
   sudo systemctl start cloudflared
   ```
4. Add DNS route:
   ```bash
   cloudflared tunnel route dns finance-tracker finance.lam-lab.cc
   ```
5. Clone the repo:
   ```bash
   git clone https://github.com/isaaclhk/Finance-Tracker.git
   cd Finance-Tracker
   ```
6. Create `.env` and fill in all secrets (see .env template above)
7. Start Firefly III, configure accounts/categories/token, then start worker:
   ```bash
   docker compose up -d firefly
   # ... configure Firefly III via web UI ...
   docker compose up -d --build worker
   ```

### Updating the app

```bash
cd Finance-Tracker
git pull
docker compose up -d --build worker   # Rebuild worker if code changed
docker compose pull                   # Pull latest Firefly III image
docker compose up -d                  # Restart with new images
```

### Backups

Set up a daily cron job to back up the SQLite database file:
```bash
mkdir -p ~/backups
crontab -e
# Add:
0 3 * * * docker cp $(docker ps -qf name=firefly):/var/www/html/storage/database/database.sqlite ~/backups/firefly-$(date +\%Y\%m\%d).sqlite && find ~/backups -name "firefly-*.sqlite" -mtime +30 -delete
```

### 2. Gmail Setup (Label-Based Filtering)

All bank alert emails are filtered into a single Gmail label ("Bank Alerts"). The worker only reads emails with this label.

**Setup in the primary Gmail account:**
1. Go to Gmail → Settings → Filters and Blocked Addresses → Create a new filter
2. In "From", enter: `documents@ocbc.com OR Notifications@ocbc.com OR unialerts@uobgroup.com`
3. Create filter → **Skip the Inbox** + **Apply the label: Bank Alerts**
4. Check **Also apply filter to matching conversations**

**If bank alerts go to different Gmail accounts:**
- In each secondary Gmail: Settings → Forwarding → Forward to the primary Gmail
- Create filters in secondary accounts: match bank senders → Forward + Mark as read
- Forwarded emails get the "Bank Alerts" label via the filter in the primary account

### 3. Gmail API Setup

1. Go to Google Cloud Console → Create project
2. Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download credentials JSON
5. Run initial OAuth flow locally to get refresh token
6. Add credentials and refresh token to your `.env` file on the VPS

### 4. Telegram Bot Setup

1. Message @BotFather on Telegram → `/newbot`
2. Get bot token
3. Create a group chat with you and your wife, add the bot to the group
4. Get the group chat ID (send a message in the group, then check `https://api.telegram.org/bot<TOKEN>/getUpdates` for the chat ID)
5. Add bot token and chat ID to your `.env` file on the VPS

### 5. IBKR Flex Query Setup

1. Log into IBKR Client Portal
2. Go to Reports → Flex Queries → Create
3. Include: Account balances, positions, trades, cash transactions
4. Save and note the Query ID
5. Go to Account Settings → generate Flex Web Service Token
6. Add both to your `.env` file on the VPS

### 6. Firefly III Initial Config

1. Access Firefly III via `https://finance.yourdomain.com`
2. Create admin account
3. Create accounts with **today's opening balances** (check each bank app for current balances):

   **Asset accounts:**
   - OCBC Savings → opening balance: your current balance
   - UOB Savings → opening balance: your current balance
   - IBKR Portfolio → opening balance: your current total equity
   - Syfe Cash → opening balance: your current balance

   **Liability accounts:**
   - UOB Credit Card → opening balance: your current outstanding amount
   - Trust Card → opening balance: your current outstanding amount

   When creating each account, Firefly III will ask for "Opening balance" and "Opening balance date" — set the date to today. From this point forward, every email-parsed transaction adjusts these balances automatically.

4. Create categories (list above)
5. Generate a Personal Access Token (Profile → OAuth → Personal Access Tokens)
6. Add the token as `FIREFLY_TOKEN` in your `.env` file and restart the worker: `docker compose restart worker`
7. Set up initial auto-categorization rules (table above)

Note: No historical transaction import is needed. The app starts tracking from today — the first few weeks will build up your spending patterns and auto-categorization rules.

### 7. Bank & Card Alert Configuration

You need email alerts enabled for every transaction on the shared accounts only. DBS accounts are personal and excluded from tracking.

#### OCBC (1 savings/checking account)
1. Open OCBC app → More → Profile & App Settings → Manage Notifications
2. Enable push notifications (this also enables email)
3. For account alerts:
   - Outgoing banking transactions will be sent via email by default once push notifications are enabled
   - Set transaction threshold to **$0.01**
4. Ensure your email address is registered (required when enabling push notifications)

#### UOB (1 credit card + 1 savings account)
1. Open UOB TMRW app → Settings → Transaction Alerts
2. For the **credit card**:
   - Set local card transaction threshold to **$0.01**
   - Set overseas card transaction threshold to **$0.01**
   - Delivery via **push + email**
3. For the **savings account**:
   - Set fund transfer threshold to **$0.01**
   - Set ATM withdrawal threshold to **$0.01**
   - Delivery via **push + email**
4. Ensure your email address and phone number are registered in UOB TMRW

#### Trust Bank (1 card)
1. Open Trust app → Profile → Settings → Notification Settings
2. Transaction push notifications are mandatory and cannot be disabled
3. **Important:** Check whether Trust Bank also sends **email** alerts for transactions. If not, your options are:
   - Check if there's an email notification setting in the app
   - Contact Trust Bank support to confirm email alert availability
   - If email alerts are not available, Trust Bank transactions will only be captured during monthly eStatement reconciliation, OR you could forward push notification content to email using an automation app (e.g., IFTTT or Tasker on Android)
4. Note: Trust Bank is a newer digital bank — their email alert format will need to be verified during initial setup

#### Future Shared Cards
The LLM-based parser is bank-agnostic — when you add a new shared card in the future:
1. Enable email alerts on the new card with $0 or $0.01 threshold
2. Add the card's last 4 digits to the `ACCOUNT_MAP` in your worker config
3. Create the corresponding liability account in Firefly III
4. No code changes needed — the universal LLM parser handles any bank's email format

#### Verifying Your Setup
After enabling alerts, make a small test transaction on each account/card and confirm:
- [ ] Email arrives within a few minutes
- [ ] Email contains: amount, merchant name, card/account identifier, date
- [ ] Note the exact sender email address for each bank (needed for Gmail filtering)

**Confirmed sender addresses:**
| Bank | Sender address |
|------|---------------|
| OCBC | `documents@ocbc.com`, `Notifications@ocbc.com` |
| UOB | `unialerts@uobgroup.com` |
| Trust | TBD — verify actual sender address |

These are used in Gmail filters to label emails as "Bank Alerts". The worker itself filters by label, not by sender.

---

## Security Considerations

- All secrets are stored in `.env` on the server — never commit this file to git. Add `.env` to `.gitignore`.
- The Gmail API OAuth token grants read-only access to the user's inbox. Store securely in `.env`.
- Firefly III Personal Access Token should be treated as a secret.
- IBKR Flex Token provides read-only access to account reports (~1 year expiry). The bot notifies via Telegram when it expires.
- Telegram bot only responds in the configured `TELEGRAM_CHAT_ID` group. All other messages are ignored silently.
- Cloudflare Tunnel handles HTTPS — Firefly III is only exposed on `127.0.0.1:8080` (localhost), never directly to the internet.
- No ports are opened on the server — Cloudflare Tunnel uses outbound connections only.
- Do not open `.env` in an IDE during Claude Code sessions — the IDE may send file contents to the chat, exposing secrets.

---

## Estimated Costs

| Item | Monthly Cost |
|------|-------------|
| Homelab server | $0 (already owned) |
| Cloudflare Tunnel | Free |
| Domain name | ~$1 (annual, amortized) |
| GPT-4.1 nano (parsing + categorization) | ~$0.01-0.05 |
| GPT-4.1 mini (queries) | ~$1-4 (depends on usage) |
| Gmail API | Free |
| Telegram Bot API | Free |
| IBKR Flex Queries | Free |
| **Total** | **~$1-5/month** |

---

## Future Enhancements (Not in Initial Build)

- Budget alerts: Bot proactively warns when spending in a category approaches a user-defined limit
- Fraud detection: Expand LLM parsing prompt to include fraud risk scoring based on transaction patterns
- Spending anomaly detection: Flag unusually large or unusual transactions
- Savings goal tracking: Set targets and track progress
- Multi-currency support: Handle USD transactions from IBKR alongside SGD
- Receipt photo OCR: Send a receipt photo to the Telegram bot, extract amount and merchant
- Weekly/monthly email digest: Automated spending summary sent to email
- CPF integration: Manual or semi-automated monthly import when ready
- Custom PWA frontend: Build a mobile-optimized web app with custom dashboard, refresh button, and spending charts for full control over the UI
- Personal account tracking: Optionally add DBS or other personal accounts with per-user visibility via separate Telegram DMs
- Ghostfolio integration: Add detailed investment portfolio tracking (individual holdings, performance, asset allocation) alongside Firefly III
