"""他サイトからのローカル API へのアクセス対策(fantracker/security.py)。"""
from pathlib import Path

import pytest
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from helpers import make_client

from fantracker import security
from fantracker.api import create_app

FIXTURES = Path(__file__).parent / "fixtures"
CSV = "business_date,captured_at,fan_total\n2026-10-05,2026-10-05T20:00:00,1000\n".encode("utf-8-sig")


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return make_client(app)


def raw(app, base_url="http://127.0.0.1:8000", headers=None, auth=True):
    """既定ではヘッダーなし・認証の Cookie あり。auth=False は、Cookie もない(他のユーザーや他サイトから)。"""
    c = TestClient(app, base_url=base_url, headers=headers or {})
    if auth:
        c.cookies.set(security.cookie_name(urlsplit(base_url).netloc), app.state.token)
    return c


# ---- Host の許可リスト(DNS リバインディング対策) ----

@pytest.mark.parametrize("base", ["http://127.0.0.1:8000", "http://localhost:8000", "http://LOCALHOST", "http://127.0.0.1"])
def test_loopback_hosts_are_allowed(app, base):
    assert raw(app, base).get("/api/records").status_code == 200


@pytest.mark.parametrize("base", [
    "http://evil.example", "http://evil.example:8000", "http://127.0.0.1.evil.example:8000",
    "http://localhost.evil.example", "http://192.168.0.5:8000", "http://testserver",
])
def test_other_hosts_are_rejected_even_for_reads(app, base):
    c = raw(app, base)
    for path in ("/api/records", "/api/export.csv", "/api/summary", "/api/info", "/"):
        assert c.get(path).status_code == 403, path


def test_host_allowlist_is_configurable(tmp_path):
    app = create_app(tmp_path, allowed_hosts=["testserver"])
    assert raw(app, "http://testserver").get("/api/records").status_code == 200
    assert raw(app, "http://127.0.0.1").get("/api/records").status_code == 403


# ---- 書き込みにはカスタムヘッダー必須(CSRF 対策) ----

def writes(c):
    """書き込み系のリクエストをすべて送って、ステータスの一覧を返す。"""
    img = (FIXTURES / "sample_1.jpg").read_bytes()
    return {
        "scan": c.post("/api/scan", files=[("files", ("20261007204638_1.jpg", img, "image/jpeg"))]).status_code,
        "create": c.post("/api/records", json={"fan_total": 1000, "captured_at": "2026-10-07T12:00:00"}).status_code,
        "patch": c.patch("/api/records/1", json={"fan_total": 2000}).status_code,
        "delete": c.delete("/api/records/1").status_code,
        "csv": c.post("/api/import/csv", files={"file": ("a.csv", CSV)}, data={"mode": "overwrite"}).status_code,
        "shutdown": c.post("/api/shutdown").status_code,
    }


def test_all_writes_are_rejected_without_header(app):
    assert set(writes(raw(app)).values()) == {403}  # Cookie があっても、ヘッダーがなければ拒否


def test_header_alone_is_not_enough_from_another_origin(app):
    c = raw(app, headers={"X-FanTracker": "1", "Origin": "https://evil.example"})  # Cookie もヘッダーもあっても、別オリジンなら拒否
    assert set(writes(c).values()) == {403}


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1:9999", "http://localhost:8000", "https://127.0.0.1:8000"])
def test_origin_must_match_host_exactly(app, origin):
    c = raw(app, headers={"X-FanTracker": "1", "Origin": origin})
    assert c.post("/api/records", json={"fan_total": 1, "captured_at": "2026-10-07T12:00:00"}).status_code == 403


def test_same_origin_write_is_accepted(app):
    c = raw(app, headers={"X-FanTracker": "1", "Origin": "http://127.0.0.1:8000"})
    assert c.post("/api/records", json={"fan_total": 1000, "captured_at": "2026-10-07T12:00:00"}).status_code == 201


def test_form_post_like_cross_site_attack_cannot_change_data(app, client):
    """text/plain や multipart のフォーム送信(ヘッダーを付けられない)では、何も書き込めない。"""
    c = raw(app, headers={"Origin": "https://evil.example"}, auth=False)
    assert c.post("/api/records", content='{"fan_total": 1, "captured_at": "2026-10-07T12:00:00"}',
                  headers={"Content-Type": "text/plain"}).status_code == 403
    assert c.post("/api/import/csv", files={"file": ("a.csv", CSV)}, data={"mode": "overwrite"}).status_code == 403
    assert client.get("/api/records", params={"include_history": True}).json() == []


def test_preflight_is_denied_and_no_cors_headers_are_ever_sent(app, client):
    pre = raw(app).options("/api/records", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-fantracker"})
    assert pre.status_code == 403 and "access-control-allow-origin" not in pre.headers
    ok = client.get("/api/records", headers={"Origin": "https://evil.example"})
    assert ok.status_code == 200 and "access-control-allow-origin" not in ok.headers


def test_reads_do_not_need_the_header(app):
    c = raw(app)
    assert c.get("/api/records").status_code == 200 and c.get("/").status_code == 200
