"""`python -m fantracker` でサーバーを起動し、ブラウザを開く。"""
import threading
import webbrowser

import uvicorn

from .api import create_app

HOST, PORT = "127.0.0.1", 8000  # 外部に公開しない(ローカル専用)


def main() -> None:
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}/")).start()
    uvicorn.run(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
