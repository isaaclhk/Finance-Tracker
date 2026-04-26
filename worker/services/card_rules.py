import json
import logging
import re
from dataclasses import dataclass

from worker.config import CARD_RULES_JSON
from worker.services.account_config import resolve_account_hint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardRule:
    account: str
    issuer_banks: frozenset[str]
    issuer_patterns: tuple[re.Pattern[str], ...]
    source_patterns: tuple[re.Pattern[str], ...]
    payment_patterns: tuple[re.Pattern[str], ...]


_DEFAULT_CARD_RULES: tuple[dict, ...] = (
    {
        "account": "Trust Card",
        "account_hints": ("Trust", "Trust Card"),
        "issuer_banks": ("Trust",),
        "issuer_patterns": (r"\btrust\b", r"trustbank\.sg"),
        "source_patterns": (
            r"\btrust\s+link\b",
            r"\btrust\s+link\s+card\b",
            r"\btrust\s+card\b",
        ),
        "payment_patterns": (
            r"^\s*trust\s*$",
            r"\btrust\s+(?:bank|card|credit\s+card)\b",
        ),
    },
    {
        "account": "UOB Absolute Cashback Amex",
        "account_hints": (
            "UOB Absolute",
            "UOB Absolute Cashback Amex",
            "UOB Credit Card",
        ),
        "issuer_banks": ("UOB",),
        "issuer_patterns": (r"\buob\b", r"uobgroup\.com"),
        "source_patterns": (
            r"\buob\s+absolute\b",
            r"\babsolute\s+cashback\b",
            r"\buob\s+(?:credit\s+)?card\b",
            r"\buob\s+amex\b",
        ),
        "payment_patterns": (
            r"\buob\s+absolute\b",
            r"\babsolute\s+cashback\b",
            r"\buob\s+(?:credit\s+)?card\b",
            r"\buob\s+amex\b",
        ),
    },
)


def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def _rule_account(raw: dict) -> str:
    for hint in raw.get("account_hints", ()):
        account = resolve_account_hint(hint)
        if account:
            return account
    return resolve_account_hint(raw["account"]) or raw["account"]


def _build_rule(raw: dict) -> CardRule:
    return CardRule(
        account=_rule_account(raw),
        issuer_banks=frozenset(raw.get("issuer_banks", ())),
        issuer_patterns=_compile_patterns(tuple(raw.get("issuer_patterns", ()))),
        source_patterns=_compile_patterns(tuple(raw.get("source_patterns", ()))),
        payment_patterns=_compile_patterns(tuple(raw.get("payment_patterns", ()))),
    )


def _extra_rules() -> list[dict]:
    if not CARD_RULES_JSON:
        return []
    try:
        return json.loads(CARD_RULES_JSON)
    except json.JSONDecodeError:
        logger.error("Invalid CARD_RULES JSON in env var")
        return []


def load_card_rules(extra_rules: list[dict] | None = None) -> tuple[CardRule, ...]:
    configured_rules = extra_rules if extra_rules is not None else _extra_rules()
    raw_rules = [*_DEFAULT_CARD_RULES, *configured_rules]
    return tuple(_build_rule(rule) for rule in raw_rules)


CARD_RULES = load_card_rules()


def matches_any(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def resolve_card_source_account(hint: str | None) -> str | None:
    if not hint:
        return None
    for rule in CARD_RULES:
        if hint == rule.account or matches_any(rule.source_patterns, hint):
            return rule.account
    return None


def resolve_card_payment_account(hint: str | None) -> str | None:
    if not hint:
        return None
    for rule in CARD_RULES:
        if hint == rule.account or matches_any(rule.payment_patterns, hint):
            return rule.account
    return None
