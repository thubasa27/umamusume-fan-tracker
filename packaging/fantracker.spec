# -*- mode: python ; coding: utf-8 -*-
# ポータブル版(onedir)。dist/FanTracker/ をフォルダごと配布する。データは exe と同じフォルダの data/ に作られる。
#   pyinstaller packaging/fantracker.spec --noconfirm
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
icon = root / "packaging" / "FanTracker.ico"

datas = [
    (str(root / "fantracker" / "static"), "fantracker/static"),
    (str(root / "fantracker" / "layout.json"), "fantracker"),
    (str(root / "fantracker" / "templates.npz"), "fantracker"),
]
binaries = []
hiddenimports = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "multipart",
]
# 専用ウィンドウ(pywebview + WebView2)。Windows でビルドするときに入っている。無ければブラウザ表示のみになる
for pkg in ("webview", "clr_loader", "pythonnet"):
    if importlib.util.find_spec(pkg):
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
hiddenimports.append("clr")

a = Analysis(
    [str(root / "packaging" / "run.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "playwright", "tkinter", "httpx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FanTracker",
    console=False,  # コンソールなし。起動エラーはメッセージボックス、ログは data/logs に出る
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FanTracker")
