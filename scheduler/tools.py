"""Tools the agent can call. Each tool takes the Store plus keyword arguments
and returns JSON-serialisable data."""

import datetime
import math
import re
from itertools import zip_longest

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
from .store import Store, directory_entry

MAX_DURATION_MINUTES = 480  # one full working day
MAX_RANGE_DAYS = 14  # a date range may span at most a fortnight
MAX_RESULTS_CAP = 20  # a range search never returns more than this
# A 24-hour clock time. The hour may be given with or without its
# leading zero ("9:00" as well as "09:00"), but nothing else is
# accepted: the whole string must be the time and nothing more.
CLOCK_PATTERN = re.compile(r"\A([01]?[0-9]|2[0-3]):[0-5][0-9]\Z")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ToolError(ValueError):
    """A tool was called with arguments it cannot act on.

    The message is written for the model: it says what was wrong and, where
    useful, what the valid values are, so the next turn can correct itself.
    """


def _known_ids(store: Store) -> list[str]:
    return [person["id"] for person in store.people]


def _check_person(store: Store, person) -> None:
    known = _known_ids(store)
    if person not in known:
        raise ToolError(
            f"Unknown person {person!r}. Valid ids: {', '.join(known)}"
        )


def _check_attendees(store: Store, attendees) -> None:
    known = _known_ids(store)
    if not isinstance(attendees, list) or not attendees:
        raise ToolError(
            f"attendees must be a non-empty list of person ids, got "
            f"{attendees!r}. Valid ids: {', '.join(known)}"
        )
    unknown = [a for a in attendees if a not in known]
    if unknown:
        raise ToolError(
            f"Unknown attendee ids: {', '.join(repr(a) for a in unknown)}. "
            f"Valid ids: {', '.join(known)}"
        )


def _parse_date(value, label: str = "date") -> datetime.date:
    """Validate a YYYY-MM-DD string and return it as a date.

    `label` names the argument in the error message, so a range search can
    say which end of it was wrong.
    """
    if not isinstance(value, str) or not DATE_PATTERN.match(value):
        raise ToolError(f"{label} must be in YYYY-MM-DD form, got {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"{label} {value!r} is not a real calendar date") from None


def _check_date(value) -> None:
    """Validate a single meeting date. Weekends are not meeting days."""
    parsed = _parse_date(value)
    if parsed.weekday() >= 5:
        raise ToolError(
            f"{value} is a {parsed.strftime('%A')}; meetings are only "
            f"scheduled on weekdays"
        )


def _check_duration(duration_minutes) -> None:
    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int):
        raise ToolError(
            f"duration_minutes must be a whole number of minutes, "
            f"got {duration_minutes!r}"
        )
    if not 0 < duration_minutes <= MAX_DURATION_MINUTES:
        raise ToolError(
            f"duration_minutes must be between 1 and {MAX_DURATION_MINUTES}, "
            f"got {duration_minutes}"
        )


def _check_bounds(earliest, latest) -> None:
    """Validate the optional HH:MM search bounds, together and apart."""
    for label, clock in (("earliest", earliest), ("latest", latest)):
        if clock is None:
            continue
        if not isinstance(clock, str) or not CLOCK_PATTERN.match(clock):
            raise ToolError(
                f"{label} must be a 24-hour time such as 09:00 or 9:00, "
                f"got {clock!r}"
            )
    if earliest and latest and time_to_minutes(earliest) >= time_to_minutes(latest):
        raise ToolError(
            f"earliest ({earliest}) must be before latest ({latest})"
        )


def _check_max_results(max_results) -> int:
    """Validate max_results and return it clamped to the hard cap.

    Asking for more than the cap is not an error - the model gets the cap's
    worth of slots, which is plenty to choose from - but 0 or a negative is
    too ambiguous to guess at ("none" or "all"?), so say so instead.
    """
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ToolError(
            f"max_results must be a whole number, got {max_results!r}"
        )
    if max_results < 1:
        raise ToolError(f"max_results must be at least 1, got {max_results}")
    return min(max_results, MAX_RESULTS_CAP)


def _bound_to_slot(clock: str, convert) -> int:
    """Turn an HH:MM search bound into a slot index inside the working day.

    `convert` decides the rounding: `earliest` rounds up so the meeting never
    starts before the bound, `latest` rounds down so it never ends after it.
    The bound has already been validated by `_check_bounds`.
    """
    return max(0, min(SLOTS_PER_DAY, convert(clock)))


def list_people(store: Store) -> list[dict]:
    """Return everyone in the directory.

    Each person is trimmed to the directory fields, for the same reason
    the system prompt is: contact details and reporting lines are not
    needed to find a meeting time, so the model never sees them.
    """
    return [directory_entry(person) for person in store.people]


def get_busy_times(store: Store, person: str, date: str) -> list[dict]:
    """Return the times a person is busy on a date (YYYY-MM-DD).

    Only start and end are returned: meeting titles can be confidential and
    the agent does not need them to find a free slot. `date` is validated
    the way find_free_slots validates it, weekends included.
    """
    _check_person(store, person)
    _check_date(date)
    busy = store.calendars.get(person, {}).get(date, [])
    return [{"start": block["start"], "end": block["end"]} for block in busy]


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
    _check_attendees(store, attendees)
    _check_date(date)
    _check_duration(duration_minutes)
    _check_bounds(earliest, latest)

    calendars = []
    for person in attendees:
        busy = store.calendars.get(person, {}).get(date, [])
        calendars.append(availability_from_busy(busy))

    free = combine_availability(calendars)
    slots_needed = math.ceil(duration_minutes / SLOT_MINUTES)
    start_slot = _bound_to_slot(earliest, time_to_slot_ceil) if earliest else 0
    end_slot = _bound_to_slot(latest, time_to_slot) if latest else SLOTS_PER_DAY

    starts = find_free_windows(free, slots_needed, start_slot, end_slot)
    return [
        {"start": slot_to_time(s), "end": slot_to_time(s + slots_needed)}
        for s in starts
    ]


def find_free_slots_in_range(
    store: Store,
    attendees: list[str],
    start_date: str,
    end_date: str,
    duration_minutes: int,
    earliest: str | None = None,
    latest: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Find times across a date range when all attendees are free.

    Searches every weekday from `start_date` to `end_date` inclusive -
    Saturdays and Sundays are skipped, though the range may start or end on
    one - and returns at most `max_results` slots (20 at the very most),
    each tagged with the `date` it falls on. The range itself may span at
    most 14 days, so "next week" works but "some time this year" does not.
    A range with no weekday in it at all is an error, not an empty result.

    Results are spread across the days of the range: the earliest window of
    each day first, then each day's second, and so on until `max_results`
    is reached, so one wide-open day cannot crowd out the rest of the week.

    `duration_minutes`, `earliest` and `latest` mean what they do in
    `find_free_slots`, which does the per-day work.
    """
    # Validate everything up front: a range with no weekdays in it searches
    # nothing, and silently returning [] would hide a bad argument.
    _check_attendees(store, attendees)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise ToolError(
            f"end_date ({end_date}) must not be before start_date "
            f"({start_date})"
        )
    span_days = (end - start).days + 1
    if span_days > MAX_RANGE_DAYS:
        raise ToolError(
            f"The range {start_date} to {end_date} covers {span_days} days; "
            f"search at most {MAX_RANGE_DAYS} days at a time"
        )
    _check_duration(duration_minutes)
    _check_bounds(earliest, latest)
    limit = _check_max_results(max_results)
    if not any(
        (start + datetime.timedelta(days=offset)).weekday() < 5
        for offset in range(span_days)
    ):
        raise ToolError(
            f"The range {start_date} to {end_date} contains no weekdays; "
            f"weekends are not working days"
        )

    # Search each weekday whole first. Days ascend and find_free_slots
    # returns each day's windows in time order.
    per_day: list[list[dict]] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            date = day.isoformat()
            per_day.append([
                {"date": date, **slot}
                for slot in find_free_slots(
                    store, attendees, date, duration_minutes, earliest, latest
                )
            ])
        day += datetime.timedelta(days=1)

    # Then take every day's first window before any day's second, so a
    # wide-open Monday cannot fill a short list on its own and hide the
    # rest of the week. A day with nothing free pads with None here, so it
    # drops out without spending any of the limit.
    interleaved = [
        window
        for same_rank in zip_longest(*per_day)
        for window in same_rank
        if window is not None
    ]
    # The round-robin interleaved the days; sort to hand them back in
    # date-then-time order.
    return sorted(
        interleaved[:limit], key=lambda row: (row["date"], row["start"])
    )


TOOLS = {
    "list_people": list_people,
    "get_busy_times": get_busy_times,
    "find_free_slots": find_free_slots,
    "find_free_slots_in_range": find_free_slots_in_range,
}
