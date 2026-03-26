import logging
from dataclasses import dataclass

from worker.integrations import firefly_client
from worker.parsers import llm_email_parser
from worker.parsers.statement_parser import extract_transactions_from_pdf
from worker.parsers.validator import validate_parsed_transaction
from worker.services.account_mapper import map_to_firefly_account
from worker.services.transaction_processor import _build_firefly_payload
from worker.utils.dedup import is_duplicate

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    new_count: int = 0
    duplicates_skipped: int = 0
    errors: int = 0


async def reconcile_statement(pdf_bytes: bytes, sender: str) -> ReconcileResult:
    result = ReconcileResult()

    chunks = extract_transactions_from_pdf(pdf_bytes)
    if not chunks:
        logger.warning("No text extracted from PDF statement")
        return result

    for chunk in chunks:
        try:
            parsed = await llm_email_parser.parse_and_categorize(chunk, sender)
            if parsed is None:
                result.errors += 1
                continue

            validated, _ = validate_parsed_transaction(parsed)
            if validated is None:
                result.errors += 1
                continue

            source_account = map_to_firefly_account(validated)
            if source_account is None:
                result.errors += 1
                continue

            if await is_duplicate(validated):
                result.duplicates_skipped += 1
                continue

            payload = _build_firefly_payload(validated, source_account)
            await firefly_client.create_transaction(payload)
            result.new_count += 1

        except Exception:
            logger.exception("Failed to reconcile transaction from statement")
            result.errors += 1

    return result
