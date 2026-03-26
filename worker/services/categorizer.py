import logging

from worker.integrations import firefly_client

logger = logging.getLogger(__name__)


def check_firefly_category(firefly_txn: dict) -> str | None:
    attrs = firefly_txn.get("attributes", {})
    transactions = attrs.get("transactions", [])
    if transactions:
        category = transactions[0].get("category_name")
        if category:
            return category
    return None


def categorize(firefly_txn: dict, suggested_category: str | None) -> tuple[str | None, bool]:
    existing = check_firefly_category(firefly_txn)
    if existing:
        return existing, False

    if suggested_category:
        return suggested_category, True

    return None, True


async def create_auto_rule(merchant: str, category: str):
    title = f"Auto: {merchant} → {category}"
    try:
        await firefly_client.create_rule(title, merchant, category)
        logger.info("Created auto-rule: %s", title)
    except Exception:
        logger.exception("Failed to create auto-rule for %s", merchant)
