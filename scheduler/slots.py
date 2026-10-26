"""Time-slot utilities for the scheduling assistant.

The working day is divided into fixed-size slots. Slot 0 starts at
DAY_START. A person's availability for one day is a list of booleans,
one entry per slot, where True means the person is free.
"""

from datetime import time

DAY_START = time(9, 0)
DAY_END = time(17, 0)
SLOT_MINUTES = 30
SLOTS_PER_DAY = 16  # 09:00 to 17:00

DAY_START_MINUTES = DAY_START.hour * 60 + DAY_START.minute


def time_to_minutes(clock: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def minutes_to_time(minutes: int) -> str:
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_to_slot(clock: str) -> int:
    """Convert a clock time to the index of the slot containing it."""
    return (time_to_minutes(clock) - DAY_START_MINUTES) // SLOT_MINUTES


def time_to_slot_ceil(clock: str) -> int:
    """Convert a clock time to a slot index, rounding up to the next boundary."""
    offset = time_to_minutes(clock) - DAY_START_MINUTES
    return -(-offset // SLOT_MINUTES)


def slot_to_time(index: int) -> str:
    """Convert a slot index to the clock time at which that slot starts."""
    return minutes_to_time(DAY_START_MINUTES + index * SLOT_MINUTES)


def availability_from_busy(busy_blocks: list[dict]) -> list[bool]:
    """Build a free/busy list for one day from a person's busy blocks.

    Any slot that overlaps a busy block, even partially, is marked busy.
    """
    free = [True] * SLOTS_PER_DAY
    for block in busy_blocks:
        start = max(0, time_to_slot(block["start"]))
        end = min(SLOTS_PER_DAY, time_to_slot_ceil(block["end"]))
        for i in range(start, end):
            free[i] = False
    return free


def combine_availability(calendars: list[list[bool]]) -> list[bool]:
    """Intersect several free/busy lists: a slot is free only if free for everyone."""
    combined = [True] * SLOTS_PER_DAY
    for free in calendars:
        combined = [a and b for a, b in zip(combined, free)]
    return combined


def find_free_windows(
    free: list[bool],
    slots_needed: int,
    start_slot: int = 0,
    end_slot: int | None = None,
) -> list[int]:
    """Return the starting slot index of every run of `slots_needed` free slots.

    Only windows that begin at or after `start_slot` and finish by
    `end_slot` are considered.
    """
    if end_slot is None:
        end_slot = SLOTS_PER_DAY
    results = []
    for start in range(start_slot, end_slot - slots_needed):
        if all(free[start:start + slots_needed]):
            results.append(start)
    return results
