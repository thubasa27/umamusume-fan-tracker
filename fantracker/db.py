"""SQLite への記録保存。同じ集計日では撮影時刻が最新の記録を採用(adopted=1)する。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_date TEXT    NOT NULL,           -- YYYY-MM-DD(AM 5:00 区切りの集計日)
    captured_at   TEXT    NOT NULL,           -- ISO 8601 の撮影日時
    fan_total     INTEGER NOT NULL,
    filename      TEXT,
    image_hash    TEXT UNIQUE,                -- SHA-256。手動追加は NULL
    adopted       INTEGER NOT NULL DEFAULT 0, -- 集計日ごとに最新の1件だけ 1
    manual        INTEGER NOT NULL DEFAULT 0, -- 利用者が値や日付を手修正した/手動追加した
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_date ON records (business_date, captured_at);
"""
COLUMNS = "id, business_date, captured_at, fan_total, filename, image_hash, adopted, manual, created_at"


class DuplicateImage(Exception):
    def __init__(self, record_id: int):
        super().__init__(f"同じ画像が登録済みです (id={record_id})")
        self.record_id = record_id


@dataclass
class Store:
    conn: sqlite3.Connection

    @classmethod
    def open(cls, path: str | Path) -> "Store":
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return cls(conn)

    # --- 採用の再計算 -------------------------------------------------
    def _refresh_adopted(self, business_date: str) -> None:
        self.conn.execute("UPDATE records SET adopted = 0 WHERE business_date = ?", (business_date,))
        self.conn.execute(
            "UPDATE records SET adopted = 1 WHERE id = ("
            " SELECT id FROM records WHERE business_date = ?"
            " ORDER BY captured_at DESC, id DESC LIMIT 1)",
            (business_date,),
        )

    # --- 参照 ---------------------------------------------------------
    def get(self, record_id: int) -> dict | None:
        row = self.conn.execute(f"SELECT {COLUMNS} FROM records WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None

    def find_by_hash(self, image_hash: str) -> dict | None:
        row = self.conn.execute(f"SELECT {COLUMNS} FROM records WHERE image_hash = ?", (image_hash,)).fetchone()
        return dict(row) if row else None

    def list(self, include_history: bool = False) -> list[dict]:
        where = "" if include_history else "WHERE adopted = 1"
        rows = self.conn.execute(
            f"SELECT {COLUMNS} FROM records {where} ORDER BY business_date, captured_at, id"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- 更新 ---------------------------------------------------------
    def add(
        self,
        *,
        business_date: date,
        captured_at: datetime,
        fan_total: int,
        filename: str | None = None,
        image_hash: str | None = None,
        manual: bool = False,
    ) -> dict:
        if image_hash and (dup := self.find_by_hash(image_hash)):
            raise DuplicateImage(dup["id"])
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO records (business_date, captured_at, fan_total, filename, image_hash, manual, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    business_date.isoformat(), captured_at.isoformat(timespec="seconds"), fan_total,
                    filename, image_hash, int(manual), datetime.now().isoformat(timespec="seconds"),
                ),
            )
            self._refresh_adopted(business_date.isoformat())
        return self.get(cur.lastrowid)

    def update(self, record_id: int, **fields) -> dict | None:
        """fan_total / business_date / captured_at を変更する(変更したら manual=1)。"""
        current = self.get(record_id)
        if current is None:
            return None
        allowed = {"fan_total", "business_date", "captured_at"}
        sets = {}
        for k, v in fields.items():
            if k not in allowed or v is None:
                continue
            sets[k] = v.isoformat(timespec="seconds") if isinstance(v, datetime) else (
                v.isoformat() if isinstance(v, date) else v)
        if not sets:
            return current
        sets["manual"] = 1
        with self.conn:
            self.conn.execute(
                f"UPDATE records SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                (*sets.values(), record_id),
            )
            for d in {current["business_date"], sets.get("business_date", current["business_date"])}:
                self._refresh_adopted(d)
        return self.get(record_id)

    def delete(self, record_id: int) -> bool:
        current = self.get(record_id)
        if current is None:
            return False
        with self.conn:
            self.conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            self._refresh_adopted(current["business_date"])
        return True
