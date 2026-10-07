"""日次の増加量と、週次・月次の集計(FR-11〜14)。

増加量の扱い:
- 補間なし: 記録がある日ごとに「前の記録日からの増加量」を1エントリとして出す。
  欠損日があれば days>1 で、増加量は経過日数分の合計。
- 補間あり: 欠損日を含む全日に増加量を日割りし、ファン数も線形補間する。
  グラフと週次・月次の集計の両方がこの値になる。
"""
from __future__ import annotations

from datetime import date, timedelta


def _d(s: str) -> date:
    return date.fromisoformat(s)


def build_series(adopted: list[dict], interpolate: bool = False) -> list[dict]:
    """採用済み記録(日付昇順)から日次の系列を作る。

    各要素: date, fan_total, increment(最初の1件は None), days(増加量が何日分か), interpolated
    """
    series: list[dict] = []
    for i, rec in enumerate(adopted):
        day, total = _d(rec["business_date"]), rec["fan_total"]
        if i == 0:
            series.append({"date": day.isoformat(), "fan_total": total, "increment": None, "days": None,
                           "interpolated": False})
            continue
        prev = adopted[i - 1]
        prev_day, prev_total = _d(prev["business_date"]), prev["fan_total"]
        gap = (day - prev_day).days
        if not interpolate or gap == 1:
            series.append({"date": day.isoformat(), "fan_total": total, "increment": total - prev_total,
                           "days": gap, "interpolated": False})
            continue
        step = (total - prev_total) / gap
        for k in range(1, gap + 1):
            last = k == gap
            series.append({
                "date": (prev_day + timedelta(days=k)).isoformat(),
                "fan_total": total if last else round(prev_total + step * k),
                "increment": total - prev_total - step * (gap - 1) if last else step,
                "days": 1, "interpolated": not last,
            })
    return series


def filter_period(series: list[dict], days: int | None) -> list[dict]:
    """最新の日付から遡って `days` 日分(最新日を含む)。None なら全期間。"""
    if days is None or not series:
        return series
    cutoff = _d(series[-1]["date"]) - timedelta(days=days - 1)
    return [s for s in series if _d(s["date"]) >= cutoff]


def _period_key(day: date, kind: str) -> str:
    if kind == "week":
        monday = day - timedelta(days=day.weekday())
        return monday.isoformat()  # 月曜始まり。キーは週の月曜日
    return f"{day.year:04d}-{day.month:02d}"


def aggregate(series: list[dict], kind: str) -> list[dict]:
    """kind は "week" か "month"。合計・平均(1日あたり)・最大の増加量を返す。"""
    groups: dict[str, list[dict]] = {}
    for s in series:
        if s["increment"] is None:
            continue
        groups.setdefault(_period_key(_d(s["date"]), kind), []).append(s)
    out = []
    for key in sorted(groups):
        items = groups[key]
        total = sum(s["increment"] for s in items)
        days = sum(s["days"] for s in items)
        out.append({
            "period": key,
            "sum": total,
            "average_per_day": total / days,
            "max": max(s["increment"] for s in items),
            "days": days,
            "records": len(items),
        })
    return out
