from datetime import date, datetime

from fantracker.dates import business_date, parse_filename, resolve_captured_at


def test_business_date_boundary_is_5am():
    assert business_date(datetime(2026, 10, 8, 4, 59, 59)) == date(2026, 10, 7)
    assert business_date(datetime(2026, 10, 8, 5, 0, 0)) == date(2026, 10, 8)
    assert business_date(datetime(2026, 10, 7, 20, 46, 38)) == date(2026, 10, 7)
    assert business_date(datetime(2026, 1, 1, 0, 30)) == date(2025, 12, 31)  # 年またぎ


def test_parse_filename():
    assert parse_filename("20261007204638_1.jpg") == datetime(2026, 10, 7, 20, 46, 38)
    assert parse_filename("C:/shots/20261007204638_1.JPG") == datetime(2026, 10, 7, 20, 46, 38)
    assert parse_filename("20261007204638.png") == datetime(2026, 10, 7, 20, 46, 38)


def test_parse_filename_rejects_bad_names():
    assert parse_filename("screenshot.jpg") is None
    assert parse_filename("20261307204638_1.jpg") is None  # 13月
    assert parse_filename("2026100720463_1.jpg") is None  # 13桁


def test_resolve_falls_back_to_mtime_then_unknown():
    assert resolve_captured_at("20261007204638_1.jpg", 0)[1] == "filename"
    dt, src = resolve_captured_at("a.jpg", 1_790_000_000_000)
    assert src == "mtime" and dt is not None
    assert resolve_captured_at("a.jpg") == (None, "unknown")
