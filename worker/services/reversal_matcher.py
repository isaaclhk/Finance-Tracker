import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from worker.integrations import firefly_client

logger = logging.getLogger(__name__)


def _parse_firefly_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _times_match(stored_dt: datetime, expected_hhmm: str) -> bool:
    try:
        hh, mm = expected_hhmm.split(":")
        expected = stored_dt.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, AttributeError):
        return False
    delta = abs((stored_dt.replace(second=0, microsecond=0) - expected).total_seconds())
    return delta <= 60


async def find_original_charge(validated: dict, source_account: str) -> list[dict]:
    """Return Firefly transaction groups that could be the reversed charge."""
    txn_date_str = validated.get("date")
    if not txn_date_str:
        return []

    try:
        txn_date = date.fromisoformat(txn_date_str)
    except ValueError:
        return []

    try:
        existing = await firefly_client.get_transactions(
            start_date=txn_date - timedelta(days=1),
            end_date=txn_date + timedelta(days=1),
        )
    except httpx.HTTPStatusError:
        logger.exception("Failed to fetch transactions for reversal match")
        return []

    target_amount = Decimal(str(validated.get("amount", 0)))
    target_time = validated.get("time")
    target_merchant = (validated.get("merchant") or "").lower()

    candidates: list[dict] = []
    for group in existing:
        for sub in group.get("attributes", {}).get("transactions", []):
            if sub.get("type") != "withdrawal":
                continue
            if sub.get("source_name") != source_account:
                continue
            if abs(Decimal(str(sub.get("amount", 0))) - target_amount) >= Decimal("0.01"):
                continue
            stored_dt = _parse_firefly_datetime(sub.get("date", ""))
            if stored_dt is None or stored_dt.date() != txn_date:
                continue
            if target_time and not _times_match(stored_dt, target_time):
                continue
            candidates.append(group)
            break

    if len(candidates) > 1 and target_merchant:
        narrowed = [
            g
            for g in candidates
            if any(
                target_merchant in (sub.get("description") or "").lower()
                for sub in g.get("attributes", {}).get("transactions", [])
            )
        ]
        if narrowed:
            return narrowed

    return candidates
