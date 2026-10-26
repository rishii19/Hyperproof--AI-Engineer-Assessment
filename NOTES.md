# NOTES — Northwind Scheduling Assistant (Python)

## Scope and verification

I kept the inherited three-layer architecture (fixed slots, tools, model loop) and the **date-range search** from my first pass. This follow-up hardening pass closes the trust boundary between tools and final answers. The starter had 11 tests; the finished suite has **96 passing tests**, run with the original `python -m pytest` command and `FakeModel` (no paid LLM). I prioritized correctness and independent checks over adding more features.

## Part A — Bugs, how I found them, and fixes

I read the code, checked boundary cases against the sample calendars, and used scripted malicious/malformed model responses to reproduce failures before fixing them.

- **Missed valid times:** `find_free_windows` excluded the final starting slot (e.g. 16:30–17:00). Fixed the inclusive upper bound. The old afternoon test was changed because its expectation encoded the bug.
- **False 45-minute meetings:** integer division treated 45 minutes as one 30-minute slot. Durations now round *up*, reject invalid values, and the user-facing response explicitly says when 45 minutes reserves 60.
- **Wrong search boundaries:** negative slots and floor-rounded `earliest` could offer out-of-hours or too-early meetings. Validate HH:MM, ceil earliest, floor latest, clamp to 09:00–17:00, and reject inverted bounds.
- **Invented attendees:** unknown IDs previously had an empty calendar and appeared free. Tools reject unknown or empty attendees and invalid dates. The agent now surfaces unknown attendees to the user and does not recommend a meeting after an unresolved unknown-ID error, even if the model tries again with a smaller group.
- **Hallucinated final answers (reproduced after the first pass):** a model could ignore an invalid-attendee tool error, invent a free time, or answer without querying tools. The `final` string now only signals completion: `scheduler/responses.py` deterministically renders validated `find_free_slots`, date-range, directory, or busy-time tool output. Without a verified result, the agent declines to suggest times. If a later tool call fails, an older successful result is invalidated so its constraints cannot be mistaken for the newer request.
- **Missing calendar dates (reproduced after the first pass):** `.get(date, [])` advertised unrecorded future dates as wholly free. The export is sparse *within* the dates occurring anywhere in the supplied calendars; dates absent from **all** calendars are unknown. Single-day tools fail closed. Date-range searches skip uncovered weekdays, return `unavailable_dates`, and clearly disclose partial coverage; all-unknown ranges fail. This avoids claiming unknown dates are free or busy.
- **Malformed model output/tool failures:** parse JSON (or exactly one fenced block), validate a single action with only permitted keys, handle nonexistent tools and missing/wrong arguments, distinguish bad arguments from internal tool failures, and avoid leaking internal exception text. A failed model call returns a safe message.
- **Infinite calls:** the agent has an 8-step budget and a three-consecutive-error limit; the optional HTTP adapter has a timeout.
- **Corrupt calendar intervals:** zero-length, reversed, invalid, or missing time values could otherwise be treated as free. Validate busy intervals on file load and make the slot core fail closed for reversed/zero-length blocks.
- **Unnecessary personal data:** the prompt and directory tool expose only `id`, `name`, `title`; busy-time tools withhold meeting titles and details.

**Existing tests changed deliberately:** the afternoon-window expectation was corrected; the busy-time test stopped expecting confidential meeting titles; the directory-prompt test strengthened redaction checks. In this pass, agent tests that previously asserted an arbitrary `final("Recovered.")` or a made-up meeting response now expect grounded output or a safe fallback. Weekend range tests use *explicit synthetic calendar coverage* instead of relying on unrecorded dates appearing free. These changes tighten expectations rather than remove coverage. Regression tests now explicitly cover fabricated people/times, unknown-ID errors followed by success, corrupt tool result shapes, stale results, partial coverage, and 45-to-60-minute rounding.

## Part B — Feature: search across a date range

`find_free_slots_in_range` lets employees ask for slots *this week* without one model/tool turn per day. It reuses the trusted per-day search, skips weekends, spans at most 14 days, caps returned windows at 20, and uses round-robin day sampling to avoid one free day crowding out the list. `truncated` reports omitted valid windows; `unavailable_dates` reports days where availability is **unknown**. I chose this over ranking near misses or adding another framework because it solves a common user problem using the existing core. Tests cover day order, boundaries, coverage, limits, sampling, and agreement with the day tool.

## AI usage and engineering judgment

I used Claude chat for the original review/plan, Claude Code for incremental implementation, and separate AI-assisted review passes to challenge the work. For this final hardening pass, I used ChatGPT to inspect the submission, reproduce final-answer failures, and propose targeted patches and tests; I reviewed the resulting behavior with `FakeModel` and the full pytest suite. The Git history preserves incremental changes.

Concrete cases where I **corrected or rejected AI output**:

- An AI-generated privacy test checked lowercase `"manager"` and missed capitalized occurrences. I replaced it with data-derived checks for *every* employee and checked both prompt and tool output.
- Signature-binding feedback reported only the first missing argument, wasting the agent's error budget. I changed it to list all missing/unexpected arguments in one response.
- A model-generated final answer looked plausible even after a correct tool error. Adding more prompt warnings was not sufficient: I moved user-facing meeting recommendations out of the model and into deterministic code.
- An earlier range-search test/prompt implied omitted dates were busy. I corrected the sampling/truncation wording and made missing coverage explicit rather than trusting the claim.

## Next steps / deliberate limits

- **Natural-language intent verification:** the agent trusts the model to translate the request into *tool arguments*. It guarantees that displayed windows match those validated arguments, but it cannot prove that the model selected every person or interpreted every constraint in the original sentence correctly. A future version would use structured user confirmation or a typed intent layer before searching.
- **Calendar coverage assumption:** this sample uses sparse busy-only calendars. A real integration needs explicit sync status and per-person coverage; the union-of-recorded-dates rule is only a documented assumption for these sample files.
- More nuanced recovery from an unknown ID (e.g., asking the user to disambiguate a similar name) would require a confirmation turn; this implementation deliberately refuses an unverified meeting.
- I did **not** add UI, calendar writes/invitations, time zones, authentication, deployment, a different framework, or a real-model dependency: the assignment expressly excludes them.
