"""入力の上限と、CSV の数式インジェクション対策。"""
import csv
import io
import logging

import pytest
from helpers import make_client
from PIL import Image

from fantracker import __main__ as entry
from fantracker import csvio, limits
from fantracker.api import create_app


@pytest.fixture
def client(tmp_path):
    return make_client(create_app(tmp_path))


def png(width, height, mode="1", color=1):
    buf = io.BytesIO()
    Image.new(mode, (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def scan(client, *files):
    return client.post("/api/scan", files=[("files", (name, data, "image/png")) for name, data in files])


# ---- 画像 ----

def test_too_many_files_in_one_request_is_rejected(client):
    tiny = png(4, 4)
    r = scan(client, *[(f"{i}.png", tiny) for i in range(limits.MAX_SCAN_FILES + 1)])
    assert r.status_code == 413


def test_file_over_the_size_limit_is_rejected_without_failing_the_batch(client):
    ok = png(300, 100)
    r = scan(client, ("big.jpg", b"\xff\xd8" + b"0" * limits.MAX_IMAGE_BYTES), ("ok.png", ok))
    assert r.status_code == 200
    big, good = r.json()["results"]
    assert "大きすぎます" in big["error"] and "error" not in good


def test_image_over_the_pixel_limit_is_rejected_before_it_is_decoded(client, monkeypatch):
    # 8000x8000 = 6400 万画素(上限 5000 万)。1 ビットの PNG なのでファイルは小さい
    r = scan(client, ("huge.png", png(8000, 8000)))
    assert r.status_code == 200
    assert "画像が大きすぎます" in r.json()["results"][0]["error"]


def test_decompression_bomb_is_an_error_for_that_file_only(client):
    # PIL の解凍爆弾の上限(約 1.8 億画素)を超える 1.96 億画素。以前は 500 エラーで、一括取り込み全体が失敗した
    r = scan(client, ("bomb.png", png(14000, 14000)), ("ok.png", png(300, 100)))
    assert r.status_code == 200
    bomb, good = r.json()["results"]
    assert "error" in bomb and "error" not in good


def test_normal_screenshot_size_is_accepted(client):
    r = scan(client, ("20261007204638_1.png", png(1625, 914, "RGB", (255, 255, 255))))
    assert r.status_code == 200 and "error" not in r.json()["results"][0]


# ---- 記録の入力値 ----

def test_record_fields_are_validated(client):
    base = {"fan_total": 1000, "captured_at": "2026-10-07T12:00:00"}
    assert client.post("/api/records", json=base).status_code == 201
    for bad in (
        {"fan_total": limits.MAX_FAN_TOTAL + 1}, {"fan_total": 10**30}, {"fan_total": 0},
        {"filename": "a" * (limits.MAX_FILENAME + 1)}, {"image_hash": "../../etc/passwd"}, {"image_hash": "A" * 64},
        {"image_hash": "g" * 64}, {"image_hash": "a" * 63},
    ):
        assert client.post("/api/records", json={**base, **bad}).status_code == 422, bad
    assert client.patch("/api/records/1", json={"fan_total": 10**30}).status_code == 422


# ---- CSV ----

def post_csv(client, body, mode="report"):
    return client.post("/api/import/csv", files={"file": ("a.csv", body)}, data={"mode": mode})


def test_csv_over_the_size_limit_is_rejected(client):
    assert post_csv(client, b"x" * (limits.MAX_CSV_BYTES + 1)).status_code == 413


def test_csv_with_a_huge_cell_is_an_error_not_a_crash(client):
    r = post_csv(client, b"captured_at,fan_total\n" + b"x" * 1_000_000)
    assert r.status_code == 200 and r.json()["imported"] == 0 and "CSV として読み込めません" in r.json()["errors"][0]
    r = post_csv(client, b"captured_at,fan_total\n2026-10-05T20:00:00,1000\n2026-10-06T20:00:00," + b"9" * 300_000 + b"\n")
    assert r.status_code == 200 and r.json()["rows"] == 1 and r.json()["errors"]


def test_csv_row_limit(client, monkeypatch):
    monkeypatch.setattr(csvio, "MAX_CSV_ROWS", 50)
    body = "business_date,captured_at,fan_total\n" + "2026-10-05,2026-10-05T20:00:00,1000\n" * 80
    r = post_csv(client, body.encode()).json()
    assert r["rows"] == 50 and "行数が多すぎます" in r["errors"][-1]


def test_csv_rows_with_bad_values_are_reported_per_line(client):
    good = "a" * 64
    body = (
        "business_date,captured_at,fan_total,filename,image_hash\n"
        f"2026-10-01,2026-10-01T20:00:00,1000,ok.jpg,{good}\n"
        f"2026-10-02,2026-10-02T20:00:00,{limits.MAX_FAN_TOTAL + 1},ok.jpg,\n"
        f"2026-10-03,2026-10-03T20:00:00,1000,{'f' * 300}.jpg,\n"
        "2026-10-04,2026-10-04T20:00:00,1000,ok.jpg,../../etc/passwd\n"
        f"2026-10-05,2026-10-05T20:00:00,1000,ok.jpg,{good.upper()}\n"
    )
    r = post_csv(client, body.encode()).json()
    assert r["rows"] == 2 and len(r["errors"]) == 3  # 正常な 2 行(ハッシュは大文字でも受け付けて小文字にそろえる)
    assert [e.split(":")[0] for e in r["errors"]] == ["3行目", "4行目", "5行目"]


# ---- CSV の数式インジェクション ----

DANGEROUS = ['=HYPERLINK("http://evil.example/","x").jpg', "+1+1.jpg", "-2+3.jpg", "@SUM(1).jpg", "\t=1.jpg", "\r=1.jpg"]


@pytest.mark.parametrize("name", DANGEROUS)
def test_dangerous_text_cells_are_escaped_on_export_and_restored_on_import(client, name):
    assert client.post("/api/records", json={"fan_total": 1000, "captured_at": "2026-10-07T12:00:00", "filename": name}).status_code == 201
    raw = client.get("/api/export.csv").content.decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(raw)))
    assert row["filename"] == "'" + name and not row["filename"].startswith(csvio.FORMULA_PREFIXES)
    # 取り込み直すと、元のファイル名に戻る(往復で変わらない)
    other = make_client(create_app(client.app.state.store.conn.execute("PRAGMA database_list").fetchone()[2].rsplit("/", 1)[0] + "/other"))
    post_csv(other, raw.encode("utf-8-sig"), mode="skip")
    assert other.get("/api/records").json()[0]["filename"] == name


def test_numbers_and_ordinary_names_are_left_alone(client):
    for name in ("20261005200000_1.jpg", "'abc.jpg", "a=b.jpg", ""):
        client.post("/api/records", json={"fan_total": 1000 + len(name), "captured_at": f"2026-10-0{len(name) % 9 + 1}T12:00:00", "filename": name or None})
    rows = list(csv.DictReader(io.StringIO(client.get("/api/export.csv").content.decode("utf-8-sig"))))
    assert {r["filename"] for r in rows} == {"20261005200000_1.jpg", "'abc.jpg", "a=b.jpg", ""}
    assert all(r["fan_total"].isdigit() for r in rows)  # 数値の列には、' を付けない


def test_escape_helpers_are_inverse():
    for value in [*DANGEROUS, "plain", "'plain", "a=b", "", "'=x", "''=x", "'", "''", "'-"]:
        assert csvio.unescape_cell(csvio.escape_cell(value)) == value


# ---- ログ ----

def test_newlines_in_file_names_cannot_forge_log_lines(tmp_path):
    entry.setup_logging(tmp_path)
    try:
        c = make_client(create_app(tmp_path))
        c.post("/api/scan", files=[("files", ("evil.jpg\n2026-01-01 00:00:00,000 INFO fantracker: FORGED", b"not an image", "image/jpeg"))])
        for h in logging.getLogger().handlers:
            h.flush()
        text = (tmp_path / "logs" / "fantracker.log").read_text(encoding="utf-8")
        assert "FORGED" in text  # 内容は記録される
        assert not any(line.lstrip().startswith("2026-01-01") for line in text.splitlines())  # 偽の行にはならない
    finally:
        logging.getLogger().handlers.clear()
