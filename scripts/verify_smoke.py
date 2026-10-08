"""実サーバーを一時データで起動し、HTTP 経由で主要な流れを自動確認する(OS 非依存)。

    python scripts/verify_smoke.py

画面の見た目(日本語フォント、Excel での CSV 表示など)は確認できないので、目視確認は別途行う。
"""
from __future__ import annotations

import csv
import io
import logging
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fantracker import security  # noqa: E402
from fantracker.api import create_app  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
# (フィクスチャ, アップロード名, 期待値, 期待する集計日)
SAMPLES = [
    ("sample_3.jpg", "20261005200000_1.jpg", 2_654_906_664, "2026-10-05"),
    ("sample_2.jpg", "20261006200000_1.jpg", 2_658_611_645, "2026-10-06"),
    ("sample_1.jpg", "20261008043000_1.jpg", 2_672_583_581, "2026-10-07"),  # AM5:00 前なので前日
]

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label))
    print(f"  [{'OK' if ok else 'NG'}] {label}" + (f"  ({detail})" if detail and not ok else ""))


def start_server(data_dir: str) -> tuple[uvicorn.Server, threading.Thread, str, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(data_dir)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise SystemExit("サーバーを起動できませんでした")
        time.sleep(0.05)
    return server, thread, f"http://127.0.0.1:{port}", app.state.token


def scan(c: httpx.Client, fixture: str, upload_name: str) -> dict:
    r = c.post("/api/scan", files=[("files", (upload_name, (FIXTURES / fixture).read_bytes(), "image/jpeg"))])
    r.raise_for_status()
    return r.json()["results"][0]


def confirm(c: httpx.Client, item: dict, **over) -> httpx.Response:
    body = {"fan_total": item["value"], "captured_at": item["captured_at"], "filename": item["filename"],
            "image_hash": item["image_hash"], **over}
    return c.post("/api/records", json=body)


def run(base: str, token: str) -> None:
    name = security.cookie_name(base.removeprefix("http://"))
    with httpx.Client(base_url=base, timeout=30, headers={"X-FanTracker": "1"}, cookies={name: token}) as c:
        print("0. 認証と防御ヘッダー")
        bare = httpx.Client(base_url=base, timeout=30)
        check(bare.get("/api/records").status_code == 403, "トークンなしでは、記録を読めない")
        check(bare.get("/api/health").status_code == 200, "起動の確認(/api/health)は、認証なしで応答する")
        check(bare.post("/api/records", headers={"X-FanTracker": "1"}, json={"fan_total": 1, "captured_at": "2026-10-07T12:00:00"}).status_code == 403,
              "トークンなしでは、記録を追加できない")
        check(httpx.get(base + "/api/health", headers={"Host": "evil.example"}).status_code == 403, "許可されていない Host は拒否される")
        h = c.get("/").headers
        check("frame-ancestors 'none'" in h.get("content-security-policy", "") and h.get("x-frame-options") == "DENY",
              "他サイトの iframe に入れられない(CSP / X-Frame-Options)")

        print("1. 画面と静的ファイル")
        page = c.get("/")
        check(page.status_code == 200 and "ファン数トラッカー" in page.text, "トップページが表示できる")
        check(all(c.get(p).status_code == 200 for p in ("/app.js", "/style.css", "/chart.umd.min.js")),
              "app.js / style.css / Chart.js(同梱)が配信される")

        print("2. サンプル画像の読み取り")
        items = [scan(c, f, n) for f, n, _, _ in SAMPLES]
        for item, (_, name, expected, bdate) in zip(items, SAMPLES):
            check(item.get("value") == expected, f"{name}: 読み取り値 {expected:,}", f"実際: {item.get('value')}")
            check(item.get("business_date") == bdate, f"{name}: 集計日 {bdate}(AM5:00 区切り)", f"実際: {item.get('business_date')}")
            check(not item.get("warnings"), f"{name}: 警告なし", str(item.get("warnings")))
        check(c.get(f"/api/images/{items[0]['image_hash']}/crop").headers.get("content-type") == "image/png",
              "切り抜き画像(PNG)が取得できる")

        print("3. 確定・二重登録の防止")
        check(all(confirm(c, i).status_code == 201 for i in items), "3件を確定できる")
        check(confirm(c, items[0]).status_code == 409, "同じ画像の再確定は拒否される")
        check("duplicate_of" in scan(c, *SAMPLES[0][:2]), "同じ画像の再スキャンは登録済みと判定される")

        print("4. 集計(日次・週次・月次)")
        summary = c.get("/api/summary").json()
        series = summary["series"]
        check([s["increment"] for s in series] == [None, 3_704_981, 13_971_936], "日次増加量 3,704,981 / 13,971,936",
              str([s["increment"] for s in series]))
        week = summary["weekly"][0] if summary["weekly"] else {}
        check(week.get("period") == "2026-10-05" and week.get("sum") == 17_676_917 and week.get("max") == 13_971_936
              and week.get("days") == 2, "週次(10/5 の週): 合計 17,676,917 / 最大 13,971,936 / 2日", str(week))
        check(len(summary["monthly"]) == 1 and summary["monthly"][0]["period"] == "2026-10", "月次 2026-10 が1件")

        print("5. 欠損日・日割り補間・警告")
        r = c.post("/api/records", json={"fan_total": 2_690_000_000, "captured_at": "2026-10-12T12:00:00"})
        check(r.status_code == 201, "2026-10-12 を手動追加できる")
        series = c.get("/api/summary").json()["series"]
        check(series[-1]["days"] == 5, "欠損日は「5日分の合計」として扱われる", str(series[-1]))
        interp = c.get("/api/summary", params={"interpolate": True}).json()
        check(len(interp["series"]) == 8, "日割り補間で欠損日が埋まる(全8日)",
              str(len(interp["series"])))
        check(abs(sum(s["increment"] for s in interp["series"][1:]) - (2_690_000_000 - 2_654_906_664)) < 1,
              "補間しても増加量の合計は変わらない")
        low = scan(c, "sample_3.jpg", "20261013200000_1.jpg")
        check(any("小さい" in w for w in low.get("warnings", [])), "前回より小さい値は警告される", str(low.get("warnings")))

        print("6. 同日の複数枚(最新の撮影を採用)")
        newer = c.post("/api/records", json={"fan_total": 2_672_600_000, "captured_at": "2026-10-08T04:50:00"}).json()
        adopted = {r["business_date"]: r for r in c.get("/api/records").json()}
        check(adopted["2026-10-07"]["id"] == newer["id"], "同じ集計日は撮影時刻が新しい方が採用される")
        hist = c.get("/api/records", params={"include_history": True}).json()
        check(len([r for r in hist if r["business_date"] == "2026-10-07"]) == 2, "古い方は履歴に残る")

        print("7. CSV")
        raw = c.get("/api/export.csv").content
        check(raw.startswith(b"\xef\xbb\xbf"), "CSV は UTF-8 BOM 付き(Excel で文字化けしない)")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        table = c.get("/api/summary").json()["series"]
        adopted_rows = [r for r in rows if r["adopted"] == "1"]
        check([int(r["fan_total"]) for r in adopted_rows] == [s["fan_total"] for s in table], "CSV の内容が画面の表と一致する")
        rep = c.post("/api/import/csv", files={"file": ("x.csv", raw)}, data={"mode": "report"}).json()
        check(len(rep["conflict_dates"]) > 0 and rep["errors"] == [], "同じ CSV の再取り込みは重複を報告する")


def main() -> int:
    logging.getLogger("fantracker").setLevel(logging.ERROR)  # 警告のテストで出るログを画面に出さない
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # 後片付けの失敗で確認結果を落とさない
        server, thread, base, token = start_server(tmp)
        try:
            run(base, token)
        finally:
            server.should_exit = True
            thread.join(5)
    failed = [label for ok, label in results if not ok]
    print(f"\n結果: {len(results) - len(failed)}/{len(results)} 件 OK")
    for label in failed:
        print(f"  NG: {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
