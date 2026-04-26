from worker.services.card_rules import (
    load_card_rules,
    matches_any,
    resolve_card_payment_account,
    resolve_card_source_account,
)


def test_default_card_source_aliases():
    assert resolve_card_source_account("Trust Link Card") == "Trust Card"
    assert resolve_card_source_account("UOB Absolute") == "UOB Absolute Cashback Amex"


def test_default_card_payment_aliases():
    assert resolve_card_payment_account("Trust Bank") == "Trust Card"
    assert resolve_card_payment_account("UOB Credit Card") == "UOB Absolute Cashback Amex"


def test_payment_alias_does_not_become_source_alias():
    assert resolve_card_source_account("Trust Bank") is None


def test_loads_extra_card_rule_shape():
    rules = load_card_rules(
        [
            {
                "account": "Example Card",
                "issuer_banks": ("Example",),
                "issuer_patterns": (r"examplebank\.com",),
                "source_patterns": (r"example\s+card",),
                "payment_patterns": (r"example\s+card\s+payment",),
            }
        ]
    )
    rule = rules[-1]

    assert rule.account == "Example Card"
    assert "Example" in rule.issuer_banks
    assert matches_any(rule.source_patterns, "paid with example card")
    assert matches_any(rule.payment_patterns, "example card payment")
