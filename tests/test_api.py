from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fantracker.api import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def scan(client, name, upload_name):
    with open(FIXTURES / name, "rb") as f:
        r = client.post("/api/scan", files=[("files", (upload_name, f, "image/jpeg"))])
    assert r.status_code == 200
    return r.json()["results"][0]


def confirm(client, item, **over):
    body = {"fan_total": item["value"], "captured_at": item["captured_at"], "filename": item["filename"],
            "image_hash": item["image_hash"], **over}
    return client.post("/api/records", json=body)


def test_scan_reads_value_and_date_from_filename(client):
    item = scan(client, "sample_1.jpg", "20261008043000_1.jpg")  # AM5:00 前なので 10/7 分
    assert item["value"] == 2_672_583_581
    assert item["date_source"] == "filename"
    assert item["business_date"] == "2026-10-07"
    assert "duplicate_of" not in item
    assert client.get(f"/api/images/{item['image_hash']}/crop").headers["content-type"] == "image/png"


def test_confirm_then_rescan_is_duplicate_and_cannot_register_twice(client):
    item = scan(client, "sample_1.jpg", "20261007204638_1.jpg")
    created = confirm(client, item)
    assert created.status_code == 201 and created.json()["adopted"] == 1
    assert scan(client, "sample_1.jpg", "20261007204638_1.jpg")["duplicate_of"] == created.json()["id"]
    assert confirm(client, item).status_code == 409
    assert len(client.get("/api/records", params={"include_history": True}).json()) == 1


def test_three_days_with_decrease_warning(client):
    names = [("sample_3.jpg", "20261005200000_1.jpg"), ("sample_2.jpg", "20261006200000_1.jpg"),
             ("sample_1.jpg", "20261007200000_1.jpg")]
    for sample, upload in names:
        assert confirm(client, scan(client, sample, upload)).status_code == 201
    assert [r["fan_total"] for r in client.get("/api/records").json()] == [2_654_906_664, 2_658_611_645, 2_672_583_581]
    # 前日より小さい値の画像を後日として取り込むと警告
    item = scan(client, "sample_3.jpg", "20261008200000_1.jpg")
    assert item["duplicate_of"]  # 同一画像なので重複、かつ…
    assert any("小さい" in w for w in item["warnings"])


def test_same_day_newer_capture_is_adopted_and_old_kept_as_history(client):
    newer = confirm(client, scan(client, "sample_2.jpg", "20261007230000_1.jpg")).json()
    older = confirm(client, scan(client, "sample_3.jpg", "20261007100000_1.jpg")).json()
    assert [r["id"] for r in client.get("/api/records").json()] == [newer["id"]]
    assert {r["id"] for r in client.get("/api/records", params={"include_history": True}).json()} == {newer["id"], older["id"]}


def test_unknown_date_requires_manual_input(client):
    item = scan(client, "sample_1.jpg", "screenshot.jpg")
    assert item["captured_at"] is None and any("撮影日時" in w for w in item["warnings"])
    created = confirm(client, item, captured_at="2026-10-07T12:00:00", manual=True)
    assert created.status_code == 201 and created.json()["manual"] == 1


def test_manual_add_patch_delete(client):
    r = client.post("/api/records", json={"fan_total": 1000, "captured_at": "2026-10-07T01:00:00"})
    rec = r.json()
    assert rec["business_date"] == "2026-10-06" and rec["manual"] == 1  # 5時前は前日
    patched = client.patch(f"/api/records/{rec['id']}", json={"captured_at": "2026-10-07T06:00:00"}).json()
    assert patched["business_date"] == "2026-10-07"
    assert client.delete(f"/api/records/{rec['id']}").status_code == 204
    assert client.delete(f"/api/records/{rec['id']}").status_code == 404


def test_invalid_upload_reports_error(client):
    r = client.post("/api/scan", files=[("files", ("a.jpg", b"not an image", "image/jpeg"))])
    assert "error" in r.json()["results"][0]


def test_confirm_with_unknown_hash_is_rejected(client):
    r = client.post("/api/records", json={"fan_total": 1, "captured_at": "2026-10-07T01:00:00", "image_hash": "deadbeef"})
    assert r.status_code == 422


def add_manual(client, d, total):
    r = client.post("/api/records", json={"fan_total": total, "captured_at": f"{d}T12:00:00"})
    assert r.status_code == 201
    return r.json()


def test_summary_endpoint_periods_and_interpolation(client):
    for d, t in [("2026-10-01", 1000), ("2026-10-02", 1100), ("2026-10-05", 1700)]:
        add_manual(client, d, t)
    full = client.get("/api/summary").json()
    assert [s["increment"] for s in full["series"]] == [None, 100, 600]
    assert [(w["period"], w["sum"]) for w in full["weekly"]] == [("2026-09-28", 100), ("2026-10-05", 600)]
    week = client.get("/api/summary", params={"period": "7"}).json()["series"]
    assert [s["date"] for s in week] == ["2026-10-01", "2026-10-02", "2026-10-05"]
    short = client.get("/api/summary", params={"period": "3"})
    assert short.status_code == 422
    interp = client.get("/api/summary", params={"interpolate": True}).json()
    assert len(interp["series"]) == 5 and interp["interpolate"] is True


def test_csv_export_matches_table_and_roundtrips(client, tmp_path):
    first = confirm(client, scan(client, "sample_3.jpg", "20261005200000_1.jpg")).json()
    confirm(client, scan(client, "sample_2.jpg", "20261006200000_1.jpg"))
    confirm(client, scan(client, "sample_1.jpg", "20261007100000_1.jpg"))
    confirm(client, scan(client, "sample_1.jpg", "20261007230000_1.jpg"), image_hash=None, manual=True)  # 同日の新しい手入力
    raw = client.get("/api/export.csv").content
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    import csv, io
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    adopted = [r for r in rows if r["adopted"] == "1"]
    table = client.get("/api/summary").json()["series"]
    assert [r["business_date"] for r in adopted] == [s["date"] for s in table]
    assert [int(r["fan_total"]) for r in adopted] == [s["fan_total"] for s in table]
    assert [r["daily_increase"] for r in adopted] == ["" if s["increment"] is None else str(s["increment"]) for s in table]
    assert len(rows) == 4 and first["business_date"] == "2026-10-05"

    # 別のデータ領域に取り込み直すと同じ記録になる
    other = TestClient(create_app(tmp_path / "other"))
    r = other.post("/api/import/csv", files={"file": ("x.csv", raw)}, data={"mode": "report"}).json()
    assert r["rows"] == 4 and r["errors"] == [] and r["conflict_dates"] == []
    r = other.post("/api/import/csv", files={"file": ("x.csv", raw)}, data={"mode": "skip"}).json()
    assert r["imported"] == 4
    assert other.get("/api/export.csv").content == raw


def test_csv_import_conflict_modes_and_errors(client):
    add_manual(client, "2026-10-05", 1000)
    csv_body = ("business_date,captured_at,fan_total\n2026-10-05,2026-10-05T20:00:00,2000\n"
                "2026-10-06,2026-10-06T20:00:00,3000\n,bad,1\n").encode("utf-8-sig")
    rep = client.post("/api/import/csv", files={"file": ("a.csv", csv_body)}).json()
    assert rep["conflict_dates"] == ["2026-10-05"] and len(rep["errors"]) == 1 and rep["imported"] == 0
    skip = client.post("/api/import/csv", files={"file": ("a.csv", csv_body)}, data={"mode": "skip"}).json()
    assert (skip["imported"], skip["skipped_conflicts"]) == (1, 1)
    assert [r["fan_total"] for r in client.get("/api/records").json()] == [1000, 3000]
    over = client.post("/api/import/csv", files={"file": ("a.csv", csv_body)}, data={"mode": "overwrite"}).json()
    assert over["imported"] == 2
    assert [r["fan_total"] for r in client.get("/api/records").json()] == [2000, 3000]
    missing = client.post("/api/import/csv", files={"file": ("a.csv", b"a,b\n1,2\n")}).json()
    assert "必須列" in missing["errors"][0]
    assert client.post("/api/import/csv", files={"file": ("a.csv", csv_body)}, data={"mode": "x"}).status_code == 422


def test_static_pages_are_served(client):
    html = client.get("/")
    assert html.status_code == 200 and "ファン数トラッカー" in html.text
    for path in ("/app.js", "/style.css", "/chart.umd.min.js"):
        assert client.get(path).status_code == 200
    assert client.get("/api/records").status_code == 200  # 静的配信が API を隠さない
