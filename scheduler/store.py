"""Loads the people directory and calendars from JSON files."""

import json
import re
from datetime import date, time
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# The only fields about a person that leave the store. Email, phone, home
# city and reporting lines are not the model's business.
DIRECTORY_FIELDS = ("id", "name", "title")


def directory_entry(person: dict) -> dict:
    """Trim one person to the fields the model is allowed to see."""
    return {field: person.get(field) for field in DIRECTORY_FIELDS}


@dataclass
class Store:
    people: list[dict]
    calendars: dict[str, dict[str, list[dict]]]

    @property
    def covered_dates(self) -> set[str]:
        """Dates represented by this sparse busy-only calendar export.

        A person with no entry on a *covered* date has no recorded conflicts.
        A date missing for *everyone* is unknown, not an all-free day.
        """
        return {day for calendar in self.calendars.values() for day in calendar}

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Store":
        with open(data_dir / "people.json") as f:
            people = json.load(f)
        with open(data_dir / "calendars.json") as f:
            calendars = json.load(f)
        # Reject corrupt source intervals instead of silently treating them
        # as free. Sparse dates are still valid: a person may have no blocks.
        clock = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
        for person_id, daily in calendars.items():
            for day, blocks in daily.items():
                try:
                    date.fromisoformat(day)
                except ValueError:
                    raise ValueError(f"Invalid calendar date for {person_id}: {day}") from None
                for block in blocks:
                    if not isinstance(block, dict):
                        raise ValueError(
                            f"Invalid busy interval for {person_id} on {day}"
                        )
                    start, end = block.get("start"), block.get("end")
                    if (not isinstance(start, str) or not isinstance(end, str)
                            or not clock.fullmatch(start) or not clock.fullmatch(end)
                            or time.fromisoformat(start) >= time.fromisoformat(end)):
                        raise ValueError(
                            f"Invalid busy interval for {person_id} on {day}"
                        )
        return cls(people=people, calendars=calendars)
