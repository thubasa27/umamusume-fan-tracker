from datetime import date, datetime

import pytest

from fantracker.db import DuplicateImage, Store


@pytest.fixture
def store():
    return Store.open(":memory:")


def add(store, d, hhmm, total, **kw):
    h, m = divmod(hhmm, 100)
    return store.add(business_date=date.fromisoformat(d), captured_at=datetime.fromisoformat(f"{d}T{h:02d}:{m:02d}:00"),
                     fan_total=total, **kw)


def test_latest_capture_is_adopted_regardless_of_import_order(store):
    late = add(store, "2026-10-07", 2300, 200)
    early = add(store, "2026-10-07", 1000, 100)  # 後から取り込んだ古い撮影
    rows = {r["id"]: r for r in store.list(include_history=True)}
    assert rows[late["id"]]["adopted"] == 1 and rows[early["id"]]["adopted"] == 0
    assert [r["id"] for r in store.list()] == [late["id"]]


def test_duplicate_hash_is_rejected(store):
    first = add(store, "2026-10-07", 1000, 100, image_hash="abc")
    with pytest.raises(DuplicateImage) as e:
        add(store, "2026-10-08", 1000, 200, image_hash="abc")
    assert e.value.record_id == first["id"]
    assert len(store.list(include_history=True)) == 1


def test_delete_promotes_previous_capture(store):
    a = add(store, "2026-10-07", 1000, 100)
    b = add(store, "2026-10-07", 2000, 200)
    store.delete(b["id"])
    assert [r["id"] for r in store.list()] == [a["id"]]


def test_update_moves_between_days_and_marks_manual(store):
    a = add(store, "2026-10-07", 1000, 100)
    b = add(store, "2026-10-07", 2000, 200)
    store.update(b["id"], business_date=date(2026, 10, 8))
    adopted = {r["business_date"]: r for r in store.list()}
    assert adopted["2026-10-07"]["id"] == a["id"]
    assert adopted["2026-10-08"]["id"] == b["id"] and adopted["2026-10-08"]["manual"] == 1


def test_update_missing_returns_none(store):
    assert store.update(999, fan_total=1) is None
    assert store.delete(999) is False
