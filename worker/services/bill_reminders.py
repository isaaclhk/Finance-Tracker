import json
import logging
import os
import re
from datetime import datetime, timedelta

from worker.utils.time import now_sgt

logger = logging.getLogger(__name__)

BILL_REMINDER_STATE_PATH = os.getenv("BILL_REMINDER_STATE_PATH", "/app/data/bill_reminders.json")

_DAYS_LEFT_RE = re.compile(r"\b(\d{1,2})\s+days?\s+left\s+to\s+pay\b", re.IGNORECASE)


def _email_field(email: object, name: str) -> str:
    return str(getattr(email, name, "") or "")


def _load_state() -> dict:
    try:
        with open(BILL_REMINDER_STATE_PATH) as f:
            data = json.load(f)
            if isinstance(data.get("sent"), dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"sent": {}}


def _save_state(state: dict):
    dirname = os.path.dirname(BILL_REMINDER_STATE_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(BILL_REMINDER_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _email_datetime(email: object) -> datetime:
    timestamp = _email_field(email, "timestamp")
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            logger.debug("Could not parse reminder email timestamp: %s", timestamp)
    return now_sgt()


def detect_trust_bill_reminder(email: object) -> dict | None:
    sender = _email_field(email, "sender")
    subject = _email_field(email, "subject")
    body = _email_field(email, "body")

    sender_text = sender.lower()
    content = f"{subject}\n{body}".lower()
    all_text = f"{sender}\n{subject}\n{body}".lower()

    if "trust" not in all_text and "trustbank.sg" not in sender_text:
        return None
    if "credit card bill" not in content:
        return None
    if "pay" not in content:
        return None
    reminder_markers = ("days left", "left to pay", "payment due", "reminder")
    if not any(marker in content for marker in reminder_markers):
        return None

    email_dt = _email_datetime(email)
    match = _DAYS_LEFT_RE.search(content)
    days_left = int(match.group(1)) if match else None
    due_date = None
    key_suffix = email_dt.strftime("%Y-%m")

    if days_left is not None:
        due_date = (email_dt.date() + timedelta(days=days_left)).isoformat()
        key_suffix = due_date

    return {
        "type": "bill_payment_reminder",
        "bank": "Trust",
        "account": "Trust credit card",
        "due_in_days": days_left,
        "due_date": due_date,
        "key": f"Trust:credit_card:{key_suffix}",
        "subject": subject,
    }


def was_sent(reminder_key: str) -> bool:
    return reminder_key in _load_state().get("sent", {})


def mark_sent(reminder: dict):
    key = reminder["key"]
    state = _load_state()
    sent = state.setdefault("sent", {})
    sent[key] = {
        "sent_at": now_sgt().isoformat(),
        "bank": reminder.get("bank"),
        "account": reminder.get("account"),
        "due_date": reminder.get("due_date"),
        "subject": reminder.get("subject"),
    }
    _save_state(state)
