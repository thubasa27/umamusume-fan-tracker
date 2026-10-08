from fastapi.testclient import TestClient

from fantracker import security


def make_client(app, host: str = "127.0.0.1") -> TestClient:
    """ブラウザの画面と同じ条件のクライアント(Host は 127.0.0.1、認証の Cookie、書き込みには X-FanTracker ヘッダー)。"""
    client = TestClient(app, base_url=f"http://{host}", headers={"X-FanTracker": "1"})
    client.cookies.set(security.cookie_name(host), app.state.token)
    return client
