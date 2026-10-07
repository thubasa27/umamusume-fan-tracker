from datetime import date

import pytest

from fantracker.summary import aggregate, build_series, filter_period


def rec(d, total):
    return {"business_date": d, "fan_total": total}


ADOPTED = [rec("2026-10-05", 1000), rec("2026-10-06", 1100), rec("2026-10-09", 1700)]  # 10/7,10/8 が欠損


def test_series_without_interpolation_marks_missing_days():
    s = build_series(ADOPTED)
    assert [x["date"] for x in s] == ["2026-10-05", "2026-10-06", "2026-10-09"]
    assert [x["increment"] for x in s] == [None, 100, 600]
    assert [x["days"] for x in s] == [None, 1, 3]  # 最後は3日分の合計


def test_series_with_interpolation_spreads_evenly():
    s = build_series(ADOPTED, interpolate=True)
    assert [x["date"] for x in s][-3:] == ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert [x["increment"] for x in s][-3:] == pytest.approx([200, 200, 200])
    assert [x["fan_total"] for x in s] == [1000, 1100, 1300, 1500, 1700]
    assert [x["interpolated"] for x in s] == [False, False, True, True, False]
    assert sum(x["increment"] for x in s[1:]) == pytest.approx(700)  # 補間しても合計は変わらない


def test_aggregate_weekly_and_monthly():
    s = build_series(ADOPTED)
    weekly = aggregate(s, "week")  # 10/5(月)始まりの1週
    assert weekly == [{"period": "2026-10-05", "sum": 700, "average_per_day": 700 / 4, "max": 600, "days": 4, "records": 2}]
    assert aggregate(s, "month")[0]["period"] == "2026-10"


def test_aggregate_with_interpolation_changes_max_and_average():
    w = aggregate(build_series(ADOPTED, interpolate=True), "week")[0]
    assert w["sum"] == pytest.approx(700) and w["max"] == pytest.approx(200) and w["days"] == 4
    assert w["average_per_day"] == pytest.approx(175)


def test_aggregate_splits_weeks_and_months():
    adopted = [rec("2026-09-29", 900), rec("2026-09-30", 1000), rec("2026-10-01", 1100), rec("2026-10-04", 1400), rec("2026-10-05", 1500)]
    weeks = aggregate(build_series(adopted), "week")
    assert [w["period"] for w in weeks] == ["2026-09-28", "2026-10-05"]  # 10/4(日) は前の週
    assert [m["period"] for m in aggregate(build_series(adopted), "month")] == ["2026-09", "2026-10"]


def test_filter_period_counts_calendar_days_from_latest():
    s = build_series([rec(f"2026-10-{d:02d}", 1000 + d) for d in range(1, 11)])
    assert len(filter_period(s, 7)) == 7 and filter_period(s, 7)[0]["date"] == "2026-10-04"
    assert filter_period(s, None) == s
    assert filter_period([], 7) == []


def test_single_record_has_no_increment():
    s = build_series([rec("2026-10-05", 1000)])
    assert s[0]["increment"] is None and aggregate(s, "week") == []
    assert date.fromisoformat(s[0]["date"])
