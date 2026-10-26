"""Tools the agent can call. Each tool takes the Store plus keyword arguments
and returns JSON-serialisable data."""

import math
import re

from .slots import (
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    availability_from_busy,
    combine_availability,
    find_free_windows,
    slot_to_time,
    time_to_minutes,
    time_to_slot,
    time_to_slot_ceil,
)
from .store import Store

MAX_DURATION_MINUTES = 480  # one full working day
CLOCK_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _bound_to_slot(clock: str, label: str, convert) -> int:
    """Turn an HH:MM search bound into a slot index inside the working day.

    `convert` decides the rounding: `earliest` rounds up so the meeting never
    starts before the bound, `latest` rounds down so it never ends after it.
    """
    if not isinstance(clock, str) or not CLOCK_PATTERN.match(clock):
        raise ValueError(f"{label} must be a time in HH:MM form, got {clock!r}")
    return max(0, min(SLOTS_PER_DAY, convert(clock)))


def list_people(store: Store) -> list[dict]:
    """Return everyone in the directory."""
    return store.people


def get_busy_times(store: Store, person: str, date: str) -> list[dict]:
    """Return a person's busy blocks on a date (YYYY-MM-DD)."""
    return store.calendars.get(person, {}).get(date, [])


def find_free_slots(
    store: Store,
    attendees: list[str],
    date: str,
    duration_minutes: int,
    earliest: str | None = None,
    latest: str | None = None,
) -> list[dict]:
    """Find every time on `date` when all attendees are free for `duration_minutes`.

    `earliest` and `latest` optionally narrow the search to part of the day
    (e.g. earliest="12:00" for "afternoon"). Durations that are not a whole
    number of slots are rounded up, so a 45-minute meeting reserves an hour.
    """
    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int):
        raise ValueError(
            f"duration_minutes must be a whole number of minutes, "
            f"got {duration_minutes!r}"
        )
    if not 0 < duration_minutes <= MAX_DURATION_MINUTES:
        raise ValueError(
            f"duration_minutes must be between 1 and {MAX_DURATION_MINUTES}, "
            f"got {duration_minutes}"
        )

    calendars = []
    for person in attendees:
        busy = store.calendars.get(person, {}).get(date, [])
        calendars.append(availability_from_busy(busy))

    free = combine_availability(calendars)
    slots_needed = math.ceil(duration_minutes / SLOT_MINUTES)
    start_slot = _bound_to_slot(earliest, "earliest", time_to_slot_ceil) if earliest else 0
    end_slot = _bound_to_slot(latest, "latest", time_to_slot) if latest else SLOTS_PER_DAY
    if earliest and latest and time_to_minutes(earliest) >= time_to_minutes(latest):
        raise ValueError(
            f"earliest ({earliest}) must be before latest ({latest})"
        )

    starts = find_free_windows(free, slots_needed, start_slot, end_slot)
    return [
        {"start": slot_to_time(s), "end": slot_to_time(s + slots_needed)}
        for s in starts
    ]


TOOLS = {
    "list_people": list_people,
    "get_busy_times": get_busy_times,
    "find_free_slots": find_free_slots,
}
