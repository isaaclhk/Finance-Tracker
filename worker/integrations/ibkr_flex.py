import asyncio
import logging
import xml.etree.ElementTree as ET

import httpx

from worker.config import IBKR_FLEX_QUERY_ID, IBKR_FLEX_TOKEN

logger = logging.getLogger(__name__)

FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


def _parse_reference_code(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
        code_elem = root.find(".//ReferenceCode")
        if code_elem is not None and code_elem.text:
            return code_elem.text
        ref = root.text or ""
        if ref.strip():
            return ref.strip()
    except ET.ParseError:
        logger.exception("Failed to parse IBKR reference code response")
    return None


def _parse_flex_xml(xml_text: str) -> dict:
    result = {
        "total_equity": 0.0,
        "positions": [],
        "cash_balances": [],
    }
    try:
        root = ET.fromstring(xml_text)

        for eq in root.iter("EquitySummaryInBase"):
            total = eq.get("totalLong", "0")
            result["total_equity"] = float(total)
            break

        for pos in root.iter("OpenPosition"):
            result["positions"].append(
                {
                    "symbol": pos.get("symbol", ""),
                    "quantity": float(pos.get("position", "0")),
                    "market_value": float(pos.get("markPrice", "0")),
                    "currency": pos.get("currency", "USD"),
                }
            )

        for cash in root.iter("CashReportCurrency"):
            result["cash_balances"].append(
                {
                    "currency": cash.get("currency", ""),
                    "balance": float(cash.get("endingCash", "0")),
                }
            )
    except ET.ParseError:
        logger.exception("Failed to parse IBKR Flex XML")

    return result


def _check_for_error(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
        error_code = root.get("errorCode", "")
        error_msg = root.get("errorMessage", "")
        if error_code or "invalid" in xml_text.lower():
            return error_msg or f"Error code: {error_code}"
    except ET.ParseError:
        pass
    return None


async def fetch_ibkr_data() -> dict | None:
    if not IBKR_FLEX_TOKEN or not IBKR_FLEX_QUERY_ID:
        logger.info("IBKR API credentials not configured, skipping API fetch")
        return None

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Request report generation
        request_url = f"{FLEX_BASE_URL}/SendRequest?t={IBKR_FLEX_TOKEN}&q={IBKR_FLEX_QUERY_ID}&v=3"
        try:
            resp = await client.get(request_url)
            resp.raise_for_status()
        except Exception:
            logger.exception("Failed to request IBKR Flex report")
            return None

        error = _check_for_error(resp.text)
        if error:
            logger.error("IBKR Flex API error: %s", error)
            raise IBKRTokenError(error)

        reference_code = _parse_reference_code(resp.text)
        if not reference_code:
            logger.error("Could not extract reference code from IBKR response")
            return None

        # Step 2: Wait for report generation
        await asyncio.sleep(5)

        # Step 3: Fetch the report
        statement_url = f"{FLEX_BASE_URL}/GetStatement?t={IBKR_FLEX_TOKEN}&q={reference_code}&v=3"
        try:
            resp = await client.get(statement_url)
            resp.raise_for_status()
        except Exception:
            logger.exception("Failed to fetch IBKR Flex report")
            return None

        return _parse_flex_xml(resp.text)


class IBKRTokenError(Exception):
    pass
