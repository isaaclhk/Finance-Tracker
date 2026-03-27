import logging
from datetime import date

import httpx

from worker.config import FIREFLY_TOKEN, FIREFLY_URL

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=FIREFLY_URL,
            headers={
                "Authorization": f"Bearer {FIREFLY_TOKEN}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client


async def close():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_accounts() -> list[dict]:
    client = get_client()
    resp = await client.get("/api/v1/accounts", params={"type": "all"})
    resp.raise_for_status()
    return resp.json()["data"]


async def get_transactions(
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: int | None = None,
) -> list[dict]:
    client = get_client()
    params: dict = {}
    if start_date:
        params["start"] = start_date.isoformat()
    if end_date:
        params["end"] = end_date.isoformat()
    if account_id:
        resp = await client.get(f"/api/v1/accounts/{account_id}/transactions", params=params)
    else:
        resp = await client.get("/api/v1/transactions", params=params)
    resp.raise_for_status()
    return resp.json()["data"]


async def create_transaction(payload: dict) -> dict:
    client = get_client()
    resp = await client.post("/api/v1/transactions", json=payload)
    if resp.status_code == 422:
        logger.error("Firefly III rejected transaction: %s", resp.text)
        logger.error("Payload was: %s", payload)
    resp.raise_for_status()
    return resp.json()["data"]


async def update_transaction(txn_id: int, payload: dict) -> dict:
    client = get_client()
    resp = await client.put(f"/api/v1/transactions/{txn_id}", json=payload)
    resp.raise_for_status()
    return resp.json()["data"]


async def create_rule(title: str, trigger_keyword: str, category_name: str) -> dict:
    client = get_client()
    payload = {
        "title": title,
        "rule_group_id": 1,
        "trigger": "store-transaction",
        "active": True,
        "strict": False,
        "triggers": [
            {
                "type": "description_contains",
                "value": trigger_keyword,
            }
        ],
        "actions": [
            {
                "type": "set_category",
                "value": category_name,
            }
        ],
    }
    resp = await client.post("/api/v1/rules", json=payload)
    resp.raise_for_status()
    return resp.json()["data"]


async def get_categories() -> list[dict]:
    client = get_client()
    resp = await client.get("/api/v1/categories")
    resp.raise_for_status()
    return resp.json()["data"]


async def search_transactions(query: str) -> list[dict]:
    client = get_client()
    resp = await client.get("/api/v1/search/transactions", params={"query": query})
    resp.raise_for_status()
    return resp.json()["data"]


async def get_budgets() -> list[dict]:
    client = get_client()
    resp = await client.get("/api/v1/budgets")
    resp.raise_for_status()
    return resp.json()["data"]


async def get_category_spending(start_date: date, end_date: date) -> list[dict]:
    client = get_client()
    params = {"start": start_date.isoformat(), "end": end_date.isoformat()}
    resp = await client.get("/api/v1/categories", params=params)
    resp.raise_for_status()
    return resp.json()["data"]
