import logging
from datetime import date, timedelta
from decimal import Decimal

from worker.integrations import firefly_client

logger = logging.getLogger(__name__)


async def is_duplicate(parsed: dict, start_date: date | None = None) -> bool:
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
    except Exception:
        logger.exception("Failed to check for duplicates")
        return False

    amount = Decimal(str(parsed.get("amount", 0)))
    merchant = (parsed.get("merchant") or "").lower()

    for txn in existing:
        attrs = txn.get("attributes", {})
        transactions = attrs.get("transactions", [])
        for t in transactions:
            existing_amount = Decimal(str(t.get("amount", 0)))
            existing_desc = (t.get("description") or "").lower()

            amounts_match = abs(existing_amount - amount) < Decimal("0.01")
            if amounts_match and merchant and merchant in existing_desc:
                return True

    return False
