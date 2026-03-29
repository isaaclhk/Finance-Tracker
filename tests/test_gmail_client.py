import base64
import json

from worker.integrations.gmail_client import (
    _extract_body,
    is_processed,
    mark_processed,
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


def test_is_processed_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "worker.integrations.gmail_client.PROCESSED_IDS_FILE",
        str(tmp_path / "processed.json"),
    )
    assert is_processed("msg-1") is False


def test_mark_and_is_processed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "worker.integrations.gmail_client.PROCESSED_IDS_FILE",
        str(tmp_path / "processed.json"),
    )
    mark_processed("msg-1")
    assert is_processed("msg-1") is True
    assert is_processed("msg-2") is False


def test_mark_processed_caps_at_max(tmp_path, monkeypatch):
    processed_file = str(tmp_path / "processed.json")
    monkeypatch.setattr("worker.integrations.gmail_client.PROCESSED_IDS_FILE", processed_file)
    monkeypatch.setattr("worker.integrations.gmail_client.MAX_PROCESSED_IDS", 5)

    for i in range(7):
        mark_processed(f"msg-{i}")

    with open(processed_file) as f:
        ids = json.load(f)
    assert len(ids) == 5
    # Oldest IDs should have been pruned
    assert "msg-0" not in ids
    assert "msg-1" not in ids
    assert "msg-6" in ids
