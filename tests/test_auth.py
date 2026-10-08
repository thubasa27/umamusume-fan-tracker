"""起動ごとのトークン認証と、防御ヘッダー(fantracker/security.py)。"""
import httpx
import pytest
from fastapi.testclient import TestClient

from fantracker import security
from fantracker.api import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path)


def anon(app, base="http://127.0.0.1:8000", **kw):
    """Cookie を持たないクライアント(他のユーザーのプログラムや、トークンを知らないブラウザ)。"""
    return TestClient(app, base_url=base, follow_redirects=False, **kw)


COOKIE = security.cookie_name("127.0.0.1:8000")


def test_requests_without_the_token_are_rejected_everywhere(app):
    c = anon(app)
    for path in ("/api/records", "/api/export.csv", "/api/summary", "/api/info", "/", "/app.js", "/api/images/" + "a" * 64 + "/crop"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/records", json={"fan_total": 1, "captured_at": "2026-10-07T12:00:00"}, headers={"X-FanTracker": "1"}).status_code == 403


def test_html_navigation_gets_a_friendly_page_and_api_gets_json(app):
    page = anon(app).get("/", headers={"Accept": "text/html"})
    assert page.status_code == 403 and "text/html" in page.headers["content-type"] and "起動したとき" in page.text
    api = anon(app).get("/api/records", headers={"Accept": "application/json"})
    assert api.status_code == 403 and "detail" in api.json()


def test_health_needs_no_token_but_still_checks_host(app):
    assert anon(app).get("/api/health").json() == {"ok": True}
    assert anon(app, "http://evil.example").get("/api/health").status_code == 403
    assert anon(app).post("/api/health", headers={"X-FanTracker": "1"}).status_code in (403, 405)


def test_token_in_url_becomes_a_cookie_and_is_removed_from_the_url(app):
    c = anon(app)
    r = c.get(f"/?t={app.state.token}")
    assert r.status_code == 303 and r.headers["location"] == "/"  # URL からトークンが消える
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={app.state.token}")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()  # ブラウザを閉じれば消える(保存しない)
    follow = c.get("/", cookies={COOKIE: app.state.token})
    assert follow.status_code == 200 and "ファン数トラッカー" in follow.text


def test_other_query_parameters_survive_the_redirect(app):
    r = anon(app).get(f"/api/records?include_history=true&t={app.state.token}")
    assert r.status_code == 303 and r.headers["location"] == "/api/records?include_history=true"


def test_wrong_or_odd_tokens_are_rejected_without_a_cookie(app):
    c = anon(app)
    for bad in ("", "x", app.state.token[:-1], app.state.token + "x", "あ", "%00", "t" * 5000):  # "あ" は非 ASCII(500 にならない)
        r = c.get("/", params={"t": bad})
        assert r.status_code == 403 and "set-cookie" not in r.headers, bad
    assert anon(app).get("/", cookies={COOKIE: "wrong"}).status_code == 403


def test_token_in_the_url_is_ignored_for_writes(app):
    r = anon(app).post(f"/api/records?t={app.state.token}", json={"fan_total": 1, "captured_at": "2026-10-07T12:00:00"},
                       headers={"X-FanTracker": "1"})
    assert r.status_code == 403


def test_cookie_is_per_port_and_per_launch(app, tmp_path):
    assert security.cookie_name("127.0.0.1:8000") != security.cookie_name("127.0.0.1:8001")
    assert security.cookie_name("localhost") == "fantracker_80"
    # 別のポートの Cookie では認証されない(複数起動しても、互いのトークンを上書きしない)
    c = anon(app, "http://127.0.0.1:8000")
    assert c.get("/api/records", cookies={security.cookie_name("127.0.0.1:8001"): app.state.token}).status_code == 403
    # 別の起動のトークンでは認証されない
    other = create_app(tmp_path / "other")
    assert other.state.token != app.state.token
    assert c.get("/api/records", cookies={COOKIE: other.state.token}).status_code == 403
    assert c.get("/api/records", cookies={COOKIE: app.state.token}).status_code == 200


def test_default_token_is_long_and_random(app, tmp_path):
    assert len(app.state.token) >= 40
    assert len({create_app(tmp_path / str(i)).state.token for i in range(5)}) == 5


def test_explicit_token_is_used(tmp_path):
    assert create_app(tmp_path, token="fixed-token").state.token == "fixed-token"


# ---- 防御ヘッダー ----

REQUIRED = {"x-frame-options": "DENY", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
            "cross-origin-opener-policy": "same-origin", "cross-origin-resource-policy": "same-origin"}


def test_security_headers_are_on_every_kind_of_response(app):
    ok = TestClient(app, base_url="http://127.0.0.1:8000", cookies={COOKIE: app.state.token}, follow_redirects=False)
    responses = {
        "html": ok.get("/"), "js": ok.get("/app.js"), "api": ok.get("/api/records"), "404": ok.get("/api/nothing"),
        "forbidden": anon(app).get("/api/records"), "health": anon(app).get("/api/health"),
        "redirect": anon(app).get(f"/?t={app.state.token}"), "bad host": anon(app, "http://evil.example").get("/"),
        "preflight": anon(app).options("/api/records"),
    }
    for name, r in responses.items():
        for header, value in REQUIRED.items():
            assert r.headers.get(header) == value, (name, header)
        assert "content-security-policy" in r.headers, name
        assert "access-control-allow-origin" not in r.headers, name


def test_csp_blocks_framing_and_inline_script(app):
    csp = anon(app).get("/api/health").headers["content-security-policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
    assert directives["frame-ancestors"] == ["'none'"] and directives["object-src"] == ["'none'"]
    assert directives["default-src"] == ["'none'"] and directives["base-uri"] == ["'none'"]
    assert directives["script-src"] == ["'self'"] and directives["style-src"] == ["'self'"]
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp and "http" not in csp


def test_api_is_not_cached_but_static_files_may_be(app):
    ok = TestClient(app, base_url="http://127.0.0.1:8000", cookies={COOKIE: app.state.token})
    assert ok.get("/api/records").headers["cache-control"] == "no-store"
    assert ok.get("/api/health").headers["cache-control"] == "no-store"
    assert "cache-control" not in ok.get("/app.js").headers


def test_oversized_request_is_rejected_before_it_is_read(app):
    ok = TestClient(app, base_url="http://127.0.0.1:8000", cookies={COOKIE: app.state.token}, headers={"X-FanTracker": "1"})
    r = ok.post("/api/scan", content=b"", headers={"Content-Length": str(security.MAX_REQUEST_BYTES + 1)})
    assert r.status_code == 413
    assert httpx.codes.is_error(r.status_code)
