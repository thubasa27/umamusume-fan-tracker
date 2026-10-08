"""実際のスクリーンショットでの読み取り(任意)。

画像はリポジトリに含めない(ゲームの画面のため)。手元に実際のスクリーンショットがあるときだけ、次のように置くと動く:

    tests/fixtures/local/sample_1.jpg   → 2,672,583,581
    tests/fixtures/local/sample_2.jpg   → 2,658,611,645
    tests/fixtures/local/sample_3.jpg   → 2,654,906,664

(ほかの画像で試すときは、tests/fixtures/local/expected.json に {"ファイル名": 値} を書く。)
tests/fixtures/local/ は .gitignore で除外している。画像が無ければ、このテストはスキップされる。
"""
import json
from pathlib import Path

import pytest
from PIL import Image

from fantracker.ocr import read_fan_total

LOCAL = Path(__file__).parent / "fixtures" / "local"
EXPECTED = {"sample_1.jpg": 2_672_583_581, "sample_2.jpg": 2_658_611_645, "sample_3.jpg": 2_654_906_664}
if (LOCAL / "expected.json").exists():
    EXPECTED.update(json.loads((LOCAL / "expected.json").read_text(encoding="utf-8")))
FOUND = {name: value for name, value in EXPECTED.items() if (LOCAL / name).exists()}


@pytest.mark.skipif(not FOUND, reason="tests/fixtures/local/ に実際のスクリーンショットがありません(任意のテスト)")
@pytest.mark.parametrize("name", sorted(FOUND) or ["(なし)"])
def test_real_screenshot(name):
    result = read_fan_total(Image.open(LOCAL / name).convert("RGB"))
    assert result.value == FOUND[name] and result.warnings == []
