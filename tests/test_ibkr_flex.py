from worker.integrations.ibkr_flex import (
    _parse_flex_xml,
    _parse_reference_code,
    is_ibkr_email,
    parse_ibkr_from_email,
)


def test_parse_reference_code():
    xml = "<FlexStatementResponse><ReferenceCode>ABC123</ReferenceCode></FlexStatementResponse>"
    assert _parse_reference_code(xml) == "ABC123"


def test_parse_reference_code_returns_none_on_bad_xml():
    assert _parse_reference_code("not xml at all <<<") is None


def test_parse_flex_xml_positions():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <EquitySummaryInBase totalLong="45200.00" />
      <OpenPositions>
        <OpenPosition symbol="AAPL" position="10" markPrice="185.50" currency="USD" />
        <OpenPosition symbol="MSFT" position="5" markPrice="420.00" currency="USD" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency currency="USD" endingCash="1500.00" />
        <CashReportCurrency currency="SGD" endingCash="200.00" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

    result = _parse_flex_xml(xml)

    assert result["total_equity"] == 45200.00
    assert len(result["positions"]) == 2
    assert result["positions"][0]["symbol"] == "AAPL"
    assert result["positions"][0]["quantity"] == 10.0
    assert len(result["cash_balances"]) == 2
    assert result["cash_balances"][0]["currency"] == "USD"
    assert result["cash_balances"][0]["balance"] == 1500.00


def test_parse_flex_xml_empty():
    xml = "<FlexQueryResponse></FlexQueryResponse>"
    result = _parse_flex_xml(xml)
    assert result["total_equity"] == 0.0
    assert result["positions"] == []
    assert result["cash_balances"] == []


def test_is_ibkr_email():
    assert is_ibkr_email("donotreply@interactivebrokers.com") is True
    assert is_ibkr_email("DONOTREPLY@interactivebrokers.com") is True
    assert is_ibkr_email("alerts@ocbc.com") is False


def test_parse_ibkr_from_email_xml_attachment():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <EquitySummaryInBase totalLong="45200.00" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

    attachments = [{"filename": "report.xml", "data": xml.encode("utf-8")}]
    result = parse_ibkr_from_email(attachments)
    assert result is not None
    assert result["total_equity"] == 45200.00


def test_parse_ibkr_from_email_no_xml():
    attachments = [{"filename": "report.pdf", "data": b"not xml"}]
    result = parse_ibkr_from_email(attachments)
    assert result is None


def test_parse_ibkr_from_email_empty():
    result = parse_ibkr_from_email([])
    assert result is None
