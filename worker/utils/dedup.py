import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from worker.integrations import firefly_client

logger = logging.getLogger(__name__)


def _normalize_merchant(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _parse_firefly_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _uses_account(transaction: dict, account_name: str | None) -> bool:
    if not account_name:
        return True
    return account_name in {
        transaction.get("source_name"),
        transaction.get("destination_name"),
    }


def _time_matches(stored_value: str, target_time: str | None) -> bool:
    if not target_time:
        return False

    stored_dt = _parse_firefly_datetime(stored_value)
    if stored_dt is None:
        return False

    try:
        hour, minute = target_time.split(":")
        expected = stored_dt.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    except (ValueError, AttributeError):
        return False

    stored = stored_dt.replace(second=0, microsecond=0)
    return abs((stored - expected).total_seconds()) <= 60


def _has_stored_time(value: str) -> bool:
    stored_dt = _parse_firefly_datetime(value)
    return bool(stored_dt and (stored_dt.hour or stored_dt.minute or stored_dt.second))


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

            if target_time and _has_stored_time(existing_date):
                if _time_matches(existing_date, target_time):
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
