"""ローカル Web アプリの API。取り込みは「scan(読み取り・確認用)→ 確定(POST /api/records)」の2段階。"""
from __future__ import annotations

import hashlib
import io
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import anomaly, csvio, dates, ocr, paths, summary
from .db import DuplicateImage, Store

IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png"}
log = logging.getLogger("fantracker")


class RecordIn(BaseModel):
    fan_total: int = Field(gt=0)
    captured_at: datetime
    business_date: date | None = None  # 省略時は captured_at から AM 5:00 区切りで決める
    filename: str | None = None
    image_hash: str | None = None
    manual: bool = False  # 読み取り値や日付を利用者が修正した


class RecordPatch(BaseModel):
    fan_total: int | None = Field(default=None, gt=0)
    captured_at: datetime | None = None
    business_date: date | None = None


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    """data_dir 省略時は実行ファイルと同じフォルダの data/(fantracker.paths.data_dir)。"""
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

    def image_path(image_hash: str) -> Path | None:
        if not image_hash.isalnum():
            return None
        return next(iter(image_dir.glob(f"{image_hash}.*")), None)

    @app.post("/api/scan")
    async def scan(files: list[UploadFile] = File(...), last_modified_ms: list[int] = Form(default=[])):
        """画像を読み取って結果を返す(DB には登録しない)。`last_modified_ms` は files と同順。"""
        results = []
        for i, f in enumerate(files):
            data = await f.read()
            image_hash = hashlib.sha256(data).hexdigest()
            item: dict = {"filename": f.filename, "image_hash": image_hash}
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
            except (UnidentifiedImageError, OSError):
                log.warning("画像として読み込めません: %s", f.filename)
                results.append({**item, "error": "画像として読み込めません"})
                continue
            if img.format not in IMAGE_SUFFIXES:
                log.warning("PNG/JPG 以外は取り込めません: %s (%s)", f.filename, img.format)
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
                log.warning("読み取り警告 %s (読取値=%s): %s", f.filename, read.value, " / ".join(item["warnings"]))
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
        rows, errors = csvio.parse_csv(await file.read())
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
