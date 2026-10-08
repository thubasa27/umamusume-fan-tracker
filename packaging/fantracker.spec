# -*- mode: python ; coding: utf-8 -*-
# ポータブル版(onedir)。dist/FanTracker/ をフォルダごと配布する。データは exe と同じフォルダの data/ に作られる。
#   pyinstaller packaging/fantracker.spec --noconfirm
from pathlib import Path

root = Path(SPECPATH).parent
icon = root / "packaging" / "FanTracker.ico"

a = Analysis(
    [str(root / "packaging" / "run.py")],
    pathex=[str(root)],
    datas=[
        (str(root / "fantracker" / "static"), "fantracker/static"),
        (str(root / "fantracker" / "layout.json"), "fantracker"),
        (str(root / "fantracker" / "templates.npz"), "fantracker"),
    ],
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "multipart",
    ],
    excludes=["pytest", "playwright", "tkinter", "httpx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FanTracker",
    console=True,  # 停止用のウィンドウとして残す(最小化して使う)
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FanTracker")
