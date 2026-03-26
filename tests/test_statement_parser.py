from worker.parsers.statement_parser import extract_transactions_from_pdf


def test_extract_returns_empty_for_invalid_pdf():
    result = extract_transactions_from_pdf(b"not a pdf")
    assert result == []


def test_extract_returns_empty_for_empty_bytes():
    result = extract_transactions_from_pdf(b"")
    assert result == []
