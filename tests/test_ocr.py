from pathlib import Path

import pytest
from PIL import Image

from fantracker.ocr import read_fan_total

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = {
    "sample_1.jpg": 2_672_583_581,
    "sample_2.jpg": 2_658_611_645,
    "sample_3.jpg": 2_654_906_664,
}


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_read_fan_total(name, expected):
    result = read_fan_total(Image.open(FIXTURES / name).convert("RGB"))
    assert result.value == expected
    assert result.warnings == []


@pytest.mark.parametrize("scale", [0.8, 1.25])
def test_read_fan_total_other_resolution(scale):
    """相対座標なので解像度が違っても同じ値が読める。"""
    img = Image.open(FIXTURES / "sample_1.jpg").convert("RGB")
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    assert read_fan_total(img).value == EXPECTED["sample_1.jpg"]


def test_non_number_region_is_not_read_as_value():
    """数値のない領域(ダイアログ左上など)は値として確定しない。"""
    img = Image.open(FIXTURES / "sample_1.jpg").convert("RGB")
    layout = {"fan_total": {"x0": 0.14, "y0": 0.05, "x1": 0.28, "y1": 0.07}}
    result = read_fan_total(img, layout)
    assert result.value is None or result.warnings
