import base64
import json

from worker.integrations.gmail_client import (
    Email,
    HistoryExpiredError,
    _compute_latest_timestamp,
    _extract_body,
    _load_cursor,
    save_cursor,
)


def test_extract_body_plain_text():
    body_data = base64.urlsafe_b64encode(b"Transaction alert: $5.50 at BOBER TEA").decode()
    payload = {
        "parts": [
            {"mimeType": "text/plain", "body": {"data": body_data}},
        ]
    }
    result = _extract_body(payload)
    assert "BOBER TEA" in result
    assert "$5.50" in result


def test_extract_body_direct():
    body_data = base64.urlsafe_b64encode(b"Direct body content").decode()
    payload = {"body": {"data": body_data}}
    result = _extract_body(payload)
    assert result == "Direct body content"


def test_extract_body_html_fallback():
    body_data = base64.urlsafe_b64encode(b"<p>HTML body</p>").decode()
    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": body_data}},
        ]
    }
    result = _extract_body(payload)
    assert "HTML body" in result


def test_extract_body_empty():
    payload = {"parts": []}
    result = _extract_body(payload)
    assert result == ""


def test_load_cursor_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "worker.integrations.gmail_client.CURSOR_FILE",
        str(tmp_path / "nonexistent.json"),
    )
    cursor = _load_cursor()
    assert cursor == {"history_id": None, "last_timestamp": None}


def test_load_cursor_old_format(tmp_path, monkeypatch):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text('{"last_timestamp": "2026-03-25T14:30:00"}')
    monkeypatch.setattr("worker.integrations.gmail_client.CURSOR_FILE", str(cursor_file))
    cursor = _load_cursor()
    assert cursor == {"history_id": None, "last_timestamp": "2026-03-25T14:30:00"}


def test_load_cursor_new_format(tmp_path, monkeypatch):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text('{"history_id": 12345, "last_timestamp": "2026-03-25T14:30:00"}')
    monkeypatch.setattr("worker.integrations.gmail_client.CURSOR_FILE", str(cursor_file))
    cursor = _load_cursor()
    assert cursor == {"history_id": 12345, "last_timestamp": "2026-03-25T14:30:00"}


def test_save_cursor_writes_both_fields(tmp_path, monkeypatch):
    cursor_file = str(tmp_path / "cursor.json")
    monkeypatch.setattr("worker.integrations.gmail_client.CURSOR_FILE", cursor_file)

    save_cursor(99999, "2026-03-29T10:00:00")

    with open(cursor_file) as f:
        data = json.load(f)
    assert data == {"history_id": 99999, "last_timestamp": "2026-03-29T10:00:00"}


def test_save_cursor_without_timestamp(tmp_path, monkeypatch):
    cursor_file = str(tmp_path / "cursor.json")
    monkeypatch.setattr("worker.integrations.gmail_client.CURSOR_FILE", cursor_file)

    save_cursor(99999)

    with open(cursor_file) as f:
        data = json.load(f)
    assert data == {"history_id": 99999}


def test_compute_latest_timestamp():
    emails = [
        Email("1", "", "", "", "2026-03-25T10:00:00"),
        Email("2", "", "", "", "2026-03-25T14:00:00"),
        Email("3", "", "", "", "2026-03-25T12:00:00"),
    ]
    assert _compute_latest_timestamp(emails, None) == "2026-03-25T14:00:00"


def test_compute_latest_timestamp_empty():
    assert _compute_latest_timestamp([], "fallback") == "fallback"


def test_history_expired_error_is_exception():
    assert issubclass(HistoryExpiredError, Exception)
