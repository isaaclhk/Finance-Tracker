import base64
import json
import logging
import os
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from worker.config import BANK_SENDERS, GMAIL_CREDENTIALS

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CURSOR_FILE = os.getenv("GMAIL_CURSOR_FILE", "/app/data/gmail_cursor.json")


@dataclass
class Email:
    message_id: str
    sender: str
    subject: str
    body: str
    timestamp: str


def _build_service():
    creds_data = json.loads(GMAIL_CREDENTIALS) if GMAIL_CREDENTIALS else {}
    if not creds_data:
        raise RuntimeError("GMAIL_CREDENTIALS not configured")
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
    return build("gmail", "v1", credentials=creds)


def _load_cursor() -> str | None:
    try:
        with open(CURSOR_FILE) as f:
            data = json.load(f)
            return data.get("last_timestamp")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_cursor(timestamp: str):
    os.makedirs(os.path.dirname(CURSOR_FILE), exist_ok=True)
    with open(CURSOR_FILE, "w") as f:
        json.dump({"last_timestamp": timestamp}, f)


def _build_sender_query() -> str:
    parts = [f"from:{sender}" for sender in BANK_SENDERS]
    return "{" + " ".join(parts) + "}"


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part["mimeType"] == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part["mimeType"] == "text/html" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    return ""


async def fetch_new_alerts() -> list[Email]:
    service = _build_service()
    cursor = _load_cursor()

    query = _build_sender_query()
    if cursor:
        query += f" after:{cursor}"

    try:
        results = service.users().messages().list(userId="me", q=query).execute()
    except Exception:
        logger.exception("Failed to list Gmail messages")
        return []

    messages = results.get("messages", [])
    if not messages:
        return []

    emails: list[Email] = []
    latest_timestamp = cursor

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(userId="me", id=msg_ref["id"]).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

            sender = headers.get("From", "")
            subject = headers.get("Subject", "")
            date_str = headers.get("Date", "")
            body = _extract_body(msg["payload"])

            timestamp = ""
            if date_str:
                try:
                    dt = parsedate_to_datetime(date_str)
                    timestamp = dt.isoformat()
                except Exception:
                    timestamp = date_str

            emails.append(
                Email(
                    message_id=msg_ref["id"],
                    sender=sender,
                    subject=subject,
                    body=body,
                    timestamp=timestamp,
                )
            )

            if timestamp and (not latest_timestamp or timestamp > latest_timestamp):
                latest_timestamp = timestamp

        except Exception:
            logger.exception("Failed to fetch message %s", msg_ref["id"])
            continue

    if latest_timestamp and latest_timestamp != cursor:
        _save_cursor(latest_timestamp)

    return emails
