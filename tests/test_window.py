"""専用ウィンドウ(pywebview)まわり。GUI は起動できないので、偽の webview で流れを確認する。"""
import base64
import inspect
import logging
import socket
import threading
import time
import types
from pathlib import Path

import httpx
import pytest

from fantracker import __main__ as entry
from fantracker import paths, window


class FakeWindow:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create_file_dialog(self, kind, **kw):
        self.calls.append((kind, kw))
        return self.answer


def make_api(answer):
    fake = types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=30))
    api = window.Api(fake)
    api._window = FakeWindow(answer)
    return api


def b64(data=b"hello"):
    return base64.b64encode(data).decode()


def test_save_file_writes_to_chosen_path(tmp_path):
    target = tmp_path / "out.csv"
    api = make_api((str(target),))  # 版により配列で返る
    res = api.save_file("fan_records.csv", b64(b"a,b\r\n"))
    assert res == {"saved": True, "path": str(target)}
    assert target.read_bytes() == b"a,b\r\n"
    kind, kw = api._window.calls[0]
    assert kind == 30 and kw["save_filename"] == "fan_records.csv" and "*.csv" in kw["file_types"][0]


def test_save_file_accepts_plain_string_path(tmp_path):
    target = tmp_path / "x.png"
    assert make_api(str(target)).save_file("x.png", b64())["saved"] is True


def test_save_file_cancel_writes_nothing(tmp_path):
    assert make_api(None).save_file("x.png", b64()) == {"saved": False}
    assert make_api(()).save_file("x.png", b64()) == {"saved": False}


def test_save_file_rejects_bad_input():
    api = make_api("ignored")
    assert "種類" in api.save_file("evil.exe", b64())["error"]
    assert "種類" in api.save_file("noext", b64())["error"]
    assert "不正" in api.save_file("a.png", "***not base64***")["error"]
    assert api._window.calls == []  # 拒否した場合はダイアログも出さない


def test_save_file_uses_only_the_file_name_from_the_page(tmp_path):
    api = make_api(str(tmp_path / "ok.png"))
    api.save_file("../../etc/ok.png", b64())
    assert api._window.calls[0][1]["save_filename"] == "ok.png"


def test_save_file_reports_write_errors(tmp_path):
    res = make_api(str(tmp_path / "no_such_dir" / "x.png")).save_file("x.png", b64())
    assert res["saved"] is False and "保存できませんでした" in res["error"]


def test_api_exposes_nothing_but_save_file():
    public = [n for n in dir(window.Api) if not n.startswith("_")]
    assert public == ["save_file"]
    assert not [n for n in vars(make_api(None)) if not n.startswith("_")]  # Window などを公開しない


def test_real_pywebview_has_the_api_we_use():
    """pywebview の版が変わって、使っている API が無くなったときに気づく。"""
    webview = pytest.importorskip("webview")
    assert webview.FileDialog.SAVE is not None
    create = inspect.signature(webview.create_window).parameters
    for name in ("js_api", "width", "height", "min_size", "text_select", "zoomable"):
        assert name in create, name
    assert "gui" in inspect.signature(webview.start).parameters
    assert "save_filename" in inspect.signature(webview.Window.create_file_dialog).parameters


# ---- 起動の流れ(実サーバー + 偽のウィンドウ) ----

@pytest.fixture
def launch(monkeypatch, tmp_path):
    """main() を別スレッドで動かす。返り値: (起動, 結果の dict)。"""
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(entry, "PORT", port)
    opened = []
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url))
    result = {"port": port, "opened": opened, "exit": None}
    threads = []

    def start(argv):
        def target():
            try:
                entry.main(argv)
                result["exit"] = 0
            except SystemExit as e:
                result["exit"] = e.code

        t = threading.Thread(target=target, daemon=True)
        t.start()
        threads.append(t)
        return t

    yield start, result
    logging.getLogger().handlers.clear()
    for t in threads:
        t.join(15)


def wait_http(port):
    for _ in range(100):
        try:
            return httpx.get(f"http://127.0.0.1:{port}/api/info", timeout=2).json()
        except httpx.HTTPError:
            time.sleep(0.1)
    raise AssertionError("サーバーが応答しません")


def test_browser_mode_has_shutdown_and_requires_header(launch):
    start, result = launch
    t = start(["--browser"])
    info = wait_http(result["port"])
    assert info["mode"] == "browser" and info["can_shutdown"] is True
    url = f"http://127.0.0.1:{result['port']}/api/shutdown"
    assert httpx.post(url).status_code == 403  # 他のサイトからの単純なリクエストでは止められない
    assert httpx.post(url, headers={"X-FanTracker": "1"}).json() == {"ok": True}
    t.join(15)
    assert not t.is_alive() and result["exit"] == 0
    assert result["opened"] == [f"http://127.0.0.1:{result['port']}/"]


def test_no_ui_opens_nothing(launch):
    start, result = launch
    t = start(["--no-ui"])
    wait_http(result["port"])
    httpx.post(f"http://127.0.0.1:{result['port']}/api/shutdown", headers={"X-FanTracker": "1"})
    t.join(15)
    assert result["opened"] == [] and result["exit"] == 0


def test_window_mode_runs_until_window_closes_then_stops_server(launch, monkeypatch):
    start, result = launch
    seen = {}

    def fake_run_window(url, version):
        seen["url"] = url
        seen["info"] = httpx.get(url + "api/info").json()
        seen["index"] = httpx.get(url).status_code

    monkeypatch.setattr(window, "is_available", lambda: True)
    monkeypatch.setattr(window, "run_window", fake_run_window)
    t = start([])
    t.join(15)
    assert not t.is_alive() and result["exit"] == 0
    assert seen["info"]["mode"] == "window" and seen["info"]["can_shutdown"] is False  # 閉じれば終了するので不要
    assert seen["index"] == 200 and result["opened"] == []
    with pytest.raises(httpx.HTTPError):  # ウィンドウを閉じたらサーバーも止まっている
        httpx.get(seen["url"] + "api/info", timeout=1)


def test_window_failure_falls_back_to_browser_with_quit_button(launch, monkeypatch):
    start, result = launch

    def broken(url, version):
        raise RuntimeError("WebView2 が見つかりません")

    monkeypatch.setattr(window, "is_available", lambda: True)
    monkeypatch.setattr(window, "run_window", broken)
    t = start([])
    deadline = time.time() + 15
    while not result["opened"] and time.time() < deadline:
        time.sleep(0.1)
    assert result["opened"], "ブラウザに切り替わっていない"
    info = wait_http(result["port"])
    assert info["mode"] == "browser" and info["can_shutdown"] is True
    httpx.post(f"http://127.0.0.1:{result['port']}/api/shutdown", headers={"X-FanTracker": "1"})
    t.join(15)
    assert result["exit"] == 0


def test_startup_error_is_shown_to_user_and_exits(launch, monkeypatch, tmp_path):
    start, result = launch
    shown = []
    monkeypatch.setattr(window, "show_error", lambda msg, *a: shown.append(msg))
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr(paths, "data_dir", lambda: blocker / "data")
    start([]).join(15)
    assert result["exit"] == 1 and "書き込めません" in shown[0]


def test_unexpected_error_is_shown_with_log_path(launch, monkeypatch):
    start, result = launch
    shown = []
    monkeypatch.setattr(window, "show_error", lambda msg, *a: shown.append(msg))
    monkeypatch.setattr(entry, "create_app", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("壊れたデータ")))
    start(["--no-ui"]).join(15)
    assert result["exit"] == 1 and "壊れたデータ" in shown[0] and "fantracker.log" in shown[0]


def test_parse_args_flags_are_exclusive():
    assert entry.parse_args([]).browser is False
    assert entry.parse_args(["--browser"]).browser is True
    assert entry.parse_args(["--no-ui"]).no_ui is True
    with pytest.raises(SystemExit):
        entry.parse_args(["--browser", "--no-ui"])
