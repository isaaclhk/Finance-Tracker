import logging

from worker.integrations import openai_client

logger = logging.getLogger(__name__)


async def parse_and_categorize(email_body: str, sender: str) -> dict | None:
    result = await openai_client.parse_and_categorize(email_body, sender)
    if result is None:
        logger.warning("LLM failed to parse email from %s", sender)
        return None

    logger.info("LLM parse result for %s: %s", sender, result)

    if not isinstance(result.get("amount"), int | float):
        logger.warning(
            "LLM returned non-numeric amount: %s (full result: %s)",
            result.get("amount"),
            result,
        )
        return None

    return result
