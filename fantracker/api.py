"""ローカル Web アプリの API。取り込みは「scan(読み取り・確認用)→ 確定(POST /api/records)」の2段階。"""
from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import __version__, anomaly, csvio, dates, ocr, paths, security, summary
from .db import DuplicateImage, Store
from .limits import (
    HASH_PATTERN, MAX_CSV_BYTES, MAX_FAN_TOTAL, MAX_FILENAME, MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, MAX_SCAN_FILES,
)

IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png"}
log = logging.getLogger("fantracker")


class RecordIn(BaseModel):
    fan_total: int = Field(gt=0, le=MAX_FAN_TOTAL)
    captured_at: datetime
    business_date: date | None = None  # 省略時は captured_at から AM 5:00 区切りで決める
    filename: str | None = Field(default=None, max_length=MAX_FILENAME)
    image_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    manual: bool = False  # 読み取り値や日付を利用者が修正した


class RecordPatch(BaseModel):
    fan_total: int | None = Field(default=None, gt=0, le=MAX_FAN_TOTAL)
    captured_at: datetime | None = None
    business_date: date | None = None


def create_app(
    data_dir: Path | str | None = None,
    mode: str = "browser",
    on_shutdown: Callable[[], None] | None = None,
    allowed_hosts: Iterable[str] = security.DEFAULT_ALLOWED_HOSTS,
    token: str | None = None,
) -> FastAPI:
    """data_dir 省略時は実行ファイルと同じフォルダの data/(fantracker.paths.data_dir)。

    mode は "window"(専用ウィンドウ)か "browser"(ブラウザ)。on_shutdown は、ブラウザ表示の「終了」ボタンで呼ぶ。
    token は、起動ごとの認証用トークン(省略時は自動で作り、`app.state.token` に入れる)。
    """
    data_dir = Path(data_dir) if data_dir else paths.data_dir()
    image_dir = data_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    store = Store.open(data_dir / "fantracker.db")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.conn.close()  # Windows では開いたままの DB ファイルを削除・移動できない

    app = FastAPI(title="ウマ娘 ファン数トラッカー", lifespan=lifespan)
    app.state.store = store
    app.state.mode = mode
    app.state.token = token or security.new_token()
    security.install(app, app.state.token, allowed_hosts)  # 他サイト・他のユーザーからのアクセスを拒否

    @app.get("/api/health")
    def health():
        return {"ok": True}  # 認証なし。起動の確認用(何も返さない)

    @app.get("/api/info")
    def info():
        browser = app.state.mode == "browser"
        return {"version": __version__, "mode": app.state.mode, "can_shutdown": browser and on_shutdown is not None}

    @app.post("/api/shutdown")
    def shutdown():
        """ブラウザ表示のときの終了(X-FanTracker ヘッダーの確認は security のミドルウェアが行う)。"""
        if app.state.mode != "browser" or on_shutdown is None:
            raise HTTPException(404)
        log.info("終了が要求されました")
        on_shutdown()
        return {"ok": True}

    def image_path(image_hash: str) -> Path | None:
        if not image_hash.isalnum():
            return None
        return next(iter(image_dir.glob(f"{image_hash}.*")), None)

    @app.post("/api/scan")
    async def scan(files: list[UploadFile] = File(...), last_modified_ms: list[int] = Form(default=[])):
        """画像を読み取って結果を返す(DB には登録しない)。`last_modified_ms` は files と同順。"""
        if len(files) > MAX_SCAN_FILES:
            raise HTTPException(413, f"一度に読み取れるのは {MAX_SCAN_FILES} 枚までです")
        results = []
        for i, f in enumerate(files):
            data = await f.read(MAX_IMAGE_BYTES + 1)  # 上限を超える分は読まない
            name = (f.filename or "")[:MAX_FILENAME]
            if len(data) > MAX_IMAGE_BYTES:
                log.warning("ファイルが大きすぎます: %r", name)
                results.append({"filename": name, "error": f"ファイルが大きすぎます(上限 {MAX_IMAGE_BYTES // 1024 // 1024}MB)"})
                continue
            image_hash = hashlib.sha256(data).hexdigest()
            item: dict = {"filename": f.filename, "image_hash": image_hash}
            try:
                img = Image.open(io.BytesIO(data))  # ヘッダーだけ読む(画素は読み込まない)
                if img.width * img.height > MAX_IMAGE_PIXELS:
                    log.warning("画像が大きすぎます: %r (%dx%d)", name, img.width, img.height)
                    results.append({**item, "error": f"画像が大きすぎます(上限 {MAX_IMAGE_PIXELS // 1_000_000} メガピクセル)"})
                    continue
                img.load()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                log.warning("画像として読み込めません: %r", name)
                results.append({**item, "error": "画像として読み込めません"})
                continue
            if img.format not in IMAGE_SUFFIXES:
                log.warning("PNG/JPG 以外は取り込めません: %r (%s)", name, img.format)
                results.append({**item, "error": "PNG/JPG 以外は取り込めません"})
                continue

            if dup := store.find_by_hash(image_hash):
                item["duplicate_of"] = dup["id"]
            else:  # 確認画面での切り抜き表示用に保存(同じ画像は再保存しない)
                path = image_dir / f"{image_hash}{IMAGE_SUFFIXES[img.format]}"
                if not path.exists():
                    path.write_bytes(data)

            read = ocr.read_fan_total(img.convert("RGB"))
            lm = last_modified_ms[i] if i < len(last_modified_ms) else None
            captured_at, source = dates.resolve_captured_at(f.filename or "", lm)
            item.update(
                value=read.value, text=read.text, confidence=read.confidence,
                warnings=list(read.warnings), date_source=source,
                captured_at=captured_at.isoformat(timespec="seconds") if captured_at else None,
                business_date=dates.business_date(captured_at).isoformat() if captured_at else None,
            )
            if source == "unknown":
                item["warnings"].append("撮影日時を特定できません。手動で指定してください")
            elif captured_at and read.value is not None:
                item["warnings"] += anomaly.check(
                    store.list(), dates.business_date(captured_at), read.value
                )
            if item["warnings"]:  # NFR-6: 読み取りの失敗・警告をログに残す
                log.warning("読み取り警告 %r (読取値=%s): %s", name, read.value, " / ".join(item["warnings"]))
            results.append(item)
        return {"results": results}

    @app.get("/api/images/{image_hash}/crop")
    def crop(image_hash: str):
        """確認画面用に、読み取り対象の領域を拡大した PNG を返す。"""
        path = image_path(image_hash)
        if path is None:
            raise HTTPException(404, "画像がありません")
        region = ocr.crop_region(Image.open(path).convert("RGB"), ocr.load_layout()["fan_total"])
        buf = io.BytesIO()
        region.resize((region.width * 4, region.height * 4), Image.LANCZOS).save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.post("/api/records", status_code=201)
    def create_record(body: RecordIn):
        if body.image_hash and image_path(body.image_hash) is None and store.find_by_hash(body.image_hash) is None:
            raise HTTPException(422, "image_hash に対応する画像がありません。先に scan してください")
        try:
            return store.add(
                business_date=body.business_date or dates.business_date(body.captured_at),
                captured_at=body.captured_at,
                fan_total=body.fan_total,
                filename=body.filename,
                image_hash=body.image_hash,
                manual=body.manual or body.image_hash is None,
            )
        except DuplicateImage as e:
            raise HTTPException(409, {"message": str(e), "duplicate_of": e.record_id})

    @app.get("/api/records")
    def list_records(include_history: bool = False):
        return store.list(include_history)

    @app.patch("/api/records/{record_id}")
    def patch_record(record_id: int, body: RecordPatch):
        # 撮影日時だけ直した場合は集計日も追従させる
        fields = body.model_dump(exclude_none=True)
        if "captured_at" in fields and "business_date" not in fields:
            fields["business_date"] = dates.business_date(fields["captured_at"])
        updated = store.update(record_id, **fields)
        if updated is None:
            raise HTTPException(404, "記録がありません")
        return updated

    @app.delete("/api/records/{record_id}", status_code=204)
    def delete_record(record_id: int):
        if not store.delete(record_id):
            raise HTTPException(404, "記録がありません")

    @app.get("/api/summary")
    def get_summary(period: str = "all", interpolate: bool = False):
        """period は "7" / "30" / "all"。週次・月次は期間によらず全期間で集計する。"""
        if period not in {"7", "30", "all"}:
            raise HTTPException(422, "period は 7 / 30 / all のいずれか")
        series = summary.build_series(store.list(), interpolate)
        return {
            "series": summary.filter_period(series, None if period == "all" else int(period)),
            "weekly": summary.aggregate(series, "week"),
            "monthly": summary.aggregate(series, "month"),
            "interpolate": interpolate,
        }

    @app.get("/api/export.csv")
    def export_csv():
        body = csvio.export_csv(store.list(include_history=True), store.list())
        return Response(body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="fan_records.csv"'})

    @app.post("/api/import/csv")
    async def import_csv(file: UploadFile = File(...), mode: str = Form("report")):
        """mode: report=登録せず衝突を報告 / skip=集計日が重複する行を飛ばす / overwrite=重複する集計日の既存記録を置き換える。"""
        if mode not in {"report", "skip", "overwrite"}:
            raise HTTPException(422, "mode は report / skip / overwrite のいずれか")
        raw = await file.read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise HTTPException(413, f"CSV が大きすぎます(上限 {MAX_CSV_BYTES // 1024 // 1024}MB)")
        rows, errors = csvio.parse_csv(raw)
        existing_dates = {r["business_date"] for r in store.list(include_history=True)}
        conflicts = sorted({r["business_date"].isoformat() for r in rows} & existing_dates)
        result = {"rows": len(rows), "errors": errors, "conflict_dates": conflicts,
                  "imported": 0, "skipped_duplicates": 0, "skipped_conflicts": 0}
        if mode == "report" or errors and not rows:
            return result
        if mode == "overwrite":
            for rec in store.list(include_history=True):
                if rec["business_date"] in conflicts:
                    store.delete(rec["id"])
        for row in rows:
            if mode == "skip" and row["business_date"].isoformat() in conflicts:
                result["skipped_conflicts"] += 1
                continue
            try:
                store.add(**row)
                result["imported"] += 1
            except DuplicateImage:
                result["skipped_duplicates"] += 1
        return result

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
