"""Deterministic user-facing responses from validated scheduling tool results.

The model supplies intent/arguments, never attendee or availability claims.
Do not surface an unrecognized result: this is the final trust boundary.
"""

from .slots import SLOT_MINUTES
from .store import Store


def format_verified_result(store: Store, name: str, args: dict, result: object) -> str | None:
    """Render a verified result, or None if its shape is unrecognized."""
    names = {person["id"]: person["name"] for person in store.people}

    if name == "list_people":
        if not isinstance(result, list) or any(
            not isinstance(p, dict) or p.get("id") not in names for p in result
        ):
            return None
        return "People in the directory: " + ", ".join(
            f"{names[p['id']]} ({p['id']})" for p in result
        ) + "."

    if name == "get_busy_times":
        person = args.get("person")
        if person not in names or not isinstance(result, list) or any(
            not isinstance(block, dict) or
            not isinstance(block.get("start"), str) or
            not isinstance(block.get("end"), str)
            for block in result
        ):
            return None
        intervals = ", ".join(f"{b['start']}–{b['end']}" for b in result)
        return (
            f"Recorded busy times for {names[person]} on {args['date']}: "
            + (intervals if intervals else "none") + "."
        )

    if name not in {"find_free_slots", "find_free_slots_in_range"}:
        return None
    attendees = args.get("attendees")
    duration = args.get("duration_minutes")
    if (not isinstance(attendees, list) or not attendees or
        any(person not in names for person in attendees) or
        not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0):
        return None

    is_range = name == "find_free_slots_in_range"
    if is_range:
        if (not isinstance(result, dict) or
            not isinstance(result.get("slots"), list) or
            not isinstance(result.get("truncated"), bool) or
            not isinstance(result.get("unavailable_dates"), list)):
            return None
        slots = result["slots"]
        incomplete_dates = result["unavailable_dates"]
    else:
        if not isinstance(result, list):
            return None
        slots = result
        incomplete_dates = []

    if any(
        not isinstance(slot, dict) or
        not isinstance(slot.get("start"), str) or
        not isinstance(slot.get("end"), str) or
        (is_range and not isinstance(slot.get("date"), str))
        for slot in slots
    ) or any(not isinstance(date, str) for date in incomplete_dates):
        return None

    group = ", ".join(names[person] for person in dict.fromkeys(attendees))
    period = (
        f"from {args['start_date']} to {args['end_date']}"
        if is_range else f"on {args['date']}"
    )
    rounded = ((duration + SLOT_MINUTES - 1) // SLOT_MINUTES) * SLOT_MINUTES
    length = f"{duration}-minute meeting"
    if rounded != duration:
        length += f" (reserving {rounded} minutes in 30-minute slots)"

    intro = f"Verified availability for {group} {period}, {length}: "
    windows = ", ".join(
        (f"{slot['date']} " if is_range else "")
        + f"{slot['start']}–{slot['end']}" for slot in slots
    )
    answer = intro + (windows if windows else "no available windows found") + "."
    if is_range and result["truncated"]:
        answer += " More valid windows exist; showing a limited shortlist."
    if incomplete_dates:
        answer += (
            " Calendar data is unavailable for " + ", ".join(incomplete_dates)
            + "; availability on those dates is unknown."
        )
    return answer
