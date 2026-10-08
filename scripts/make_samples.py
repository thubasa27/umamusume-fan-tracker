"""手動で試すための、撮影日時入りの合成スクリーンショットを作る(Windows の確認スクリプトが使う)。

    python scripts/make_samples.py <出力フォルダ>

実際のゲームの画像は、リポジトリに含めない。ここで作るのは、数字テンプレートから合成した画像(tests/synthetic.py)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import synthetic  # noqa: E402

# (合成画像の名前, 保存するファイル名, 期待する集計日)
SAMPLES = [
    ("sample_3.jpg", "20261005200000_1.jpg", "2026-10-05"),
    ("sample_2.jpg", "20261006200000_1.jpg", "2026-10-06"),
    ("sample_1.jpg", "20261008043000_1.jpg", "2026-10-07(AM5:00 前なので前日)"),
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples")
    out.mkdir(parents=True, exist_ok=True)
    for source, name, bdate in SAMPLES:
        (out / name).write_bytes(synthetic.sample_bytes(source))
        print(f"  {name}   期待値 {synthetic.SAMPLE_VALUES[source]:,} / 集計日 {bdate}")
    print(f"合成スクリーンショットの場所: {out}")


if __name__ == "__main__":
    main()
