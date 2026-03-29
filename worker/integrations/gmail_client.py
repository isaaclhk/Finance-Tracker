import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from worker.config import GMAIL_CREDENTIALS, GMAIL_LABEL

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CURSOR_FILE = os.getenv("GMAIL_CURSOR_FILE", "/app/data/gmail_cursor.json")


class HistoryExpiredError(Exception):
    pass


@dataclass
class Email:
    message_id: str
    sender: str
    subject: str
    body: str
    timestamp: str
    attachments: list[dict] | None = None  # [{"filename": ..., "data": bytes}]


def _build_service():
    creds_data = json.loads(GMAIL_CREDENTIALS) if GMAIL_CREDENTIALS else {}
    if not creds_data:
        raise RuntimeError("GMAIL_CREDENTIALS not configured")
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
    return build("gmail", "v1", credentials=creds)


def _load_cursor() -> dict:
    try:
        with open(CURSOR_FILE) as f:
            data = json.load(f)
            return {
                "history_id": data.get("history_id"),
                "last_timestamp": data.get("last_timestamp"),
            }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"history_id": None, "last_timestamp": None}


def save_cursor(history_id: int, timestamp: str | None = None):
    os.makedirs(os.path.dirname(CURSOR_FILE), exist_ok=True)
    data: dict = {"history_id": history_id}
    if timestamp:
        data["last_timestamp"] = timestamp
    with open(CURSOR_FILE, "w") as f:
        json.dump(data, f)


def _get_current_history_id(service) -> int:
    profile = service.users().getProfile(userId="me").execute()
    return int(profile["historyId"])


def _get_label_id(service) -> str | None:
    try:
        results = service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label["name"] == GMAIL_LABEL:
                return label["id"]
    except Exception:
        logger.exception("Failed to list Gmail labels")
    return None


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


def _extract_attachments(service, message_id: str, payload: dict) -> list[dict]:
    attachments = []
    for part in payload.get("parts", []):
        filename = part.get("filename", "")
        if not filename:
            continue
        attachment_id = part.get("body", {}).get("attachmentId")
        if not attachment_id:
            continue
        try:
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data = base64.urlsafe_b64decode(att["data"])
            attachments.append({"filename": filename, "data": data})
        except Exception:
            logger.exception("Failed to fetch attachment %s", filename)
    return attachments


def _parse_message(service, msg_id: str) -> Email | None:
    msg = service.users().messages().get(userId="me", id=msg_id).execute()
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

    attachments = _extract_attachments(service, msg_id, msg["payload"])

    return Email(
        message_id=msg_id,
        sender=sender,
        subject=subject,
        body=body,
        timestamp=timestamp,
        attachments=attachments or None,
    )


def _compute_latest_timestamp(emails: list[Email], fallback: str | None) -> str | None:
    timestamps = [e.timestamp for e in emails if e.timestamp]
    if timestamps:
        return max(timestamps)
    return fallback


def _fetch_via_search(
    service, label_id: str, after_timestamp: str | None
) -> tuple[list[Email], str | None]:
    query = ""
    if after_timestamp:
        try:
            dt = datetime.fromisoformat(after_timestamp)
            epoch = int(dt.timestamp())
            query = f"after:{epoch}"
        except (ValueError, OSError):
            query = f"after:{after_timestamp}"

    try:
        results = (
            service.users().messages().list(userId="me", labelIds=[label_id], q=query).execute()
        )
    except Exception:
        logger.exception("Failed to list Gmail messages")
        return [], None

    messages = results.get("messages", [])
    if not messages:
        return [], None

    emails: list[Email] = []
    latest_timestamp = after_timestamp

    for msg_ref in messages:
        try:
            email = _parse_message(service, msg_ref["id"])
            if email:
                emails.append(email)
                if email.timestamp and (not latest_timestamp or email.timestamp > latest_timestamp):
                    latest_timestamp = email.timestamp
        except Exception:
            logger.exception("Failed to fetch message %s", msg_ref["id"])
            continue

    return emails, latest_timestamp


def _fetch_via_history(service, label_id: str, start_history_id: int) -> tuple[list[Email], int]:
    message_ids: set[str] = set()
    page_token = None
    new_history_id = start_history_id

    while True:
        try:
            params: dict = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "labelId": label_id,
                "historyTypes": ["messageAdded"],
            }
            if page_token:
                params["pageToken"] = page_token

            response = service.users().history().list(**params).execute()
        except HttpError as e:
            if e.resp.status == 404:
                raise HistoryExpiredError(f"History ID {start_history_id} has expired") from e
            raise

        new_history_id = int(response["historyId"])

        for record in response.get("history", []):
            for added in record.get("messagesAdded", []):
                msg = added.get("message", {})
                if msg.get("id"):
                    message_ids.add(msg["id"])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    emails: list[Email] = []
    for msg_id in message_ids:
        try:
            email = _parse_message(service, msg_id)
            if email:
                emails.append(email)
        except Exception:
            logger.exception("Failed to fetch message %s", msg_id)
            continue

    return emails, new_history_id


async def fetch_new_alerts() -> tuple[list[Email], int | None, str | None]:
    service = _build_service()
    cursor = _load_cursor()

    label_id = _get_label_id(service)
    if not label_id:
        logger.error("Gmail label '%s' not found", GMAIL_LABEL)
        return [], None, None

    history_id = cursor["history_id"]
    last_timestamp = cursor["last_timestamp"]

    if history_id:
        # Path A: incremental poll via History API
        try:
            emails, new_history_id = _fetch_via_history(service, label_id, history_id)
            latest_ts = _compute_latest_timestamp(emails, last_timestamp)
            return emails, new_history_id, latest_ts
        except HistoryExpiredError:
            logger.warning("History ID %s expired, falling back to search", history_id)

    # Path B (first run) or Path C (expired history / old cursor format)
    emails, latest_ts = _fetch_via_search(service, label_id, last_timestamp)
    new_history_id = _get_current_history_id(service)
    return emails, new_history_id, latest_ts or last_timestamp
