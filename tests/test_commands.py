from datetime import date

from worker.bot.commands import _parse_period


def test_parse_period_today():
    start, end, label = _parse_period([])
    assert start == date.today()
    assert end == date.today()
    assert label == "today"


def test_parse_period_today_explicit():
    start, end, label = _parse_period(["today"])
    assert label == "today"


def test_parse_period_this_week():
    start, end, label = _parse_period(["this", "week"])
    assert label == "this week"
    assert start.weekday() == 0  # Monday
    assert end == date.today()


def test_parse_period_this_month():
    start, end, label = _parse_period(["this", "month"])
    assert label == "this month"
    assert start.day == 1
    assert start.month == date.today().month


def test_parse_period_last_month():
    start, end, label = _parse_period(["last", "month"])
    assert label == "last month"
    assert start.day == 1
    today = date.today()
    expected_month = today.month - 1 if today.month > 1 else 12
    assert start.month == expected_month
