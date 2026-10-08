"""専用ウィンドウ(pywebview。Windows では WebView2)で UI を表示する。

サーバーは別スレッドで動かし、メインスレッドでウィンドウを表示する(pywebview の制約)。
CSV と PNG の保存は、WebView2 のダウンロード挙動に頼らず、保存ダイアログを出す `save_file` を JS から呼ぶ。
"""
from __future__ import annotations

import base64
import binascii
import importlib.util
import logging
import sys
from pathlib import Path

log = logging.getLogger("fantracker")

TITLE = "ウマ娘 ファン数トラッカー"
SAVE_TYPES = {".png": "PNG 画像", ".csv": "CSV ファイル"}
MAX_SAVE_BYTES = 50 * 1024 * 1024


def is_available() -> bool:
    return importlib.util.find_spec("webview") is not None


class Api:
    """ページの JS から `window.pywebview.api.*` として呼ぶ。

    `_` で始まる属性は pywebview が公開しない(Window を公開しないために `_window` にしている)。
    """

    def __init__(self, webview_module) -> None:
        self._webview = webview_module
        self._window = None

    def save_file(self, name: str, data_base64: str) -> dict:
        """保存先を選ぶダイアログを出し、データを書き込む。戻り値: {"saved": bool, "path"?: str, "error"?: str}"""
        suffix = Path(str(name)).suffix.lower()
        if suffix not in SAVE_TYPES:
            return {"saved": False, "error": f"保存できないファイルの種類です: {suffix or '(なし)'}"}
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError, TypeError):
            return {"saved": False, "error": "データが不正です"}
        if len(data) > MAX_SAVE_BYTES:
            return {"saved": False, "error": "データが大きすぎます"}
        try:
            chosen = self._window.create_file_dialog(
                self._webview.FileDialog.SAVE,
                save_filename=Path(str(name)).name,
                file_types=(f"{SAVE_TYPES[suffix]} (*{suffix})",),
            )
            if isinstance(chosen, (list, tuple)):  # 版により、パスまたはその配列で返る
                chosen = chosen[0] if chosen else None
            if not chosen:
                return {"saved": False}  # キャンセル
            Path(chosen).write_bytes(data)
        except OSError as e:
            log.warning("保存に失敗しました: %s", e)
            return {"saved": False, "error": f"保存できませんでした: {e}"}
        log.info("保存しました: %s", chosen)
        return {"saved": True, "path": str(chosen)}


def run_window(url: str, version: str) -> None:
    """ウィンドウを表示し、閉じられるまで戻らない。WebView2 が使えない等の場合は例外を送出する。"""
    import webview

    api = Api(webview)
    api._window = webview.create_window(
        f"{TITLE} v{version}", url, js_api=api, width=1280, height=900, min_size=(900, 600),
        text_select=True,  # 表の数値をコピーできるように
        zoomable=True,
    )
    # Windows は WebView2 を指定する(未指定だと旧 IE エンジンに落ちて、画面が動かない)
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)


def show_error(message: str, title: str = TITLE) -> None:
    """コンソールのない exe でも見えるように、Windows ではメッセージボックスで表示する。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # MB_ICONERROR
            return
        except Exception:  # noqa: BLE001 - 表示手段が無いときは標準エラーへ
            pass
    if sys.stderr is not None:
        print(f"{title}: {message}", file=sys.stderr)
