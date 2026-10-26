import pytest

from scheduler.store import Store
from scheduler.tools import find_free_slots, get_busy_times


def test_get_busy_times():
    store = Store.load()
    busy = get_busy_times(store, "sam", "2026-11-04")
    assert busy == [{"start": "09:00", "end": "09:30", "title": "Standup"}]


def test_find_free_slots_for_two_people_in_the_afternoon():
    store = Store.load()
    slots = find_free_slots(
        store,
        attendees=["priya", "sam"],
        date="2026-11-03",
        duration_minutes=30,
        earliest="13:00",
    )
    assert slots == [
        {"start": "13:00", "end": "13:30"},
        {"start": "13:30", "end": "14:00"},
        {"start": "15:00", "end": "15:30"},
        {"start": "16:00", "end": "16:30"},
        {"start": "16:30", "end": "17:00"},
    ]


def test_find_free_slots_hour_long_meeting():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["priya", "sam"], date="2026-11-03", duration_minutes=60
    )
    assert {"start": "13:00", "end": "14:00"} in slots


def test_find_free_slots_includes_the_last_slot_of_the_day():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30
    )
    assert slots[0] == {"start": "09:00", "end": "09:30"}
    assert slots[-1] == {"start": "16:30", "end": "17:00"}
    assert len(slots) == 16


def test_find_free_slots_rounds_duration_up_to_whole_slots():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=45
    )
    # 45 minutes needs two 30-minute slots, not one.
    assert slots[0] == {"start": "09:00", "end": "10:00"}
    assert len(slots) == 15


def test_find_free_slots_rejects_bad_durations():
    store = Store.load()
    for duration in [0, -30, 481, "30", 30.0, None, True]:
        with pytest.raises(ValueError):
            find_free_slots(
                store, attendees=["luis"], date="2026-11-02",
                duration_minutes=duration,
            )


def test_earliest_rounds_up_and_latest_rounds_down():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="13:10", latest="15:50",
    )
    # 13:10 rounds up to 13:30; 15:50 rounds down to 15:30.
    assert slots == [
        {"start": "13:30", "end": "14:00"},
        {"start": "14:00", "end": "14:30"},
        {"start": "14:30", "end": "15:00"},
        {"start": "15:00", "end": "15:30"},
    ]


def test_bounds_outside_the_working_day_are_clamped():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="06:00", latest="23:00",
    )
    assert len(slots) == 16


def test_find_free_slots_rejects_bad_bounds():
    store = Store.load()
    bad = [
        {"earliest": "14:00", "latest": "14:00"},
        {"earliest": "15:00", "latest": "13:00"},
        {"earliest": "9am"},
        {"latest": "25:00"},
        {"earliest": "1300"},
        {"latest": "13:60"},
    ]
    for bounds in bad:
        with pytest.raises(ValueError):
            find_free_slots(
                store, attendees=["luis"], date="2026-11-02",
                duration_minutes=30, **bounds,
            )
