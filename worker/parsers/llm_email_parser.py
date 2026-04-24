import logging

from worker.integrations import openai_client

logger = logging.getLogger(__name__)

RECORDABLE = "recordable"
NON_TRANSACTION = "non_transaction"
NEEDS_REVIEW = "needs_review"
RECORD_STATUSES = {RECORDABLE, NON_TRANSACTION, NEEDS_REVIEW}


async def parse_and_categorize(email_body: str, sender: str) -> dict | None:
    result = await openai_client.parse_and_categorize(email_body, sender)
    if result is None:
        logger.warning("LLM failed to parse email from %s", sender)
        return None

    logger.info("LLM parse result for %s: %s", sender, result)

    record_status = result.get("record_status")
    if record_status is None:
        record_status = RECORDABLE if isinstance(result.get("amount"), int | float) else None
        if record_status:
            result["record_status"] = record_status

    if record_status in (NON_TRANSACTION, NEEDS_REVIEW):
        return result

    if record_status not in RECORD_STATUSES:
        logger.warning("LLM returned invalid record_status: %s", record_status)
        return None

    if not isinstance(result.get("amount"), int | float):
        logger.warning(
            "LLM returned non-numeric amount: %s (full result: %s)",
            result.get("amount"),
            result,
        )
        return None

    return result
