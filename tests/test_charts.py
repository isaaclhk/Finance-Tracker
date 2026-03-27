from datetime import date

from worker.bot.charts import (
    generate_category_pie,
    generate_daily_spending,
    generate_monthly_trend,
)


def _is_png(buf):
    return buf is not None and buf.read(4) == b"\x89PNG"


def test_category_pie_basic():
    cats = {"Food & Drink": 500, "Transport": 300, "Shopping": 200}
    buf = generate_category_pie(cats)
    assert _is_png(buf)


def test_category_pie_groups_small():
    cats = {"Food & Drink": 500, "Transport": 300, "Tiny": 1}
    buf = generate_category_pie(cats)
    assert _is_png(buf)


def test_category_pie_returns_none_single():
    assert generate_category_pie({"Food": 100}) is None


def test_category_pie_returns_none_empty():
    assert generate_category_pie({}) is None


def test_monthly_trend_basic():
    data = {"Jan 2026": 1200, "Feb 2026": 1500, "Mar 2026": 1100}
    buf = generate_monthly_trend(data)
    assert _is_png(buf)


def test_monthly_trend_returns_none_single():
    assert generate_monthly_trend({"Jan 2026": 1200}) is None


def test_monthly_trend_returns_none_empty():
    assert generate_monthly_trend({}) is None


def test_daily_spending_basic():
    data = {
        date(2026, 3, 25): 50.0,
        date(2026, 3, 26): 30.0,
        date(2026, 3, 27): 80.0,
    }
    buf = generate_daily_spending(data, "this week")
    assert _is_png(buf)


def test_daily_spending_returns_none_single():
    assert generate_daily_spending({date(2026, 3, 25): 50.0}, "today") is None


def test_daily_spending_returns_none_empty():
    assert generate_daily_spending({}, "today") is None
