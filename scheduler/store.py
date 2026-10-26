"""Loads the people directory and calendars from JSON files."""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Store:
    people: list[dict]
    calendars: dict[str, dict[str, list[dict]]]

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Store":
        with open(data_dir / "people.json") as f:
            people = json.load(f)
        with open(data_dir / "calendars.json") as f:
            calendars = json.load(f)
        return cls(people=people, calendars=calendars)
