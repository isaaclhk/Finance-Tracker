from datetime import date, datetime
from zoneinfo import ZoneInfo

SINGAPORE_TZ = ZoneInfo("Asia/Singapore")


def now_sgt() -> datetime:
    return datetime.now(SINGAPORE_TZ)


def today_sgt() -> date:
    return now_sgt().date()
