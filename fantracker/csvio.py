"""CSV の入出力(Excel で開ける UTF-8 BOM 付き)。"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from . import dates
from .limits import HASH_PATTERN, MAX_CSV_ROWS, MAX_FAN_TOTAL, MAX_FILENAME
from .summary import build_series

HASH_RE = re.compile(HASH_PATTERN)
# Excel などで開いたときに数式として実行されうる先頭文字(CSV インジェクション)。文字列の列は、先頭に ' を付けて無害にする
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

HEADER = ["business_date", "captured_at", "fan_total", "daily_increase", "filename", "image_hash", "adopted", "manual"]


def _is_dangerous(value: str) -> bool:
    """先頭の ' を除いた先頭が、数式として実行されうる文字か(' が付いた値も対象にして、往復で一意に戻せるようにする)。"""
    return value.lstrip("'").startswith(FORMULA_PREFIXES)


def escape_cell(value: str) -> str:
    """文字列のセルが数式として実行されないよう、危険な値には先頭に ' を 1 つ付ける。"""
    return "'" + value if _is_dangerous(value) else value


def unescape_cell(value: str) -> str:
    """escape_cell の逆。危険な値に付いた先頭の ' を 1 つ取り除く。"""
    return value[1:] if value.startswith("'") and _is_dangerous(value) else value


def export_csv(records: list[dict], adopted: list[dict]) -> str:
    """記録(履歴を含む)を CSV にする。daily_increase は採用記録だけ、画面の表と同じ値(補間なし)。"""
    inc = {s["date"]: s["increment"] for s in build_series(adopted)}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    for r in records:
        increase = inc.get(r["business_date"]) if r["adopted"] else None
        w.writerow([r["business_date"], r["captured_at"], r["fan_total"], "" if increase is None else increase,
                    escape_cell(r["filename"] or ""), escape_cell(r["image_hash"] or ""), r["adopted"], r["manual"]])
    return "﻿" + buf.getvalue()


def parse_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    """(行のリスト, エラーメッセージのリスト)。必須列は captured_at と fan_total(business_date は省略可)。"""
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    try:
        fieldnames = reader.fieldnames or []
    except csv.Error as e:
        return [], [f"CSV として読み込めません: {e}"]
    missing = {"captured_at", "fan_total"} - set(fieldnames)
    if missing:
        return [], [f"必須列がありません: {', '.join(sorted(missing))}"]
    rows, errors = [], []
    line = 1
    while True:
        line += 1
        try:
            row = next(reader, None)
        except csv.Error as e:  # 1 つのセルが大きすぎる、など
            errors.append(f"{line}行目: CSV として読み込めません({e})")
            break
        if row is None:
            break
        if len(rows) + len(errors) >= MAX_CSV_ROWS:
            errors.append(f"行数が多すぎます(上限 {MAX_CSV_ROWS:,} 行)。それ以降は読み込みません")
            break
        try:
            captured = datetime.fromisoformat(row["captured_at"].strip())
            total = int(row["fan_total"].strip().replace(",", ""))
            if total <= 0:
                raise ValueError("fan_total は正の整数")
            if total > MAX_FAN_TOTAL:
                raise ValueError("fan_total が大きすぎます")
            filename = unescape_cell((row.get("filename") or "").strip()) or None
            if filename and len(filename) > MAX_FILENAME:
                raise ValueError(f"filename が長すぎます(上限 {MAX_FILENAME} 文字)")
            image_hash = unescape_cell((row.get("image_hash") or "").strip().lower()) or None
            if image_hash and not HASH_RE.match(image_hash):
                raise ValueError("image_hash は 64 桁の 16 進数")
            bdate = (row.get("business_date") or "").strip()
            rows.append({
                "business_date": datetime.strptime(bdate, "%Y-%m-%d").date() if bdate else dates.business_date(captured),
                "captured_at": captured, "fan_total": total,
                "filename": filename,
                "image_hash": image_hash,
                "manual": (row.get("manual") or "").strip() == "1",
            })
        except (ValueError, AttributeError, OverflowError) as e:
            errors.append(f"{line}行目: {e}")
    return rows, errors
