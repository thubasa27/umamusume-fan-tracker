from datetime import date

from fantracker.anomaly import check


def series(start_total, increments, start=date(2026, 10, 1)):
    rows, total = [], start_total
    for i, inc in enumerate([0] + increments):
        total += inc
        rows.append({"business_date": date.fromordinal(start.toordinal() + i).isoformat(), "fan_total": total})
    return rows


def test_decrease_is_flagged():
    rows = series(1000, [100])
    assert any("小さい" in w for w in check(rows, date(2026, 10, 3), 1050))


def test_normal_increase_has_no_warning():
    rows = series(1000, [100] * 6)
    assert check(rows, date(2026, 10, 8), rows[-1]["fan_total"] + 100) == []


def test_outlier_needs_enough_history():
    short = series(1000, [100] * 3)
    assert check(short, date(2026, 10, 5), short[-1]["fan_total"] + 10_000) == []
    enough = series(1000, [100] * 6)
    assert any("外れて" in w for w in check(enough, date(2026, 10, 8), enough[-1]["fan_total"] + 10_000))
    assert any("外れて" in w for w in check(enough, date(2026, 10, 8), enough[-1]["fan_total"] + 10))


def test_missing_days_are_noted_and_rate_uses_per_day():
    rows = series(1000, [100] * 6)
    ws = check(rows, date(2026, 10, 9), rows[-1]["fan_total"] + 200)  # 2日で+200 = 100/日
    assert ws == ["1日分の記録が欠けています(増加量は2日分の合計)"]


def test_replacing_same_day_ignores_itself():
    rows = series(1000, [100] * 6)
    assert check(rows, date(2026, 10, 7), rows[-1]["fan_total"]) == []
