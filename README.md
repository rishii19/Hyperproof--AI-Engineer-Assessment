# Northwind Scheduling Assistant

A Python take-home project for finding mutually available meeting times from a small employee directory and sample calendars. A tool-calling agent interprets requests, while **deterministic scheduling code** validates attendees, calculates free windows, and produces the user-facing results.

This submission focuses on reliability: no fabricated availability, explicit handling of missing calendar data, bounded agent execution, and clear failures when a request cannot be verified. It also adds a **multi-day availability search** as the user-facing feature.

## Quick start

**Requirements:** Python 3.10+ and `pip`. No API key is needed to run the tests or scripted demo.

From the `northwind-scheduler-python` directory:

```powershell
python -m pip install pytest
python -m pytest
python main.py "Find an hour for Priya and Sam on Tuesday afternoon"
```

The default CLI uses a **scripted `FakeModel`**. It demonstrates the agent and tool flow, but does **not** interpret the text you type: without a configured real model, it always makes the same example lookup (Priya and Sam, November 3, 2026, after 12:00). To explore other attendees, dates, or durations without an LLM, use the direct-tool commands under [Manual verification](#manual-verification).

## What it does

- **Single-day scheduling:** Computes available windows for one or more validated employees.
- **Multi-day scheduling (added feature):** Searches an inclusive date range, skips weekends, and returns a capped shortlist across covered dates rather than favoring one busy-free day.
- **Correct time boundaries:** Uses a 09:00–17:00 workday divided into 30-minute slots; respects `earliest` and `latest` time bounds and includes the last valid window of the day.
- **Safe duration handling:** Rounds a requested duration *up* to a full 30-minute slot boundary (for example, 45 minutes reserves 60 minutes) and discloses that in the answer.
- **Fail-closed validation:** Rejects unknown employee IDs, invalid dates/times/durations, missing calendar coverage, and malformed stored busy intervals instead of claiming unsupported availability.
- **Grounded responses:** The LLM's `final` message only signals completion. Meeting times and people in the displayed response are generated from validated tool results, not copied from model prose.
- **Agent safeguards:** Validates the action JSON and tool arguments, handles model/tool errors without crashing, and limits agent turns and consecutive errors.
- **Data minimization:** Exposes employee IDs, names, and titles only; busy-time results exclude meeting names and details.

## Manual verification

The sample employees include `priya`, `sam`, `dana`, `luis`, `mei`, and `arjun`. Calendar coverage is **November 2–4, 2026**.

These PowerShell commands call the scheduling tools directly, so the input really changes what gets searched.

**Known availability:**

```powershell
python -c "from scheduler.store import Store; from scheduler.tools import find_free_slots; print(find_free_slots(Store.load(), ['priya', 'sam'], '2026-11-03', 60, earliest='12:00'))"
```

Expected result:

```python
[{'start': '13:00', 'end': '14:00'}, {'start': '16:00', 'end': '17:00'}]
```

**Added feature — search several days:**

```powershell
python -c "from scheduler.store import Store; from scheduler.tools import find_free_slots_in_range; print(find_free_slots_in_range(Store.load(), ['priya', 'sam'], '2026-11-02', '2026-11-06', 60, earliest='12:00', max_results=5))"
```

The result contains `slots`, `truncated` (whether other valid windows were omitted), and `unavailable_dates` (covered dates are November 2–4; November 5–6 have **unknown** availability, not free calendars).

**Negative case — nonexistent employee:**

```powershell
python -c "from scheduler.store import Store; from scheduler.tools import find_free_slots; print(find_free_slots(Store.load(), ['alice', 'priya'], '2026-11-03', 60))"
```

Expected: a `ToolError` identifying the unknown attendee. The command exits with an error intentionally; the agent catches this class of error and returns a safe message.

**Optional interactive helper:** If you've copied `manual_check.py` beside `main.py`, you can also run `python manual_check.py` for a menu or `python manual_check.py --smoke` for targeted checks. This helper is not required by the submission or test suite.

## How the agent works

```text
Employee request
      |
      v
Model: JSON tool action  -->  Strict action/argument validation
                                    |
                                    v
                           Scheduling tools + Store
                           - list_people
                           - get_busy_times
                           - find_free_slots
                           - find_free_slots_in_range
                                    |
                                    v
                         Validated tool result
                                    |
                Model completion signal ("final")
                                    |
                                    v
                     Deterministic response formatter
                                    |
                                    v
                   Verified result or safe fallback
```

The model chooses which tool to call and supplies arguments; it does not determine whether a time is free. `scheduler/responses.py` renders supported, successful tool results. The agent refuses to turn an unverified or failed result into a meeting recommendation.

## Project structure

```text
northwind-scheduler-python/
├── main.py                 # CLI entry point / scripted demo
├── pyproject.toml          # Python package and pytest configuration
├── data/
│   ├── people.json         # Sample employee directory
│   └── calendars.json      # Sparse busy-time sample
├── scheduler/
│   ├── agent.py            # Bounded tool-calling loop and error handling
│   ├── responses.py        # Deterministic, grounded user responses
│   ├── tools.py            # Validated scheduling and lookup functions
│   ├── slots.py            # Time-slot and free-window calculation
│   ├── store.py            # Sample-data loading and integrity checks
│   ├── prompts.py          # System/tool guidance
│   ├── model.py            # Model interface and FakeModel
│   └── real_model.py       # Optional OpenAI-compatible adapter
├── tests/                  # pytest regression suite
├── NOTES.md                # Investigation, fixes, AI use, and trade-offs
└── README.md
```

## Test coverage

```powershell
python -m pytest -q
```

The verified submission has **96 passing tests**. Tests cover the final-window boundary, overlapping calendars, duration rounding, valid/invalid inputs, unknown attendees, unavailable calendar dates, multi-day result limits and distribution, corrupt calendar intervals, fabricated model answers, malformed actions, error recovery, and loop limits. Tests use `FakeModel`; no paid LLM is required.

## Optional real-model mode

`main.py` selects `OpenAICompatibleModel` when both `LLM_BASE_URL` and `LLM_MODEL` are set. For example, with a compatible local server already running and the model installed:

```powershell
$env:LLM_BASE_URL = "http://localhost:11434/v1"
$env:LLM_MODEL = "llama3.1"
python main.py "Find 30 minutes with Mei and Luis on Tuesday"
```

**Note:** Natural-language interpretation depends on the chosen model. The application verifies calendar results for the tool arguments the model produced, but it does not independently prove that the model interpreted every condition in the original sentence correctly.

## Data assumptions and boundaries

- The sample dates are November **2–4, 2026**, and the agent's reference "today" is **November 2, 2026** (not your computer's current date).
- This is a **sparse, busy-only export**: a missing employee entry on an otherwise covered date means no recorded conflict; a date missing from *all* calendars means unknown coverage, not guaranteed availability.
- Single-day searches reject unsupported dates. Range searches report unsupported weekdays in `unavailable_dates` and do not present them as free.
- Range searches span up to **14 calendar days**, cap returned windows at **20**, and show `truncated` when more available windows exist.
- This project **finds times only**. It does not create calendar events, send invitations, persist bookings, or implement authentication/time zones.

## Implementation notes

See [`NOTES.md`](NOTES.md) for the reproduced starter defects, fixes and adjusted test expectations, the Part B feature rationale, use of AI assistance, and consciously deferred production improvements.
