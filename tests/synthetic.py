"""テスト用の合成スクリーンショット。

ゲームのスクリーンショットをリポジトリに置かずにテストするため、数字テンプレート(fantracker/templates.npz)の文字を
「総獲得数」の位置に並べた画像を作る。上下の行に見立てた濃い帯と、ラベルに見立てた灰色の帯も描き、切り出し範囲の外にある
文字が読み取りに影響しないことも確かめられるようにしている。

限界: 文字はテンプレート自身なので、これは「読み取りの流れ(切り出し・分割・照合・API・画面)が正しい」ことの確認で、
未知の画像での読み取り精度の確認ではない。実際のスクリーンショットでの確認は、tests/fixtures/local/ に置いた画像で行う
(tests/test_real_samples.py。リポジトリには含めない)。
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from fantracker import ocr

BASE_SIZE = (1625, 914)
GAP = 2  # 文字と文字の間の空白(列)
INK = 0.42  # 読み取り側が文字とみなす濃さ(輝度 150 未満)より、わずかに濃い列だけを文字の幅とする
JPEG_QUALITY = 92

# 3 つのサンプル(sample_N.jpg)に対応する値。以前は実際のスクリーンショットだった
SAMPLE_VALUES = {
    "sample_1.jpg": 2_672_583_581,
    "sample_2.jpg": 2_658_611_645,
    "sample_3.jpg": 2_654_906_664,
}


def _strip(text: str) -> np.ndarray:
    """文字列を、テンプレートの文字を並べた濃度マップ(高さ CANON_H、0=白 1=黒)にする。"""
    chars, glyphs = ocr.load_templates()
    table = dict(zip(chars, glyphs))
    pieces = []
    for c in text:
        g = table[c]
        cols = np.where((g > INK).any(axis=0))[0]
        pieces.append(g[:, cols.min() : cols.max() + 1])
    gap = np.zeros((ocr.CANON_H, GAP), dtype=np.float32)
    out = []
    for p in pieces:
        out += [p, gap]
    return np.concatenate(out[:-1], axis=1)


def render_screenshot(fan_total: int, size: tuple[int, int] = BASE_SIZE) -> Image.Image:
    """`fan_total` を「総獲得数」の位置に描いた、進行状況ダイアログ風の画像。"""
    w, h = BASE_SIZE
    box = ocr.load_layout()["fan_total"]
    x0, y0 = round(box["x0"] * w), round(box["y0"] * h)
    x1, y1 = round(box["x1"] * w), round(box["y1"] * h)
    assert (x1 - x0, y1 - y0) == (ocr.CANON_W, ocr.CANON_H)

    img = np.full((h, w), 255, dtype=np.uint8)
    img[y0 - 30 : y0 - 17, 556:690] = 90  # 上の行の数値に見立てた濃い帯(切り出し範囲の外)
    img[y1 + 10 : y1 + 23, 556:690] = 90  # 下の行
    img[y0 + 2 : y0 + 16, 406:550] = 225  # ラベルの灰色の帯(範囲の左)

    strip = _strip(f"{fan_total:,}人")
    right = ocr.CANON_W - 11  # 実際の画面では、末尾の「人」が領域の右端から約 11px 内側で終わる
    left = right - strip.shape[1]
    assert left >= 0, "値が大きすぎて領域に収まらない"
    region = np.full((ocr.CANON_H, ocr.CANON_W), 255, dtype=np.uint8)
    region[:, left:right] = np.round(255 * (1 - strip)).astype(np.uint8)
    img[y0:y1, x0:x1] = region

    out = Image.fromarray(img).convert("RGB")
    if size != BASE_SIZE:
        out = out.resize(size, Image.LANCZOS)
    return out


def image_bytes(fan_total: int, fmt: str = "JPEG", size: tuple[int, int] = BASE_SIZE) -> bytes:
    buf = io.BytesIO()
    render_screenshot(fan_total, size).save(buf, fmt, **({"quality": JPEG_QUALITY} if fmt == "JPEG" else {}))
    return buf.getvalue()


def sample_image(name: str) -> Image.Image:
    return render_screenshot(SAMPLE_VALUES[name])


def sample_bytes(name: str) -> bytes:
    """sample_N.jpg に相当する、JPEG の合成スクリーンショット。"""
    return image_bytes(SAMPLE_VALUES[name])
