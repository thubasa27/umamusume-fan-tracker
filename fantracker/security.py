"""ローカル API への、他サイトからのアクセスを防ぐ。

想定する攻撃:
1. CSRF: 悪意あるページから `127.0.0.1` へ POST を送る。マルチパートのフォーム送信などは、
   ブラウザの事前確認(プリフライト)なしに送れるため、CSV の取り込み(上書き)で記録が書き換わりうる。
2. DNS リバインディング: 攻撃者のドメインが 127.0.0.1 を指すようにして、同一オリジンとして記録や画像を読み出す。

対策:
- Host ヘッダーが許可リスト(127.0.0.1 / localhost)にないリクエストは、読み取りも含めて拒否する(2 への対策)。
- 書き込み系(GET/HEAD 以外)は、カスタムヘッダー `X-FanTracker: 1` を必須にする。他のオリジンからカスタムヘッダー付きで
  送るにはプリフライトが要るが、CORS を許可していないので失敗する(1 への対策)。OPTIONS も拒否する。
- Origin ヘッダーがあれば、このサーバーと同じオリジン(スキーム・ホスト・ポートが一致)であることを確認する("null" も拒否)。
CORS ヘッダーは付けない(他のオリジンからは、応答を読めない)。
"""
from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost")
CSRF_HEADER = "x-fantracker"
SAFE_METHODS = {"GET", "HEAD"}


def _hostname(host_header: str) -> str:
    """Host ヘッダーからポートを除いたホスト名(小文字)。"""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def install(app: FastAPI, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS) -> None:
    allowed = {h.lower() for h in allowed_hosts}

    def deny(reason: str) -> JSONResponse:
        return JSONResponse({"detail": reason}, status_code=403)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if _hostname(host) not in allowed:
            return deny("許可されていない Host です")
        if request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != "1":
                return deny("X-FanTracker ヘッダーが必要です")
            origin = request.headers.get("origin")
            if origin is not None:
                parts = urlsplit(origin)
                if parts.scheme != request.url.scheme or parts.netloc.lower() != host.strip().lower():
                    return deny("別のオリジンからのリクエストは受け付けません")
        return await call_next(request)
