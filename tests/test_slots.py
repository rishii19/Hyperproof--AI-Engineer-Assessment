from scheduler.slots import (
    availability_from_busy,
    combine_availability,
    find_free_windows,
    slot_to_time,
    time_to_slot,
)


def test_slot_to_time():
    assert slot_to_time(0) == "09:00"
    assert slot_to_time(3) == "10:30"


def test_time_to_slot():
    assert time_to_slot("09:00") == 0
    assert time_to_slot("10:45") == 3


def test_availability_marks_partial_overlap_busy():
    free = availability_from_busy([{"start": "10:00", "end": "10:45"}])
    assert free[2] is False  # 10:00-10:30
    assert free[3] is False  # 10:30-11:00, partially busy
    assert free[4] is True


def test_combine_availability():
    a = [True, True, False, True]
    b = [True, False, True, True]
    assert combine_availability([a, b])[:4] == [True, False, False, True]


def test_find_free_windows():
    free = [False, True, True, True, False, True] + [False] * 10
    assert find_free_windows(free, 2) == [1, 2]


def test_bad_busy_blocks_fail_closed_instead_of_leaving_day_free():
    import pytest

    for block in [
        {"start": "10:00", "end": "09:30"},
        {"start": "10:00", "end": "10:00"},
    ]:
        with pytest.raises(ValueError, match="start before end"):
            availability_from_busy([block])
