import json
import logging

from worker.config import ACCOUNT_MAP_JSON

logger = logging.getLogger(__name__)

# Bank name fallbacks (always available)
_BANK_FALLBACKS: dict[str, str] = {
    "OCBC": "OCBC Child Savings Account",
    "UOB": "UOB One Account",
    "Trust": "Trust Card",
    "Syfe": "Syfe Cash",
}


def _load_account_map() -> dict[str, str]:
    custom: dict[str, str] = {}
    if ACCOUNT_MAP_JSON:
        try:
            custom = json.loads(ACCOUNT_MAP_JSON)
        except json.JSONDecodeError:
            logger.error("Invalid ACCOUNT_MAP JSON in env var")
    return {**_BANK_FALLBACKS, **custom}


ACCOUNT_MAP = _load_account_map()


def resolve_account_hint(hint: str | None) -> str | None:
    if not hint:
        return None
    if hint in ACCOUNT_MAP:
        return ACCOUNT_MAP[hint]
    if hint in ACCOUNT_MAP.values():
        return hint
    return None
