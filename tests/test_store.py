import json
from pathlib import Path

import pytest

from scheduler.store import Store


@pytest.mark.parametrize("interval", [
    {"start": "11:00", "end": "10:00"},
    {"start": "10:00", "end": "10:00"},
    {"start": "25:00", "end": "26:00"},
    {"start": None, "end": "11:00"},
    None,
])
def test_corrupt_calendar_blocks_are_rejected_on_load(tmp_path: Path, interval):
    (tmp_path / "people.json").write_text('[{"id":"priya","name":"Priya"}]')
    calendars = {"priya": {"2026-11-02": [interval]}}
    (tmp_path / "calendars.json").write_text(json.dumps(calendars))
    with pytest.raises(ValueError, match="Invalid busy interval"):
        Store.load(tmp_path)


def test_sparse_calendar_coverage_is_union_of_dates():
    store = Store.load()
    assert store.covered_dates == {"2026-11-02", "2026-11-03", "2026-11-04"}
