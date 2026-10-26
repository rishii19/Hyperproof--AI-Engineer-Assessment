"""Tools the agent can call. Each tool takes the Store plus keyword arguments
and returns JSON-serialisable data."""

import math

from .slots import (
    SLOT_MINUTES,
    availability_from_busy,
    combine_availability,
    find_free_windows,
    slot_to_time,
    time_to_slot,
)
from .store import Store

MAX_DURATION_MINUTES = 480  # one full working day


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
    start_slot = time_to_slot(earliest) if earliest else 0
    end_slot = time_to_slot(latest) if latest else None

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
