"""ブラウザ(ヘッドレス Chromium)で画面を通しで操作する E2E テスト。playwright が無ければスキップ。"""
import socket
import threading
import time
from pathlib import Path

import pytest
import synthetic
import uvicorn

pw = pytest.importorskip("playwright.sync_api")

from fantracker import security  # noqa: E402
from fantracker.api import create_app  # noqa: E402



TOKENS = {}  # サーバーの URL → 認証トークン(画面は、トークン付きの URL を開いて Cookie を受け取る)


def serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
    TOKENS[f"http://127.0.0.1:{port}"] = app.state.token
    yield f"http://127.0.0.1:{port}", srv
    srv.should_exit = True
    t.join(5)


@pytest.fixture
def server(tmp_path):
    for url, _ in serve(create_app(tmp_path)):
        yield url


@pytest.fixture
def server_with_quit(tmp_path):
    box = {}
    app = create_app(tmp_path, mode="browser", on_shutdown=lambda: setattr(box["srv"], "should_exit", True))
    for url, srv in serve(app):
        box["srv"] = srv
        yield url, srv


@pytest.fixture
def page(server):
    yield from open_page(server)


def wait_js(pg, expression, timeout=10):
    """式が真になるまで、Python 側から繰り返し評価する。
    page.wait_for_function は文字列を eval で評価するため、unsafe-eval を許可しない CSP(アプリの防御ヘッダー)に止められる。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pg.evaluate(expression):
            return
        time.sleep(0.05)
    raise AssertionError(f"条件を満たしませんでした: {expression}")


def open_url(server):
    """アプリが最初に開く URL(トークン付き。開くと Cookie に替わり、URL から消える)。"""
    return f"{server}/?t={TOKENS[server]}"


def open_page(server, init_script=None):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # ブラウザ未インストール
            pytest.skip(f"chromium を起動できません: {e}")
        pg = browser.new_page(accept_downloads=True)
        if init_script:
            pg.add_init_script(init_script)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        # 防御ヘッダー(CSP)でアプリ自体が壊れていないこと: 違反はコンソールのエラーとして報告される
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(open_url(server))
        assert "t=" not in pg.url  # トークンは URL から消えている
        yield pg
        assert errors == []
        browser.close()


def upload(page, *pairs):
    """(フィクスチャ名, アップロード時のファイル名) を取り込みタブから読み込む。"""
    files = [{"name": up, "mimeType": "image/jpeg", "buffer": synthetic.sample_bytes(src)} for src, up in pairs]
    page.set_input_files("#file-input", files)
    wait_js(page, "document.querySelector('#scan-status').textContent.includes('件を読み取りました')")


def test_import_confirm_dashboard_records_flow(page):
    upload(page, ("sample_3.jpg", "20261005200000_1.jpg"), ("sample_2.jpg", "20261006200000_1.jpg"),
           ("sample_1.jpg", "20261008030000_1.jpg"))  # 3枚目は AM5:00 前なので 10/7 分
    wait_js(page, "document.querySelectorAll('#scan-results .item').length === 3")
    values = [i.input_value() for i in page.locator("#scan-results .item input[type=text]").all()]
    assert values == ["2654906664", "2658611645", "2672583581"]
    assert "集計日 2026-10-07" in page.locator("#scan-results .item").nth(2).inner_text()
    assert page.locator("#scan-results .item img").first.is_visible()
    assert "null" not in page.locator("#scan-results").inner_text()

    page.click("#confirm-all")
    wait_js(page, "document.querySelectorAll('#scan-results .ok').length === 3")

    # 同じ画像を再取り込みすると登録済み扱い
    upload(page, ("sample_1.jpg", "20261008030000_1.jpg"))
    assert "登録済み" in page.locator("#scan-results").inner_text()

    page.click("nav button[data-tab=dashboard]")
    page.wait_for_selector("#tbl-daily tbody tr")
    page.uncheck("#interpolate")
    page.select_option("#period", "all")
    wait_js(page, "document.querySelectorAll('#tbl-daily tbody tr').length === 3")
    rows = page.locator("#tbl-daily tbody tr").all_inner_texts()
    assert len(rows) == 3 and "2,672,583,581" in rows[0]
    assert "2日分の合計" not in "".join(rows)  # 10/5, 10/6, 10/7 は連続
    assert page.locator("#tbl-weekly tbody tr").count() == 1

    # PNG ダウンロード
    with page.expect_download() as d:
        page.click("button.dl[data-chart=chart-total]")
    assert d.value.suggested_filename == "fan_total.png"
    assert Path(d.value.path()).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # 欠損日の注記と補間
    page.click("nav button[data-tab=records]")
    page.fill("#manual-form input[name=fan_total]", "2680000000")
    page.fill("#manual-form input[name=captured_at]", "2026-10-10T12:00")
    page.click("#manual-form button")
    page.wait_for_selector("#manual-msg.ok")
    page.click("nav button[data-tab=dashboard]")
    page.uncheck("#interpolate")
    wait_js(page, "document.querySelectorAll('#tbl-daily tbody tr').length === 4")
    assert "3日分の合計" in page.locator("#tbl-daily tbody tr").first.inner_text()
    page.check("#interpolate")
    wait_js(page, "document.querySelectorAll('#tbl-daily tbody tr').length === 6")
    assert page.locator("#tbl-daily tbody tr", has_text="補間").count() == 2

    # 記録一覧: 編集と削除
    page.click("nav button[data-tab=records]")
    page.wait_for_selector("#tbl-records tbody tr")
    assert page.locator("#tbl-records tbody tr").count() == 4
    page.locator("#tbl-records tbody tr").last.get_by_text("編集").click()
    page.locator("#tbl-records tbody tr input[type=text]").fill("2681000000")
    page.get_by_text("保存").click()
    page.wait_for_selector("#tbl-records td:has-text('2,681,000,000')")
    assert "○" in page.locator("#tbl-records tbody tr").last.inner_text()  # 手修正フラグ
    page.on("dialog", lambda dlg: dlg.accept())
    page.locator("#tbl-records tbody tr").last.get_by_text("削除").click()
    wait_js(page, "document.querySelectorAll('#tbl-records tbody tr').length === 3")


def test_csv_import_panel_flow(page, tmp_path):
    csv = tmp_path / "in.csv"
    csv.write_bytes("business_date,captured_at,fan_total\n2026-10-05,2026-10-05T20:00:00,1000\n".encode("utf-8-sig"))
    page.click("nav button[data-tab=records]")
    page.set_input_files("#csv-input", str(csv))
    page.get_by_text("取り込む", exact=True).click()
    page.wait_for_selector("#csv-panel .ok")
    page.wait_for_selector("#tbl-records td:has-text('1,000')")
    # 再度同じ日を取り込むと重複を報告
    page.set_input_files("#csv-input", str(csv))
    page.wait_for_selector("#csv-panel :text('重複: 2026-10-05')")
    page.get_by_text("重複は上書き").click()
    page.wait_for_selector("#csv-panel .ok")


def test_empty_dashboard_message(page):
    page.click("nav button[data-tab=dashboard]")
    page.wait_for_selector("#dash-empty:not([hidden])")


def test_dashboard_defaults_to_30_days_with_interpolation(page):
    page.click("nav button[data-tab=dashboard]")
    assert page.input_value("#period") == "30"
    assert page.is_checked("#interpolate")


# 専用ウィンドウ(pywebview)では window.pywebview.api.save_file が使える。偽の実装を差し込んで保存の流れを確認する
FAKE_PYWEBVIEW = """
window.__saved = [];
window.pywebview = { api: { save_file: async (name, b64) => { window.__saved.push({name, b64}); return {saved: true, path: 'C:\\\\out\\\\' + name}; } } };
"""


def test_native_save_for_csv_and_chart_png(server):
    import base64

    for pg in open_page(server, FAKE_PYWEBVIEW):
        pg.click("nav button[data-tab=records]")
        pg.fill("#manual-form input[name=fan_total]", "2600000000")
        pg.fill("#manual-form input[name=captured_at]", "2026-10-07T12:00")
        pg.click("#manual-form button")
        pg.wait_for_selector("#manual-msg.ok")

        pg.click("#export-link")  # ダウンロードではなく保存ダイアログ経由になる
        wait_js(pg, "window.__saved.length === 1")
        saved = pg.evaluate("window.__saved[0]")
        assert saved["name"] == "fan_records.csv"
        assert base64.b64decode(saved["b64"]).startswith(b"\xef\xbb\xbfbusiness_date")
        assert "保存しました" in pg.inner_text("#toast")

        pg.click("nav button[data-tab=dashboard]")
        pg.wait_for_selector("#tbl-daily tbody tr")
        pg.click("button.dl[data-chart=chart-total]")
        wait_js(pg, "window.__saved.length === 2")
        png = pg.evaluate("window.__saved[1]")
        assert png["name"] == "fan_total.png" and base64.b64decode(png["b64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_quit_button_is_hidden_without_shutdown_callback(page):
    page.wait_for_load_state("networkidle")
    assert page.is_hidden("#quit")  # 専用ウィンドウなど、終了を受け付けない場合は出さない


def test_quit_button_stops_the_app_in_browser_mode(server_with_quit):
    url, srv = server_with_quit
    for pg in open_page(url):
        pg.wait_for_selector("#quit:not([hidden])")
        pg.once("dialog", lambda d: d.accept())
        pg.click("#quit")
        pg.wait_for_selector("text=終了しました")
    deadline = time.time() + 5
    while not srv.should_exit and time.time() < deadline:
        time.sleep(0.05)
    assert srv.should_exit


# ---- 他サイトからの攻撃を、実ブラウザで再現する ----

def attack_page(server, extra_args=None):
    """被害者のブラウザ(アプリを開いて、認証の Cookie を持っている)のページ。`evil.test` を 127.0.0.1 に向けて DNS リバインディングも再現する。"""
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--host-resolver-rules=MAP evil.test 127.0.0.1"] + (extra_args or []))
        except Exception as e:
            pytest.skip(f"chromium を起動できません: {e}")
        pg = browser.new_page()
        pg.goto(open_url(server))  # 被害者はアプリを開いていて、127.0.0.1 の Cookie を持っている
        yield pg
        browser.close()


@pytest.fixture
def attacker_site():
    """別オリジンの「攻撃者のサイト」(`evil.test:<ポート>` として、ブラウザからだけ見える)。"""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><body>attacker</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://evil.test:{httpd.server_address[1]}/"
    httpd.shutdown()


ATTACK_JS = """async (url) => {
  const result = {};
  const fd = new FormData();
  fd.append("file", new Blob(["business_date,captured_at,fan_total\\n2026-10-05,2026-10-05T20:00:00,1\\n"]), "a.csv");
  fd.append("mode", "overwrite");
  // 1) マルチパートのフォーム送信(プリフライトなしの単純リクエスト)で CSV を上書き取り込み
  try { await fetch(url + "/api/import/csv", { method: "POST", body: fd, mode: "no-cors" }); } catch (e) { result.csv = String(e); }
  // 2) text/plain の JSON(これも単純リクエスト)で記録を追加
  try { await fetch(url + "/api/records", { method: "POST", mode: "no-cors", headers: {"Content-Type": "text/plain"},
                                           body: '{"fan_total":1,"captured_at":"2026-10-05T20:00:00"}' }); } catch (e) { result.text = String(e); }
  // 3) カスタムヘッダー付き(プリフライトが必要。CORS を許可していないので失敗する)
  try { await fetch(url + "/api/records", { method: "POST", headers: {"X-FanTracker": "1", "Content-Type": "application/json"},
                                           body: '{"fan_total":1,"captured_at":"2026-10-05T20:00:00"}' }); } catch (e) { result.header = String(e); }
  return result;
}"""


def test_cross_site_form_post_cannot_write_in_real_browser(server, attacker_site):
    import json
    import urllib.request

    port = server.rsplit(":", 1)[1]

    for pg in attack_page(server):
        pg.goto(attacker_site)  # 別オリジン(evil.test)のページから、アプリ(127.0.0.1)へ送る
        assert pg.evaluate("location.origin") != server
        result = pg.evaluate(ATTACK_JS, server)
        assert "header" in result  # カスタムヘッダー付きは、ブラウザ側(プリフライト)で止まる
    req = urllib.request.Request(f"{server}/api/records?include_history=true",
                                 headers={"Cookie": f"{security.cookie_name('127.0.0.1:' + port)}={TOKENS[server]}"})
    with urllib.request.urlopen(req) as r:
        assert json.load(r) == []  # 何も書き込まれていない


def test_dns_rebinding_cannot_read_data_in_real_browser(server):
    port = server.rsplit(":", 1)[1]
    import urllib.request
    req = urllib.request.Request(f"{server}/api/records", data=b'{"fan_total": 123456, "captured_at": "2026-10-05T20:00:00"}',
                                 headers={"Content-Type": "application/json", "X-FanTracker": "1",
                                          "Cookie": f"{security.cookie_name('127.0.0.1:' + port)}={TOKENS[server]}"}, method="POST")
    urllib.request.urlopen(req).read()  # 正規の記録を1件入れておく
    for pg in attack_page(server):
        # evil.test が 127.0.0.1 を指す(DNS リバインディング)。同一オリジンになるので、ブラウザ側の制限は効かない
        resp = pg.goto(f"http://evil.test:{port}/api/records")
        assert resp.status == 403
        assert "123456" not in pg.content()
        status = pg.evaluate("async (u) => (await fetch(u + '/api/export.csv')).status", f"http://evil.test:{port}")
        assert status == 403
        # 正規のアドレスなら、同じページから読める(対策が正規の利用を妨げない)
        assert pg.goto(f"http://127.0.0.1:{port}/api/records").status == 200


def test_browser_without_the_token_cannot_use_the_app(server):
    """トークンを知らないブラウザ(同じ PC の別のユーザーなど)は、画面も API も使えない。"""
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium を起動できません: {e}")
        pg = browser.new_page()
        resp = pg.goto(server + "/")
        assert resp.status == 403 and "起動したとき" in pg.inner_text("body")
        assert pg.evaluate("async () => (await fetch('/api/records')).status") == 403
        assert pg.evaluate("async () => (await fetch('/api/health')).status") == 200  # 起動の確認用だけは認証なし
        pg.goto(f"{server}/?t=wrong-token")
        assert "403" in str(pg.evaluate("async () => (await fetch('/api/records')).status"))
        # 正しいトークンを渡すと使える
        assert pg.goto(open_url(server)).status == 200
        assert pg.evaluate("async () => (await fetch('/api/records')).status") == 200
        browser.close()


def test_page_cannot_be_framed_by_another_site(server, attacker_site):
    """クリックジャッキング対策(frame-ancestors / X-Frame-Options)。

    認証が要る画面は、SameSite=Strict の Cookie が iframe には送られないので、そもそも表示されない。防御ヘッダーだけを確かめるため、
    認証なしで応答する /api/health を iframe に入れて、ブラウザが表示を拒否することを確認する。"""
    port = server.rsplit(":", 1)[1]
    for pg in attack_page(server):
        pg.goto(attacker_site)
        pg.evaluate(
            """(url) => new Promise((resolve) => {
              const f = document.createElement("iframe");
              f.src = url;
              f.onload = () => resolve(true);
              document.body.append(f);
              setTimeout(() => resolve(false), 5000);
            })""",
            f"http://127.0.0.1:{port}/api/health",
        )
        frames = [f for f in pg.frames if f != pg.main_frame]
        assert frames, "iframe が作られていない"
        assert '"ok"' not in frames[0].content()  # 表示を拒否されている(拒否されなければ {"ok":true} が表示される)
