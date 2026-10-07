"""撮影日時と集計日(ゲームの日替わり AM 5:00 区切り)の計算。"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

DAY_START_HOUR = 5  # この時刻より前の撮影は前日分として集計する
_FILENAME_RE = re.compile(r"^(\d{14})(?:_.*)?\.(?:jpe?g|png)$", re.IGNORECASE)


def business_date(captured_at: datetime) -> date:
    return (captured_at - timedelta(hours=DAY_START_HOUR)).date()


def parse_filename(name: str) -> datetime | None:
    """`YYYYMMDDhhmmss_*.jpg` の先頭14桁から撮影日時を取る。形式不一致・不正な日時は None。"""
    m = _FILENAME_RE.match(Path(name).name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def resolve_captured_at(name: str, last_modified_ms: int | None = None) -> tuple[datetime | None, str]:
    """撮影日時と、その出どころ("filename" / "mtime" / "unknown")を返す。"""
    parsed = parse_filename(name)
    if parsed:
        return parsed, "filename"
    if last_modified_ms is not None:
        return datetime.fromtimestamp(last_modified_ms / 1000), "mtime"
    return None, "unknown"
