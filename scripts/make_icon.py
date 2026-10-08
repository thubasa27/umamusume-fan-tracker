"""packaging/FanTracker.ico を作る(favicon.svg と同じ、緑地に白い棒グラフ)。

    python scripts/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "packaging" / "FanTracker.ico"
S = 256  # 64x64 の favicon.svg を 4 倍に拡大した座標


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=56, fill="#2e9d48")
    for x, y, h in [(48, 152, 56), (108, 112, 96), (168, 56, 152)]:
        d.rounded_rectangle((x, y, x + 40, y + h), radius=8, fill="#ffffff")
    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
