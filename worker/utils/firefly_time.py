from datetime import datetime


def parse_firefly_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def time_matches(stored_dt: datetime, expected_hhmm: str | None) -> bool:
    if not expected_hhmm:
        return False

    try:
        hh, mm = expected_hhmm.split(":")
        expected = stored_dt.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, AttributeError):
        return False

    stored = stored_dt.replace(second=0, microsecond=0)
    return abs((stored - expected).total_seconds()) <= 60


def has_time_component(value: datetime) -> bool:
    return bool(value.hour or value.minute or value.second)
