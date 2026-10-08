"""読み取り(fantracker/ocr.py)。画像は、数字テンプレートから作る合成のスクリーンショット(tests/synthetic.py)。"""
import io

import pytest
import synthetic
from PIL import Image

from fantracker.ocr import read_fan_total

SAMPLES = synthetic.SAMPLE_VALUES


def reopen(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


@pytest.mark.parametrize("name,expected", SAMPLES.items())
def test_read_fan_total(name, expected):
    result = read_fan_total(reopen(synthetic.sample_bytes(name)))
    assert result.value == expected
    assert result.warnings == []


@pytest.mark.parametrize("value", [1_234_567, 9_876_543_210, 2_000_000_000, 5_050_505_050, 7_000_001, 8_888_888_888, 4_040_404_040])
@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_all_digits_and_lengths_are_read(value, fmt):
    result = read_fan_total(reopen(synthetic.image_bytes(value, fmt)))
    assert result.value == value and result.warnings == []


@pytest.mark.parametrize("scale", [0.8, 1.25, 2.0])
def test_read_fan_total_other_resolution(scale):
    """相対座標なので解像度が違っても同じ値が読める。"""
    size = (round(1625 * scale), round(914 * scale))
    assert read_fan_total(reopen(synthetic.image_bytes(2_672_583_581, "JPEG", size))).value == 2_672_583_581


def test_text_outside_the_region_does_not_matter():
    """切り出し範囲の外(上下の行、ラベル)にある文字は、読み取りに影響しない(合成画像には、上下に濃い帯がある)。"""
    img = synthetic.render_screenshot(2_672_583_581)
    assert img.getpixel((600, 705)) != (255, 255, 255) and img.getpixel((600, 765)) != (255, 255, 255)  # 帯がある
    assert read_fan_total(img).value == 2_672_583_581


def test_non_number_region_is_not_read_as_value():
    """数値のない領域は値として確定しない。"""
    layout = {"fan_total": {"x0": 0.14, "y0": 0.05, "x1": 0.28, "y1": 0.07}}
    result = read_fan_total(synthetic.sample_image("sample_1.jpg"), layout)
    assert result.value is None or result.warnings


def test_too_short_number_is_flagged():
    result = read_fan_total(synthetic.render_screenshot(123_456))
    assert result.value == 123_456 and any("桁数" in w for w in result.warnings)


def test_blurred_image_lowers_confidence_or_warns():
    from PIL import ImageFilter

    img = synthetic.render_screenshot(2_672_583_581).filter(ImageFilter.GaussianBlur(2.5))
    result = read_fan_total(img)
    assert result.value != 2_672_583_581 or result.warnings or result.confidence < 0.9
