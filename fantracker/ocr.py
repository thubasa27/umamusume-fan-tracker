"""進行状況ダイアログの「総獲得数」を固定相対座標の切り出し+テンプレート照合で読み取る。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

PKG_DIR = Path(__file__).parent
LAYOUT_PATH = PKG_DIR / "layout.json"
TEMPLATES_PATH = PKG_DIR / "templates.npz"

# 切り出し領域を揃える正規化サイズ(基準解像度 1625x914 での領域サイズ)
CANON_W, CANON_H = 147, 18
GLYPH_W = 12  # テンプレートの幅(列方向は中央寄せ)
INK_THRESHOLD = 150  # 輝度がこれ未満の画素を文字とみなす
SHIFT = 1  # 照合時に許容する横ずれ(px)
UNIT = "人"
# 最近傍との距離がこの値を超える、または2位との差が小さい場合は信頼度を下げる
MAX_DISTANCE = 3.0
MIN_MARGIN = 0.2
EXPECTED_DIGITS = (7, 13)  # 総獲得ファン数として妥当な桁数(超えると警告)


@dataclass
class ReadResult:
    value: int | None
    text: str
    confidence: float
    warnings: list[str] = field(default_factory=list)


def load_layout(path: Path = LAYOUT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_templates(path: Path = TEMPLATES_PATH) -> tuple[list[str], np.ndarray]:
    data = np.load(path)
    return [str(c) for c in data["chars"]], data["glyphs"]


def crop_region(img: Image.Image, box: dict) -> Image.Image:
    w, h = img.size
    region = img.crop(
        (round(box["x0"] * w), round(box["y0"] * h), round(box["x1"] * w), round(box["y1"] * h))
    )
    return region.resize((CANON_W, CANON_H), Image.LANCZOS)


def segment(gray: np.ndarray) -> list[tuple[int, int]]:
    """列方向に文字(連続する列)を分割し、(開始列, 終了列+1) を返す。"""
    ink_cols = (gray < INK_THRESHOLD).any(axis=0)
    spans, start = [], None
    for x, on in enumerate(ink_cols):
        if on and start is None:
            start = x
        elif not on and start is not None:
            spans.append((start, x))
            start = None
    if start is not None:
        spans.append((start, len(ink_cols)))
    return spans


def glyph_feature(gray: np.ndarray, span: tuple[int, int]) -> np.ndarray:
    """文字を GLYPH_W 幅の中央寄せキャンバスに載せた濃度マップ(0=白, 1=黒)にする。"""
    x0, x1 = span
    ink = 1.0 - gray[:, x0:x1].astype(np.float32) / 255.0
    canvas = np.zeros((gray.shape[0], GLYPH_W), dtype=np.float32)
    off = (GLYPH_W - ink.shape[1]) // 2
    if off < 0:  # 幅が広すぎる(文字結合など)場合は切り詰める
        ink, off = ink[:, -off : -off + GLYPH_W], 0
    canvas[:, off : off + ink.shape[1]] = ink
    return canvas


def match_glyph(feature: np.ndarray, chars: list[str], glyphs: np.ndarray) -> tuple[str, float, float]:
    """最近傍の文字、その距離、2位との距離差を返す(±SHIFT px の横ずれを許容)。"""
    best: dict[str, float] = {}
    for dx in range(-SHIFT, SHIFT + 1):
        shifted = np.roll(feature, dx, axis=1)
        dist = np.sqrt(((glyphs - shifted) ** 2).sum(axis=(1, 2)))
        for c, d in zip(chars, dist):
            if d < best.get(c, 1e9):
                best[c] = float(d)
    ranked = sorted(best.items(), key=lambda kv: kv[1])
    margin = ranked[1][1] - ranked[0][1] if len(ranked) > 1 else 0.0
    return ranked[0][0], ranked[0][1], margin


def read_text(img: Image.Image, box: dict) -> tuple[str, list[float], list[float]]:
    gray = np.array(crop_region(img, box).convert("L"))
    chars, glyphs = load_templates()
    text, dists, margins = "", [], []
    for span in segment(gray):
        c, d, m = match_glyph(glyph_feature(gray, span), chars, glyphs)
        text += c
        dists.append(d)
        margins.append(m)
    return text, dists, margins


def read_fan_total(img: Image.Image, layout: dict | None = None) -> ReadResult:
    """総獲得ファン数を読み取る。値が読めない場合 value=None。"""
    layout = layout or load_layout()
    text, dists, margins = read_text(img, layout["fan_total"])
    warnings: list[str] = []

    if text.endswith(UNIT):
        body = text[: -len(UNIT)]
    else:
        body = text
        warnings.append("末尾の「人」を検出できませんでした")
    digits = body.replace(",", "")

    if not digits.isdigit():
        return ReadResult(None, text, 0.0, warnings + [f"数値として解釈できません: {text!r}"])
    if body != f"{int(digits):,}":
        warnings.append(f"カンマ位置が不正です: {body!r}")
    if not EXPECTED_DIGITS[0] <= len(digits) <= EXPECTED_DIGITS[1]:
        warnings.append(f"桁数が想定外です: {len(digits)}桁")

    worst_dist, worst_margin = max(dists), min(margins)
    if worst_dist > MAX_DISTANCE or worst_margin < MIN_MARGIN:
        warnings.append("読み取り信頼度が低い文字があります")
    # 距離が小さく2位との差が大きいほど 1 に近い、粗い指標
    confidence = max(0.0, min(1.0, min(1.0 - worst_dist / (2 * MAX_DISTANCE), worst_margin / (1.5 * MIN_MARGIN))))
    return ReadResult(int(digits), text, confidence, warnings)
