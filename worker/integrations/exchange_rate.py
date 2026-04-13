import logging

import httpx

logger = logging.getLogger(__name__)

FRANKFURTER_BASE_URL = "https://api.frankfurter.app"

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=FRANKFURTER_BASE_URL, timeout=10.0)
    return _client


async def close():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def convert_to_sgd(amount: float, currency: str) -> tuple[float, float] | None:
    """Convert a foreign amount to SGD.

    Returns (sgd_amount, rate) on success, or None on failure.
    """
    currency = currency.upper().strip()
    if currency == "SGD":
        return None

    client = get_client()
    try:
        resp = await client.get(
            "/latest",
            params={"from": currency, "to": "SGD", "amount": 1},
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["SGD"]
        return round(amount * rate, 2), rate
    except Exception:
        logger.exception("Exchange rate conversion failed for %s -> SGD", currency)
        return None
