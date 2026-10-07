"""読み取り値の異常検出(FR-6)。閾値は定数で、設定として差し替えられる。"""
from __future__ import annotations

from datetime import date
from statistics import median

HISTORY = 14       # 直近何件の日次増加量を基準にするか
MIN_HISTORY = 5    # 有効な増加量がこれ未満の間は外れ値判定をしない
OUTLIER_FACTOR = 3.0


def check(adopted: list[dict], business_date: date, fan_total: int) -> list[str]:
    """`adopted` は採用済み記録(business_date 昇順)。登録前の値に対する警告を返す。"""
    warnings: list[str] = []
    iso = business_date.isoformat()
    others = [r for r in adopted if r["business_date"] != iso]  # 同日の置き換え分は除外
    before = [r for r in others if r["business_date"] < iso]
    after = [r for r in others if r["business_date"] > iso]

    if before and fan_total < before[-1]["fan_total"]:
        warnings.append(f"前回記録({before[-1]['business_date']})より小さい値です")
    if after and fan_total > after[0]["fan_total"]:
        warnings.append(f"次の記録({after[0]['business_date']})より大きい値です")
    if warnings or not before:
        return warnings

    gap = (business_date - date.fromisoformat(before[-1]["business_date"])).days
    increment = (fan_total - before[-1]["fan_total"]) / gap

    rates = []
    for a, b in zip(before, before[1:]):
        days = (date.fromisoformat(b["business_date"]) - date.fromisoformat(a["business_date"])).days
        rates.append((b["fan_total"] - a["fan_total"]) / days)
    rates = rates[-HISTORY:]
    if len(rates) >= MIN_HISTORY and (m := median(rates)) > 0:
        if increment > m * OUTLIER_FACTOR or increment < m / OUTLIER_FACTOR:
            warnings.append(f"日次増加量が過去の中央値({m:,.0f}/日)から大きく外れています")
    if gap > 1:
        warnings.append(f"{gap - 1}日分の記録が欠けています(増加量は{gap}日分の合計)")
    return warnings
