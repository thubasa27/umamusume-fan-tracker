"""ポータブル形式のための場所の解決。データは実行ファイルと同じフォルダの `data/` に置く。"""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """アプリの置かれたフォルダ。exe(PyInstaller)なら exe のあるフォルダ、開発時はリポジトリ直下。

    カレントディレクトリには依存しない(どこから起動しても同じデータを使う)。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """SQLite・取り込んだ画像・ログ・設定の上書きを置くフォルダ。"""
    return app_dir() / "data"
