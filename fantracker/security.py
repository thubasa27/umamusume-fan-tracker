"""ローカル API への、他サイトや他のユーザーからのアクセスを防ぐ。

想定する攻撃と対策:
1. 他サイトからの書き込み(CSRF): 悪意あるページから 127.0.0.1 へ POST を送る(マルチパートのフォーム送信などは、
   ブラウザの事前確認なしに送れる)。
   → GET/HEAD 以外は `X-FanTracker: 1` ヘッダー必須、Origin はこのサーバーと同じオリジンのみ、OPTIONS は拒否。CORS ヘッダーは付けない。
2. DNS リバインディング: 攻撃者のドメインが 127.0.0.1 を指すようにして、同一オリジンとして記録や画像を読み出す。
   → Host ヘッダーが許可リスト(127.0.0.1 / localhost)にないリクエストは、読み取りも含めて拒否。
3. 同じ PC の他のユーザーやプログラムからのアクセス(認証がないと、記録も画像も読み書きできてしまう)。
   → 起動ごとのランダムなトークン。起動時に開く URL(`/?t=<トークン>`)でだけ受け取り、Cookie(HttpOnly・SameSite=Strict)に入れて
     URL から消す(リダイレクト)。以降のリクエストは Cookie が一致しないと拒否する(`/api/health` だけは例外)。
   Cookie は「ポートを区別しない」ので、名前にポートを含めて、複数起動しても干渉しないようにする。
4. 他サイトの iframe への埋め込み(クリックジャッキング)や、スクリプトの注入。
   → CSP(`frame-ancestors 'none'`、`script-src 'self'` など)、X-Frame-Options、nosniff など、防御ヘッダーを全応答に付ける。
5. 巨大なリクエストによるメモリ消費。→ Content-Length の上限。
"""
from __future__ import annotations

import secrets
from collections.abc import Iterable
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost")
CSRF_HEADER = "x-fantracker"
SAFE_METHODS = {"GET", "HEAD"}
TOKEN_PARAM = "t"
PUBLIC_PATHS = {"/api/health"}  # 認証なしで返す(起動の確認用。何も返さない)
MAX_REQUEST_BYTES = 200 * 1024 * 1024  # 1 リクエストの上限(Content-Length)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

FORBIDDEN_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>ウマ娘 ファン数トラッカー</title>"
    "<p>この画面からは使えません。アプリを起動したときに開く画面(専用ウィンドウ、または自動で開くブラウザ)から使ってください。</p>"
)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _same(a: str, b: str) -> bool:
    """タイミング攻撃に強い比較。secrets.compare_digest は非 ASCII の str で例外になるため、バイト列で比べる。"""
    return secrets.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))


def _hostname(host_header: str) -> str:
    """Host ヘッダーからポートを除いたホスト名(小文字)。"""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def _port(host_header: str) -> str:
    host = host_header.strip().lower()
    tail = host.rsplit(":", 1)[1] if ":" in host and not host.endswith("]") else ""
    return tail if tail.isdigit() else "80"


def cookie_name(host_header: str) -> str:
    """Cookie はポートを区別しないので、名前にポートを含める(複数起動しても、互いのトークンを上書きしない)。"""
    return f"fantracker_{_port(host_header)}"


def install(app: FastAPI, token: str, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS) -> None:
    allowed = {h.lower() for h in allowed_hosts}

    def deny(request: Request, reason: str, status: int = 403) -> Response:
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(FORBIDDEN_PAGE, status_code=status)
        return JSONResponse({"detail": reason}, status_code=status)

    def authenticated(request: Request, host: str) -> bool:
        return _same(request.cookies.get(cookie_name(host), ""), token)

    async def check(request: Request, call_next) -> Response:
        host = request.headers.get("host", "")
        if _hostname(host) not in allowed:
            return deny(request, "許可されていない Host です")

        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JSONResponse({"detail": "リクエストが大きすぎます"}, status_code=413)

        if request.url.path in PUBLIC_PATHS and request.method in SAFE_METHODS:
            return await call_next(request)

        # 起動時に開く URL の ?t=<トークン> を Cookie に替え、URL から消す(履歴や Referer に残さない)
        given = request.query_params.get(TOKEN_PARAM)
        if given is not None and request.method == "GET":
            if not _same(given, token):
                return deny(request, "トークンが正しくありません")
            rest = [(k, v) for k, v in request.query_params.multi_items() if k != TOKEN_PARAM]
            target = request.url.path + (f"?{urlencode(rest)}" if rest else "")
            response = RedirectResponse(target, status_code=303)
            response.set_cookie(cookie_name(host), token, httponly=True, samesite="strict", path="/")
            return response

        if not authenticated(request, host):
            return deny(request, "認証されていません。アプリを起動したときに開く画面から使ってください")

        if request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != "1":
                return deny(request, "X-FanTracker ヘッダーが必要です")
            origin = request.headers.get("origin")
            if origin is not None:
                parts = urlsplit(origin)
                if parts.scheme != request.url.scheme or parts.netloc.lower() != host.strip().lower():
                    return deny(request, "別のオリジンからのリクエストは受け付けません")
        return await call_next(request)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        response = await check(request, call_next)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
