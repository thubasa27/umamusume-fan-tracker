"""ポータブル形式(データは実行ファイルと同じフォルダ)に関するテスト。"""
import json
import logging
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

from fantracker import __main__ as entry
from fantracker import ocr, paths
from fantracker.db import SCHEMA_VERSION, Store

REPO = Path(__file__).resolve().parent.parent


def test_app_dir_is_repo_root_in_development_and_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert paths.app_dir() == REPO
    assert paths.data_dir() == REPO / "data"


def test_app_dir_is_exe_folder_when_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "FanTracker" / "FanTracker.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.chdir(tmp_path)  # どこから起動しても exe のフォルダ
    assert paths.data_dir() == exe.parent / "data"


def test_layout_override_replaces_only_given_keys(tmp_path):
    base = ocr.load_layout(override=tmp_path / "none.json")
    override = tmp_path / "layout.json"
    override.write_text(json.dumps({"fan_total": {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}}), encoding="utf-8")
    merged = ocr.load_layout(override=override)
    assert merged["fan_total"] == {"x0": 0.1, "y0": 0.2, "x1": 0.3, "y1": 0.4}
    assert merged["_comment"] == base["_comment"]


def test_layout_override_with_broken_json_names_the_file(tmp_path):
    override = tmp_path / "layout.json"
    override.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="layout.json"):
        ocr.load_layout(override=override)


def test_new_db_gets_schema_version_and_old_unversioned_db_is_accepted(tmp_path):
    path = tmp_path / "a.db"
    Store.open(path).conn.close()
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    # v1.0.0 は版を持たない(user_version=0)。そのまま開ける
    sqlite3.connect(path).execute("PRAGMA user_version = 0").connection.commit()
    store = Store.open(path)
    assert store.list() == []


def test_db_from_newer_app_is_rejected(tmp_path):
    path = tmp_path / "b.db"
    Store.open(path).conn.close()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="新しいバージョン"):
        Store.open(path)


def test_pick_port_skips_busy_port():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert entry.pick_port("127.0.0.1", port, 5) != port


def test_check_writable_creates_folder_and_rejects_unwritable(tmp_path):
    target = tmp_path / "x" / "data"
    entry.check_writable(target)
    assert target.is_dir() and not (target / ".write_test").exists()
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(entry.StartupError, match="書き込めません"):
        entry.check_writable(blocker / "data")  # ファイルの下には作れない


def test_scan_warnings_are_written_to_log_file(tmp_path):
    import synthetic
    from helpers import make_client

    from fantracker.api import create_app

    entry.setup_logging(tmp_path)
    try:
        client = make_client(create_app(tmp_path))
        client.post("/api/scan", files=[("files", ("screenshot.jpg", synthetic.sample_bytes("sample_1.jpg"), "image/jpeg"))])
        for h in logging.getLogger().handlers:
            h.flush()
        text = (tmp_path / "logs" / "fantracker.log").read_text(encoding="utf-8")
        assert "読み取り警告 'screenshot.jpg'" in text and "撮影日時を特定できません" in text
    finally:
        logging.getLogger().handlers.clear()
