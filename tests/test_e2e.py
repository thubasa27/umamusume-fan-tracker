"""ブラウザ(ヘッドレス Chromium)で画面を通しで操作する E2E テスト。playwright が無ければスキップ。"""
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

pw = pytest.importorskip("playwright.sync_api")

from fantracker.api import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.05)
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
        pg.goto(server)
        yield pg
        assert errors == []
        browser.close()


def upload(page, *pairs):
    """(フィクスチャ名, アップロード時のファイル名) を取り込みタブから読み込む。"""
    files = [{"name": up, "mimeType": "image/jpeg", "buffer": (FIXTURES / src).read_bytes()} for src, up in pairs]
    page.set_input_files("#file-input", files)
    page.wait_for_function("document.querySelector('#scan-status').textContent.includes('件を読み取りました')")


def test_import_confirm_dashboard_records_flow(page):
    upload(page, ("sample_3.jpg", "20261005200000_1.jpg"), ("sample_2.jpg", "20261006200000_1.jpg"),
           ("sample_1.jpg", "20261008030000_1.jpg"))  # 3枚目は AM5:00 前なので 10/7 分
    page.wait_for_function("document.querySelectorAll('#scan-results .item').length === 3")
    values = [i.input_value() for i in page.locator("#scan-results .item input[type=text]").all()]
    assert values == ["2654906664", "2658611645", "2672583581"]
    assert "集計日 2026-10-07" in page.locator("#scan-results .item").nth(2).inner_text()
    assert page.locator("#scan-results .item img").first.is_visible()
    assert "null" not in page.locator("#scan-results").inner_text()

    page.click("#confirm-all")
    page.wait_for_function("document.querySelectorAll('#scan-results .ok').length === 3")

    # 同じ画像を再取り込みすると登録済み扱い
    upload(page, ("sample_1.jpg", "20261008030000_1.jpg"))
    assert "登録済み" in page.locator("#scan-results").inner_text()

    page.click("nav button[data-tab=dashboard]")
    page.wait_for_selector("#tbl-daily tbody tr")
    page.uncheck("#interpolate")
    page.select_option("#period", "all")
    page.wait_for_function("document.querySelectorAll('#tbl-daily tbody tr').length === 3")
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
    page.wait_for_function("document.querySelectorAll('#tbl-daily tbody tr').length === 4")
    assert "3日分の合計" in page.locator("#tbl-daily tbody tr").first.inner_text()
    page.check("#interpolate")
    page.wait_for_function("document.querySelectorAll('#tbl-daily tbody tr').length === 6")
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
    page.wait_for_function("document.querySelectorAll('#tbl-records tbody tr').length === 3")


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
        pg.wait_for_function("window.__saved.length === 1")
        saved = pg.evaluate("window.__saved[0]")
        assert saved["name"] == "fan_records.csv"
        assert base64.b64decode(saved["b64"]).startswith(b"\xef\xbb\xbfbusiness_date")
        assert "保存しました" in pg.inner_text("#toast")

        pg.click("nav button[data-tab=dashboard]")
        pg.wait_for_selector("#tbl-daily tbody tr")
        pg.click("button.dl[data-chart=chart-total]")
        pg.wait_for_function("window.__saved.length === 2")
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
