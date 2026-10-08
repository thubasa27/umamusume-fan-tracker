from fastapi.testclient import TestClient


def make_client(app) -> TestClient:
    """ブラウザの画面と同じ条件のクライアント(Host は 127.0.0.1、書き込みには X-FanTracker ヘッダー)。"""
    return TestClient(app, base_url="http://127.0.0.1", headers={"X-FanTracker": "1"})
