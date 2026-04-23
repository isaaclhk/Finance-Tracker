import json
import logging
import os

from worker.integrations import firefly_client
from worker.utils.time import today_sgt

logger = logging.getLogger(__name__)

SALARY_CONFIG_PATH = os.getenv("SALARY_CONFIG_PATH", "/app/data/salary_config.json")
DEFAULT_ACCOUNT = "UOB One Account"


def load_config() -> dict:
    try:
        with open(SALARY_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"salaries": [], "deposited": {}}


def save_config(config: dict):
    os.makedirs(os.path.dirname(SALARY_CONFIG_PATH), exist_ok=True)
    with open(SALARY_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def add_salary(name: str, amount: float, day: int) -> str:
    config = load_config()
    for s in config["salaries"]:
        if s["name"].lower() == name.lower():
            return f"Salary '{name}' already exists. Use /salary set to update."

    config["salaries"].append(
        {
            "name": name,
            "amount": amount,
            "account": DEFAULT_ACCOUNT,
            "day": day,
        }
    )
    save_config(config)
    return f"Added: {name} ${amount:,.2f} on day {day}"


def remove_salary(name: str) -> str:
    config = load_config()
    before = len(config["salaries"])
    config["salaries"] = [s for s in config["salaries"] if s["name"].lower() != name.lower()]
    if len(config["salaries"]) == before:
        return f"Salary '{name}' not found."
    config["deposited"].pop(name, None)
    save_config(config)
    return f"Removed: {name}"


def set_salary_amount(name: str, amount: float) -> str:
    config = load_config()
    for s in config["salaries"]:
        if s["name"].lower() == name.lower():
            old = s["amount"]
            s["amount"] = amount
            save_config(config)
            return f"Updated {name}: ${old:,.2f} → ${amount:,.2f}"
    return f"Salary '{name}' not found."


def get_salaries() -> list[dict]:
    config = load_config()
    return config.get("salaries", [])


def should_deposit_today(entry: dict, config: dict) -> bool:
    today = today_sgt()
    if today.day != entry["day"]:
        return False

    month_key = today.strftime("%Y-%m")
    deposited = config.get("deposited", {})
    return deposited.get(entry["name"]) != month_key


async def deposit_salary(entry: dict) -> str | None:
    payload = {
        "transactions": [
            {
                "type": "deposit",
                "date": today_sgt().isoformat(),
                "amount": str(entry["amount"]),
                "description": f"Salary: {entry['name']}",
                "source_name": "Salary",
                "destination_name": entry.get("account", DEFAULT_ACCOUNT),
            }
        ]
    }
    try:
        await firefly_client.create_transaction(payload)
        config = load_config()
        if "deposited" not in config:
            config["deposited"] = {}
        config["deposited"][entry["name"]] = today_sgt().strftime("%Y-%m")
        save_config(config)
        return f"{entry['name']}: ${entry['amount']:,.2f} → {entry.get('account', DEFAULT_ACCOUNT)}"
    except Exception:
        logger.exception("Failed to deposit salary for %s", entry["name"])
        return None


async def run_salary_check() -> list[str]:
    config = load_config()
    results = []
    for entry in config.get("salaries", []):
        if should_deposit_today(entry, config):
            result = await deposit_salary(entry)
            if result:
                results.append(result)
    return results
