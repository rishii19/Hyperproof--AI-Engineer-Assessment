# NOTES

All work is in `northwind-scheduler-python`. Baseline is commit `9606b16` (the starter, untouched), so every change reads as a diff against what I inherited. Tests: 11 at baseline, 72 now, all run with `python -m pytest`. Most new tests are regression tests, each written to fail before its fix.

**Time:** about 3 hours of focused work, spread over an afternoon with breaks (first commit 13:32, last 20:13). That is over the suggested 2. The overrun went into the independent verification passes described below and the 12 fixes they found.

## Problems found

How found: reading the code, a probe script against the sample data, then independent verification passes that never edited the repo: a minute-resolution oracle (637,632 cases, 0 mismatches; re-injecting the original off-by-one gets caught 16,081 times), 4,010 agent fuzz runs (0 raises), a taint sweep of every model-visible string (0 leaks), and mutation tests on the key behaviours.

**Correct results (R1)**
- **Last window of the day was never offered.** `find_free_windows` looped `range(start, end - n)`, one short. 16:30–17:00 was unreachable. Fixed the bound. (`155f444`)
- **An existing test encoded that bug.** `test_find_free_slots_for_two_people_in_the_afternoon` expected no 16:30 slot, but Priya and Sam are both free then. I added 16:30–17:00 to its expectation; this is a changed test, justified by the fix above.
- **45-minute meetings were searched as 30.** `duration // 30` floors, so it offered 15:00 although Sam is busy from 15:30. Durations now round up to whole slots. Zero, negative, non-integer and boolean durations are rejected; JSON `true` would otherwise count as 1. (`9bfbe41`)
- **Search bounds could produce impossible times.** `earliest="08:00"` offered 08:00 because a negative slot slices to an empty list, which `all()` treats as free. `earliest="12:15"` offered 12:00 because it rounded down. Now `earliest` rounds up, `latest` rounds down, both are clamped to 09:00–17:00, and inverted bounds are rejected. `H:MM` or `HH:MM` is accepted; anything else is rejected. (`83313cb`, `54d0ae2`)

**No invented people (R2)**
- **Unknown attendees were treated as free all day.** `calendars.get(person, {})` gave anyone not in the directory an empty calendar, and an empty attendee list meant everyone was free. Tools now raise `ToolError` naming the unknown ids and listing the valid ones, so the model can correct itself or tell the user. Dates are validated as `YYYY-MM-DD` weekdays, in `get_busy_times` too. (`cfbd160`, `79883ff`)

**Graceful failure (R3)**
- **The agent crashed on malformed model output.** It used unguarded `json.loads`, `TOOLS[...]` and `**args`. Every failure is now fed back to the model as a tool error. That covers non-JSON output, a non-object reply, an unknown tool, bad `args` and a non-string `final`. One fenced JSON block is accepted even with prose around it. (`a9f1af8`, `113f2ab`)
- **A failing model call raised out of `run()`.** It now returns a fixed fallback answer. (`ab19c25`)
- **Model mistakes and our own bugs were indistinguishable.** A model passing bad arguments now gets a specific message naming every missing or unexpected argument. An internal exception or an unserialisable result gets a generic message with no internals exposed. (`dccfa10`, `b172cc3`, `cb89f58`)

**Always finishes (R4)**
- **The loop could run forever.** It was a bare `while True`. Now capped at 8 model calls and 3 consecutive errors, after which it returns the fallback. The real-model HTTP request has a 30 s timeout. (`1527931`)

**Privacy**
- **Personal and confidential data reached the model.** Phone numbers, emails and home cities were in the system prompt and in `list_people`. Meeting titles such as "Reorg discussion (confidential)" came back from `get_busy_times`. Now only `id`, `name` and `title` are exposed, and busy blocks carry no titles. Tests check every person's details, not just one person's. (`0ca0651`, `24b9e73`, `756abbf`)
- **Changed existing tests (all three):** `test_get_busy_times` no longer expects `title` (intended redaction). `test_find_free_slots_for_two_people_in_the_afternoon` now includes 16:30–17:00 (it encoded the off-by-one). `test_system_prompt_includes_directory` gained an assertion and lost none. (`155f444` for the afternoon test; `0ca0651` for the other two)

## My addition: date-range search

`find_free_slots_in_range` finds a time across up to 14 days in one call ("30 minutes with Mei and Luis this week"). It helps any employee whose request names a week rather than a day, which is most requests. Before this, the model had to call the day tool once per day.

- It reuses `find_free_slots` per weekday, so every R1/R2 fix applies automatically.
- Results are spread across days round-robin (earliest window of each day first), so one open day can't crowd out the rest.
- It returns `{"slots": [...], "truncated": bool}`. The prompt tells the model never to describe omitted days as busy. A range containing no weekdays is rejected rather than returned empty. I chose a flag over sampling every day because it keeps the selection rule already verified, and it tells the model the truth instead of hiding the gap.
- The prompt's description reads its limits from the same constants the tool enforces, and a test fails if the two drift apart.
- Tests cover round-robin rank order, weekend skipping and rejection, the result cap, `truncated`, and agreement with the day tool across days; mutation checks run in the review sessions (not committed) confirmed each rule is pinned.
- Commits: `5575389` → `1c82336`.

I chose this over two alternatives. Listing near-miss times and who blocks each would be useful, but its ranking rules are debatable within a small timebox. Friendly-name resolution is partly covered already by the unknown-id error message.

## How I used AI tools

I used three roles, kept separate on purpose:

- **Planner (Claude chat):** read the starter, listed the defects, wrote a requirements doc and a commit-by-commit plan, and helped me triage every review finding into fix / leave / note.
- **Implementer (Claude Code):** one commit per step, test first, suite green before each commit.
- **Reviewer (fresh Claude Code sessions):** never edited the repo. Built independent oracles (minute-resolution slot checker, agent fuzzer, taint sweep, mutation tests) and reported defects. A fresh session checks the work instead of defending it.

The planner proposed a fix/leave call for each review finding; I reviewed and approved each one before it went to the implementer.

Where I rejected or corrected AI output:

- **A privacy test that guarded nothing.** The AI-written test asserted `"manager" not in system`. It passed only because job titles use a capital M ("Engineering Manager"). A reviewer injected a `"Manager"` key and the suite stayed green. I replaced it with checks built from `people.json` for all six people. An earlier review had already found `list_people` still leaking phones and emails despite a commit titled "Keep personal details out of the model's context" (`24b9e73`, `756abbf`).
- **A correct fix with a worse side effect.** The suggested way to separate model mistakes from our own bugs was `inspect.signature().bind()`. It classified errors correctly, but its message names only the first missing argument, so a model fixing one argument per turn ran out of its three-error budget. I replaced it with a message listing every missing and unexpected argument (`b172cc3`, `cb89f58`).
- **Tests and prompts that described the code wrong.** The range tool's own test pinned five Monday results as correct, which encoded the bug. Later the prompt twice promised coverage the tool didn't deliver. I tied the prompt to the constants the tool enforces and added a test that fails if they drift (`6839e4a`, `f466843`, `6ec0d8a`).
- **A reviewer's wrong evidence.** One review said Thursday and Friday were "completely open". They only looked open because there is no calendar data for those days. The bug it pointed at was real; the evidence wasn't.

Lesson: the AI's confident "done" was wrong several times, so every claim got an independent check before I accepted it.

## What I'd do next

- **Check the final answer against tool results.** The model's reply is free text and could state a time or include a person that no tool returned. The guarantees here stop at the tool layer.
- **Distinguish "free" from "no calendar data".** Dates outside the sample files currently read as fully free.
- **Count distinct free periods for `truncated`, not overlapping windows.** At the default, it is true on almost every call.
- **Tell the user when a duration was rounded up** (45 minutes searched as 60).
- **Validate busy blocks at the store boundary.** Zero-length and reversed blocks are handled inconsistently. The sample data has none, so I left it.

**Deliberately left alone:**
- The real-model adapter's message format.
- The 30-minute slot granularity, which is a product decision.
- Positional-only tool parameters, which no tool uses.
- Redundant per-day validation in the range tool, and duplicate attendee ids (harmless).
- Test-margin findings: one test per mutant on round-robin and `truncated`; bare-digit matching in the prompt test (safe while the text comes from constants).
- The TypeScript version: I fixed one repo well rather than two partially.
