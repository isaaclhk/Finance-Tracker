import logging
import re
from datetime import date, timedelta
from decimal import Decimal

import httpx

from worker.integrations import firefly_client
from worker.utils.firefly_time import has_time_component, parse_firefly_datetime, time_matches

logger = logging.getLogger(__name__)


def _normalize_merchant(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _uses_account(transaction: dict, account_name: str | None) -> bool:
    if not account_name:
        return True
    return account_name in {
        transaction.get("source_name"),
        transaction.get("destination_name"),
    }


async def is_duplicate(
    parsed: dict,
    start_date: date | None = None,
    source_account: str | None = None,
) -> bool:
    txn_date_str = parsed.get("date")
    if not txn_date_str:
        return False

    txn_date = date.fromisoformat(txn_date_str)
    search_start = start_date or (txn_date - timedelta(days=1))
    search_end = txn_date + timedelta(days=1)

    try:
        existing = await firefly_client.get_transactions(
            start_date=search_start,
            end_date=search_end,
        )
    except httpx.HTTPStatusError:
        logger.exception("Failed to check for duplicates")
        return False

    amount = Decimal(str(parsed.get("amount", 0)))
    merchant = _normalize_merchant(parsed.get("merchant") or "")
    target_time = parsed.get("time")

    for txn in existing:
        attrs = txn.get("attributes", {})
        transactions = attrs.get("transactions", [])
        for t in transactions:
            if not _uses_account(t, source_account):
                continue

            existing_amount = Decimal(str(t.get("amount", 0)))
            existing_desc = _normalize_merchant(t.get("description") or "")
            existing_date = t.get("date", "")

            amounts_match = abs(existing_amount - amount) < Decimal("0.01")
            if not amounts_match:
                continue

            stored_dt = parse_firefly_datetime(existing_date)
            if target_time and stored_dt and has_time_component(stored_dt):
                if time_matches(stored_dt, target_time):
                    return True
                continue

            merchant_matches = bool(
                merchant
                and existing_desc
                and (merchant in existing_desc or existing_desc in merchant)
            )
            if merchant_matches:
                return True

    return False
