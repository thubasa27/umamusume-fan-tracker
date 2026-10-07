"""CSV の入出力(Excel で開ける UTF-8 BOM 付き)。"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from . import dates
from .summary import build_series

HEADER = ["business_date", "captured_at", "fan_total", "daily_increase", "filename", "image_hash", "adopted", "manual"]


def export_csv(records: list[dict], adopted: list[dict]) -> str:
    """記録(履歴を含む)を CSV にする。daily_increase は採用記録だけ、画面の表と同じ値(補間なし)。"""
    inc = {s["date"]: s["increment"] for s in build_series(adopted)}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    for r in records:
        increase = inc.get(r["business_date"]) if r["adopted"] else None
        w.writerow([r["business_date"], r["captured_at"], r["fan_total"], "" if increase is None else increase,
                    r["filename"] or "", r["image_hash"] or "", r["adopted"], r["manual"]])
    return "﻿" + buf.getvalue()


def parse_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    """(行のリスト, エラーメッセージのリスト)。必須列は captured_at と fan_total(business_date は省略可)。"""
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"captured_at", "fan_total"} - set(reader.fieldnames or [])
    if missing:
        return [], [f"必須列がありません: {', '.join(sorted(missing))}"]
    rows, errors = [], []
    for line, row in enumerate(reader, start=2):
        try:
            captured = datetime.fromisoformat(row["captured_at"].strip())
            total = int(row["fan_total"].strip().replace(",", ""))
            if total <= 0:
                raise ValueError("fan_total は正の整数")
            bdate = row.get("business_date", "").strip()
            rows.append({
                "business_date": datetime.strptime(bdate, "%Y-%m-%d").date() if bdate else dates.business_date(captured),
                "captured_at": captured, "fan_total": total,
                "filename": (row.get("filename") or "").strip() or None,
                "image_hash": (row.get("image_hash") or "").strip() or None,
                "manual": (row.get("manual") or "").strip() == "1",
            })
        except (ValueError, AttributeError) as e:
            errors.append(f"{line}行目: {e}")
    return rows, errors
