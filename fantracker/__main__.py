"""`python -m fantracker`(ポータブル版では FanTracker.exe)で起動する。

既定は専用ウィンドウ(pywebview)。使えない場合や `--browser` ではブラウザで開く。
`--no-ui` は画面を出さずにサーバーだけを起動する(ビルドの動作確認用)。
"""
import argparse
import logging
import logging.handlers
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, paths, window
from .api import create_app

HOST = "127.0.0.1"  # 外部に公開しない(ローカル専用)
PORT = 8000
PORT_TRIES = 20  # 8000 が使用中なら 8001, 8002, … を試す
START_TIMEOUT = 15  # サーバーが起動するまで待つ秒数

log = logging.getLogger("fantracker")


class StartupError(Exception):
    """起動できない理由(利用者に見せる文面)。"""


def pick_port(host: str = HOST, start: int | None = None, tries: int = PORT_TRIES) -> int:
    start = PORT if start is None else start
    for port in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"{start}〜{start + tries - 1} のポートがすべて使用中です")


def check_writable(data: Path) -> None:
    """データフォルダに書き込めることを確認する(読み取り専用の場所に置かれた場合に分かりやすく止める)。"""
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".write_test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        raise StartupError(
            f"データフォルダに書き込めません: {data}\n理由: {e}\n"
            "アプリのフォルダを、書き込める場所(例: ドキュメントやデスクトップ)に移してください。"
        ) from e


def setup_logging(data: Path) -> None:
    """data/logs/fantracker.log に記録する(コンソールがない起動でも残る)。"""
    log_dir = data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log_dir / "fantracker.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers, force=True)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # リクエストごとの行はファイルに残さない


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fantracker", description="ウマ娘 ファン数トラッカー")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--browser", action="store_true", help="専用ウィンドウではなくブラウザで開く")
    group.add_argument("--no-ui", action="store_true", help="画面を出さずにサーバーだけ起動する")
    return parser.parse_args(argv)


def _wait_until_stopped(server: uvicorn.Server, thread: threading.Thread) -> None:
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(10)


def _run(args: argparse.Namespace) -> None:
    data = paths.data_dir()
    check_writable(data)
    setup_logging(data)

    port = pick_port()
    url = f"http://{HOST}:{port}/"
    server: uvicorn.Server

    def request_shutdown() -> None:
        server.should_exit = True

    use_window = not args.browser and not args.no_ui and window.is_available()
    app = create_app(data, mode="window" if use_window else "browser", on_shutdown=request_shutdown)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.time() + START_TIMEOUT
    while not server.started:
        if not thread.is_alive() or time.time() > deadline:
            raise StartupError("サーバーを起動できませんでした。data\\logs\\fantracker.log を確認してください。")
        time.sleep(0.05)
    log.info("起動 v%s データ=%s %s 表示=%s", __version__, data, url, "ウィンドウ" if use_window else "ブラウザ" if not args.no_ui else "なし")
    print(f"ウマ娘 ファン数トラッカー v{__version__}\nデータの保存先: {data}\n{url}")

    if use_window:
        try:
            window.run_window(url, __version__)  # ウィンドウが閉じられるまで戻らない
            server.should_exit = True
            thread.join(10)
            return
        except Exception:  # noqa: BLE001 - WebView2 が無い等。ブラウザ表示に切り替える
            log.exception("専用ウィンドウを開けませんでした。ブラウザで開きます")
            app.state.mode = "browser"
    if not args.no_ui:
        webbrowser.open(url)
        print("停止は、画面の「終了」ボタン、または Ctrl+C です。")
    _wait_until_stopped(server, thread)


def main(argv: list[str] | None = None) -> None:
    try:
        _run(parse_args(argv))
    except StartupError as e:
        log.error("%s", e)
        window.show_error(str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - 想定外は、原因をログに残して利用者にも見せる
        log.exception("起動に失敗しました")
        window.show_error(f"起動に失敗しました。\n{type(e).__name__}: {e}\n\nログ: {paths.data_dir() / 'logs' / 'fantracker.log'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
