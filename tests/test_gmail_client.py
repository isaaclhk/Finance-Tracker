import base64

from worker.integrations.gmail_client import _extract_body


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
