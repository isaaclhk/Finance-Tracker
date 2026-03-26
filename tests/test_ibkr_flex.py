from worker.integrations.ibkr_flex import _parse_flex_xml, _parse_reference_code


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
