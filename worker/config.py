import logging
import os

logger = logging.getLogger(__name__)

# Firefly III
FIREFLY_URL = os.getenv("FIREFLY_URL", "http://localhost:8080")
FIREFLY_TOKEN = os.getenv("FIREFLY_TOKEN", "")
FIREFLY_MERCHANT_EXPENSE_ACCOUNT = os.getenv("FIREFLY_MERCHANT_EXPENSE_ACCOUNT", "Merchant Spend")

# Gmail
GMAIL_CREDENTIALS = os.getenv("GMAIL_CREDENTIALS", "")
GMAIL_LABEL = os.getenv("GMAIL_LABEL", "Bank Alerts")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")
OPENAI_QUERY_MODEL = os.getenv("OPENAI_QUERY_MODEL", "gpt-4.1-mini")

# IBKR
IBKR_FLEX_TOKEN = os.getenv("IBKR_FLEX_TOKEN", "")
IBKR_FLEX_QUERY_ID = os.getenv("IBKR_FLEX_QUERY_ID", "")

# Account mapping (JSON string: {"1234": "UOB Credit Card", "5678": "OCBC Savings", ...})
ACCOUNT_MAP_JSON = os.getenv("ACCOUNT_MAP", "")

# Validation thresholds
VALIDATION_LARGE_AMOUNT_THRESHOLD = float(os.getenv("VALIDATION_LARGE_AMOUNT_THRESHOLD", "5000"))
VALIDATION_SMALL_AMOUNT_MIN = float(os.getenv("VALIDATION_SMALL_AMOUNT_MIN", "0.01"))
VALIDATION_MAX_AMOUNT = float(os.getenv("VALIDATION_MAX_AMOUNT", "50000"))

# Conversation memory
CONVERSATION_HISTORY_LENGTH = int(os.getenv("CONVERSATION_HISTORY_LENGTH", "5"))
CONVERSATION_TIMEOUT_MINUTES = int(os.getenv("CONVERSATION_TIMEOUT_MINUTES", "30"))

# Polling
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))

# Bot personality
SOUL_FILE_PATH = os.getenv("SOUL_FILE_PATH", "/app/soul.md")


def load_personality() -> str:
    try:
        with open(SOUL_FILE_PATH) as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.debug("Soul file not found at %s, using default personality", SOUL_FILE_PATH)
        return "You are a friendly personal finance assistant. Be concise and use SGD."


BOT_PERSONALITY = load_personality()
