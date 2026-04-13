def get_suggested_category(firefly_txn: dict, llm_suggestion: str | None) -> str | None:
    """Return the best category suggestion (Firefly rule match or LLM), or None."""
    attrs = firefly_txn.get("attributes", {})
    transactions = attrs.get("transactions", [])
    if transactions:
        existing = transactions[0].get("category_name")
        if existing:
            return existing
    return llm_suggestion
