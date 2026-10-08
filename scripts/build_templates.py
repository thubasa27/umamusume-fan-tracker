"""数字テンプレートを作る。

テンプレートは sample_1.jpg の「総獲得数」以外の行(育成回数・トロフィー数など、
同じフォントの数値)から作り、総獲得数の行はテスト専用に残す。
「人」だけは総獲得数の行にしか無いので、sample_1 の末尾から取る。

    python scripts/build_templates.py

元の画像(ゲームのスクリーンショット)はリポジトリに含めない。再生成するときは、手元の画像を
tests/fixtures/local/sample_1.jpg に置く(tests/fixtures/local/ は .gitignore で除外)。
できた fantracker/templates.npz(文字の小さなビットマップ)だけを、リポジトリに含める。
"""
from pathlib import Path

import numpy as np
from PIL import Image

from fantracker import ocr

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "fixtures" / "local" / "sample_1.jpg"  # 実際のスクリーンショット(リポジトリには含めない)

# 基準解像度(1625x914)での各行の中心 y と、その行に表示されている文字列
ROWS = [
    (110, "4,911"), (138, "119"), (167, "73,790"),
    (222, "44"), (251, "44"), (279, "76"), (308, "115"),
    (420, "5,526"),
    (473, "169"), (501, "897"), (530, "180"), (558, "466"),
    (587, "51"), (615, "688"), (644, "14,816"), (672, "12,647"),
]
FAN_ROW = (740, "2,672,583,581人")
X0, X1 = 0.3403, 0.4308  # layout.json の fan_total と同じ横範囲(ラベルのピルを含めない)
HALF_H = 9  # 行中心から上下 9px(CANON_H=18 に一致。隣の行を含めない)


def row_box(cy: int, w: int, h: int) -> dict:
    return {"x0": X0, "x1": X1, "y0": (cy - HALF_H) / h, "y1": (cy + HALF_H) / h}


def extract(img: Image.Image, cy: int, label: str):
    gray = np.array(ocr.crop_region(img, row_box(cy, *img.size)).convert("L"))
    spans = ocr.segment(gray)
    if len(spans) != len(label):
        raise SystemExit(f"{label!r}: 文字数 {len(label)} に対し {len(spans)} 個に分割された")
    return [(c, ocr.glyph_feature(gray, s)) for c, s in zip(label, spans)]


def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit(f"元の画像がありません: {SAMPLE}\n実際のスクリーンショットを、この場所に置いてください(リポジトリには含めません)。")
    img = Image.open(SAMPLE).convert("RGB")
    samples: dict[str, list[np.ndarray]] = {}
    for cy, label in ROWS:
        for c, f in extract(img, cy, label):
            samples.setdefault(c, []).append(f)
    cy, label = FAN_ROW
    samples[ocr.UNIT] = [extract(img, cy, label)[-1][1]]

    chars = sorted(samples)
    glyphs = np.stack([np.mean(samples[c], axis=0) for c in chars])
    np.savez_compressed(ocr.TEMPLATES_PATH, chars=np.array(chars), glyphs=glyphs)
    print("templates:", {c: len(samples[c]) for c in chars})


if __name__ == "__main__":
    main()
