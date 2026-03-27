from datetime import date

from worker.bot.commands import _parse_period


def test_parse_period_today():
    result = _parse_period("")
    assert result is not None
    start, end, label = result
    assert start == date.today()
    assert end == date.today()
    assert label == "today"


def test_parse_period_today_explicit():
    result = _parse_period("today")
    assert result is not None
    assert result[2] == "today"


def test_parse_period_yesterday():
    result = _parse_period("yesterday")
    assert result is not None
    assert result[2] == "yesterday"


def test_parse_period_this_week():
    result = _parse_period("this week")
    assert result is not None
    start, end, label = result
    assert label == "this week"
    assert start.weekday() == 0
    assert end == date.today()


def test_parse_period_last_week():
    result = _parse_period("last week")
    assert result is not None
    start, end, label = result
    assert label == "last week"
    assert start.weekday() == 0
    assert (end - start).days == 6


def test_parse_period_this_month():
    result = _parse_period("this month")
    assert result is not None
    start, end, label = result
    assert label == "this month"
    assert start.day == 1
    assert start.month == date.today().month


def test_parse_period_last_month():
    result = _parse_period("last month")
    assert result is not None
    start, end, label = result
    assert label == "last month"
    assert start.day == 1
    today = date.today()
    expected_month = today.month - 1 if today.month > 1 else 12
    assert start.month == expected_month


def test_parse_period_this_year():
    result = _parse_period("this year")
    assert result is not None
    start, end, label = result
    assert label == "this year"
    assert start.month == 1
    assert start.day == 1
    assert end == date.today()


def test_parse_period_last_year():
    result = _parse_period("last year")
    assert result is not None
    start, end, label = result
    assert label == "last year"
    assert start.year == date.today().year - 1


def test_parse_period_last_n_days():
    result = _parse_period("last 7 days")
    assert result is not None
    start, end, label = result
    assert label == "last 7 days"
    assert end == date.today()


def test_parse_period_last_n_months():
    result = _parse_period("last 3 months")
    assert result is not None
    start, end, label = result
    assert label == "last 3 months"
    assert end == date.today()


def test_parse_period_past_n_weeks():
    result = _parse_period("past 2 weeks")
    assert result is not None
    assert result[2] == "last 2 weeks"


def test_parse_period_month_name():
    result = _parse_period("january")
    assert result is not None
    start, end, label = result
    assert start.month == 1
    assert start.day == 1


def test_parse_period_month_abbr():
    result = _parse_period("feb")
    assert result is not None
    assert result[0].month == 2


def test_parse_period_month_with_year():
    result = _parse_period("march 2025")
    assert result is not None
    start, end, label = result
    assert start == date(2025, 3, 1)
    assert end == date(2025, 3, 31)


def test_parse_period_unknown_returns_none():
    result = _parse_period("some random text")
    assert result is None
