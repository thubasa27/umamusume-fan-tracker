"""`python -m fantracker`(ポータブル版では FanTracker.exe)でサーバーを起動し、ブラウザを開く。"""
import logging
import logging.handlers
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, paths
from .api import create_app

HOST = "127.0.0.1"  # 外部に公開しない(ローカル専用)
PORT = 8000
PORT_TRIES = 20  # 8000 が使用中なら 8001, 8002, … を試す


def pick_port(host: str = HOST, start: int = PORT, tries: int = PORT_TRIES) -> int:
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
        sys.exit(
            f"データフォルダに書き込めません: {data}\n理由: {e}\n"
            "アプリのフォルダを、書き込める場所(例: ドキュメントやデスクトップ)に移してください。"
        )


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


def main() -> None:
    data = paths.data_dir()
    check_writable(data)
    setup_logging(data)
    port = pick_port()
    url = f"http://{HOST}:{port}/"
    logging.getLogger("fantracker").info("起動 v%s データ=%s %s", __version__, data, url)
    print(f"ウマ娘 ファン数トラッカー v{__version__}\nデータの保存先: {data}\n{url} を開きます(停止は Ctrl+C またはこのウィンドウを閉じる)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(data), host=HOST, port=port, log_config=None)


if __name__ == "__main__":
    main()
