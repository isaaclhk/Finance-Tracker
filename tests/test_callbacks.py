from worker.bot.callbacks import CATEGORY_CODES, CODE_BY_NAME


def test_category_codes_complete():
    assert len(CATEGORY_CODES) == 10
    assert "FD" in CATEGORY_CODES
    assert CATEGORY_CODES["FD"] == "Food & Drink"
    assert CATEGORY_CODES["TR"] == "Transport"


def test_reverse_lookup():
    assert CODE_BY_NAME["Food & Drink"] == "FD"
    assert CODE_BY_NAME["Transport"] == "TR"
    assert CODE_BY_NAME["Groceries"] == "GR"


def test_all_categories_have_codes():
    from worker.integrations.openai_client import CATEGORIES

    for cat in CATEGORIES:
        assert cat in CODE_BY_NAME, f"Missing code for category: {cat}"
