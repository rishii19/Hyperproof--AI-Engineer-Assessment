import pytest

from scheduler.store import Store
from scheduler.tools import (
    ToolError,
    find_free_slots,
    find_free_slots_in_range,
    get_busy_times,
)


def test_get_busy_times():
    store = Store.load()
    busy = get_busy_times(store, "sam", "2026-11-04")
    assert busy == [{"start": "09:00", "end": "09:30"}]


def test_get_busy_times_withholds_meeting_titles():
    store = Store.load()
    busy = get_busy_times(store, "dana", "2026-11-03")
    # "Reorg discussion (confidential)" is none of the agent's business.
    assert busy == [{"start": "11:00", "end": "12:00"}]


def test_find_free_slots_for_two_people_in_the_afternoon():
    store = Store.load()
    slots = find_free_slots(
        store,
        attendees=["priya", "sam"],
        date="2026-11-03",
        duration_minutes=30,
        earliest="13:00",
    )
    assert slots == [
        {"start": "13:00", "end": "13:30"},
        {"start": "13:30", "end": "14:00"},
        {"start": "15:00", "end": "15:30"},
        {"start": "16:00", "end": "16:30"},
        {"start": "16:30", "end": "17:00"},
    ]


def test_find_free_slots_hour_long_meeting():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["priya", "sam"], date="2026-11-03", duration_minutes=60
    )
    assert {"start": "13:00", "end": "14:00"} in slots


def test_find_free_slots_includes_the_last_slot_of_the_day():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30
    )
    assert slots[0] == {"start": "09:00", "end": "09:30"}
    assert slots[-1] == {"start": "16:30", "end": "17:00"}
    assert len(slots) == 16


def test_find_free_slots_rounds_duration_up_to_whole_slots():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=45
    )
    # 45 minutes needs two 30-minute slots, not one.
    assert slots[0] == {"start": "09:00", "end": "10:00"}
    assert len(slots) == 15


def test_find_free_slots_rejects_bad_durations():
    store = Store.load()
    for duration in [0, -30, 481, "30", 30.0, None, True]:
        with pytest.raises(ToolError):
            find_free_slots(
                store, attendees=["luis"], date="2026-11-02",
                duration_minutes=duration,
            )


def test_earliest_rounds_up_and_latest_rounds_down():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="13:10", latest="15:50",
    )
    # 13:10 rounds up to 13:30; 15:50 rounds down to 15:30.
    assert slots == [
        {"start": "13:30", "end": "14:00"},
        {"start": "14:00", "end": "14:30"},
        {"start": "14:30", "end": "15:00"},
        {"start": "15:00", "end": "15:30"},
    ]


def test_bounds_outside_the_working_day_are_clamped():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="06:00", latest="23:00",
    )
    assert len(slots) == 16


def test_find_free_slots_rejects_bad_bounds():
    store = Store.load()
    bad = [
        {"earliest": "14:00", "latest": "14:00"},
        {"earliest": "15:00", "latest": "13:00"},
        {"earliest": "9am"},
        {"latest": "25:00"},
        {"earliest": "1300"},
        {"latest": "13:60"},
    ]
    for bounds in bad:
        with pytest.raises(ToolError):
            find_free_slots(
                store, attendees=["luis"], date="2026-11-02",
                duration_minutes=30, **bounds,
            )


def test_unknown_attendee_error_lists_unknown_and_valid_ids():
    store = Store.load()
    with pytest.raises(ToolError) as excinfo:
        find_free_slots(
            store, attendees=["priya", "bob"], date="2026-11-02",
            duration_minutes=30,
        )
    message = str(excinfo.value)
    assert "bob" in message
    assert "priya" in message and "luis" in message  # the valid ids


def test_find_free_slots_rejects_bad_attendees():
    store = Store.load()
    for attendees in [[], "priya", None, ["priya", 7], {"id": "priya"}]:
        with pytest.raises(ToolError):
            find_free_slots(
                store, attendees=attendees, date="2026-11-02",
                duration_minutes=30,
            )


def test_find_free_slots_rejects_bad_dates():
    store = Store.load()
    for date in ["2026-11-07", "2026-11-08", "next Tuesday", "11/03/2026",
                 "2026-13-01", None]:
        with pytest.raises(ToolError):
            find_free_slots(
                store, attendees=["luis"], date=date, duration_minutes=30,
            )


def test_get_busy_times_rejects_unknown_person():
    store = Store.load()
    with pytest.raises(ToolError) as excinfo:
        get_busy_times(store, "bob", "2026-11-02")
    assert "bob" in str(excinfo.value)


def test_tool_error_is_a_value_error():
    assert issubclass(ToolError, ValueError)


# --- find_free_slots_in_range -------------------------------------------


def test_find_free_slots_in_range_orders_results_by_date_then_time():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-04", duration_minutes=30, earliest="16:00",
    )
    # Luis has "User interviews" 16:00-17:00 on the 3rd, so that day
    # contributes nothing and the 2nd runs straight into the 4th.
    assert results == [
        {"date": "2026-11-02", "start": "16:00", "end": "16:30"},
        {"date": "2026-11-02", "start": "16:30", "end": "17:00"},
        {"date": "2026-11-04", "start": "16:00", "end": "16:30"},
        {"date": "2026-11-04", "start": "16:30", "end": "17:00"},
    ]
    keys = [(r["date"], r["start"]) for r in results]
    assert keys == sorted(keys)


def test_find_free_slots_in_range_agrees_with_the_single_day_tool_for_a_single_day():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["priya", "sam"], start_date="2026-11-03",
        end_date="2026-11-03", duration_minutes=30, earliest="13:00",
        max_results=20,
    )
    single_day = find_free_slots(
        store, attendees=["priya", "sam"], date="2026-11-03",
        duration_minutes=30, earliest="13:00",
    )
    assert [{"date": "2026-11-03", **slot} for slot in single_day] == results


def test_find_free_slots_in_range_agrees_with_the_single_day_tool_across_days():
    store = Store.load()
    # Whichever windows the round-robin picks, each one has to be a window
    # find_free_slots would have offered for that same date on its own.
    results = find_free_slots_in_range(
        store, attendees=["priya", "sam"], start_date="2026-11-02",
        end_date="2026-11-06", duration_minutes=60, max_results=20,
    )
    assert results
    per_day = {}
    for row in results:
        date = row["date"]
        if date not in per_day:
            per_day[date] = find_free_slots(
                store, attendees=["priya", "sam"], date=date,
                duration_minutes=60,
            )
        assert {"start": row["start"], "end": row["end"]} in per_day[date]


def test_find_free_slots_in_range_skips_saturday_and_sunday():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-06",
        end_date="2026-11-09", duration_minutes=30, earliest="16:00",
        max_results=20,
    )
    # Friday the 6th, then straight to Monday the 9th.
    assert [r["date"] for r in results] == [
        "2026-11-06", "2026-11-06", "2026-11-09", "2026-11-09",
    ]


def test_find_free_slots_in_range_rejects_a_range_with_no_weekdays():
    store = Store.load()
    # A range of nothing but weekend searches nothing at all. Returning []
    # reads as "everyone is busy", so name the real problem instead.
    for start_date, end_date in [
        ("2026-11-07", "2026-11-08"),  # Saturday to Sunday
        ("2026-11-07", "2026-11-07"),  # a single Saturday
    ]:
        with pytest.raises(ToolError) as excinfo:
            find_free_slots_in_range(
                store, attendees=["luis"], start_date=start_date,
                end_date=end_date, duration_minutes=30,
            )
        message = str(excinfo.value)
        assert start_date in message and end_date in message
        assert "weekend" in message.lower()


def test_find_free_slots_in_range_accepts_a_weekend_start_or_end():
    store = Store.load()
    # Unlike find_free_slots, the bounds of a range may fall on a weekend:
    # only the days searched have to be weekdays.
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-07",
        end_date="2026-11-09", duration_minutes=30, earliest="16:00",
    )
    assert [r["date"] for r in results] == ["2026-11-09", "2026-11-09"]


def test_find_free_slots_in_range_spreads_its_five_results_across_days():
    # Was test_find_free_slots_in_range_defaults_to_five_results, which
    # expected all five from the 2nd: the results are round-robined over
    # the days now, so a free Monday no longer fills the whole list.
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-04", duration_minutes=30,
    )
    # 3 days x 5 results forces a second round, so this pins rank order,
    # not just day coverage.
    assert results == [
        {"date": "2026-11-02", "start": "09:00", "end": "09:30"},
        {"date": "2026-11-02", "start": "09:30", "end": "10:00"},
        {"date": "2026-11-03", "start": "09:00", "end": "09:30"},
        {"date": "2026-11-03", "start": "09:30", "end": "10:00"},
        {"date": "2026-11-04", "start": "09:00", "end": "09:30"},
    ]


def test_find_free_slots_in_range_returns_everything_under_max_results():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-03", duration_minutes=30, earliest="15:00",
        max_results=10,
    )
    # Six windows in all, so nothing is dropped and date-then-time order
    # survives the round-robin.
    assert results == [
        {"date": "2026-11-02", "start": "15:00", "end": "15:30"},
        {"date": "2026-11-02", "start": "15:30", "end": "16:00"},
        {"date": "2026-11-02", "start": "16:00", "end": "16:30"},
        {"date": "2026-11-02", "start": "16:30", "end": "17:00"},
        {"date": "2026-11-03", "start": "15:00", "end": "15:30"},
        {"date": "2026-11-03", "start": "15:30", "end": "16:00"},
    ]


def test_find_free_slots_in_range_skips_an_empty_day_without_spending_the_cap():
    store = Store.load()
    # Luis is in user interviews 16:00-17:00 on the 3rd, so that day offers
    # nothing after 16:00. Its turn passes to the next day with free time
    # rather than costing one of the two results.
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-04", duration_minutes=30, earliest="16:00",
        max_results=2,
    )
    assert results == [
        {"date": "2026-11-02", "start": "16:00", "end": "16:30"},
        {"date": "2026-11-04", "start": "16:00", "end": "16:30"},
    ]


def test_find_free_slots_in_range_truncates_to_max_results():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-04", duration_minutes=30, max_results=2,
    )
    assert len(results) == 2


def test_find_free_slots_in_range_caps_max_results_at_twenty():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-04", duration_minutes=30, max_results=500,
    )
    # The three days offer 43 slots between them, so the cap - not the
    # calendar - is what stops the search, and every day is represented.
    assert len(results) == 20
    assert {r["date"] for r in results} == {
        "2026-11-02", "2026-11-03", "2026-11-04",
    }


def test_find_free_slots_in_range_rejects_bad_max_results():
    store = Store.load()
    for max_results in [0, -1, "5", 5.0, None, True]:
        with pytest.raises(ToolError):
            find_free_slots_in_range(
                store, attendees=["luis"], start_date="2026-11-02",
                end_date="2026-11-04", duration_minutes=30,
                max_results=max_results,
            )


def test_find_free_slots_in_range_rejects_an_end_before_the_start():
    store = Store.load()
    with pytest.raises(ToolError) as excinfo:
        find_free_slots_in_range(
            store, attendees=["luis"], start_date="2026-11-04",
            end_date="2026-11-02", duration_minutes=30,
        )
    message = str(excinfo.value)
    assert "2026-11-04" in message and "2026-11-02" in message


def test_find_free_slots_in_range_rejects_a_range_longer_than_two_weeks():
    store = Store.load()
    with pytest.raises(ToolError) as excinfo:
        find_free_slots_in_range(
            store, attendees=["luis"], start_date="2026-11-02",
            end_date="2026-11-16", duration_minutes=30,
        )
    assert "14" in str(excinfo.value)


def test_find_free_slots_in_range_allows_exactly_fourteen_days():
    store = Store.load()
    results = find_free_slots_in_range(
        store, attendees=["luis"], start_date="2026-11-02",
        end_date="2026-11-15", duration_minutes=30,
    )
    assert len(results) == 5


def test_find_free_slots_in_range_rejects_bad_dates():
    store = Store.load()
    bad = [
        {"start_date": "next Tuesday", "end_date": "2026-11-04"},
        {"start_date": "2026-11-02", "end_date": "11/04/2026"},
        {"start_date": "2026-13-01", "end_date": "2026-11-04"},
        {"start_date": "2026-11-02", "end_date": None},
    ]
    for dates in bad:
        with pytest.raises(ToolError):
            find_free_slots_in_range(
                store, attendees=["luis"], duration_minutes=30, **dates
            )


def test_find_free_slots_in_range_rejects_unknown_attendees():
    store = Store.load()
    with pytest.raises(ToolError) as excinfo:
        find_free_slots_in_range(
            store, attendees=["priya", "bob"], start_date="2026-11-02",
            end_date="2026-11-04", duration_minutes=30,
        )
    message = str(excinfo.value)
    assert "bob" in message
    assert "priya" in message and "luis" in message  # the valid ids


def test_find_free_slots_in_range_validates_even_with_no_weekdays_to_search():
    store = Store.load()
    # A Saturday-to-Sunday range searches nothing, but a bad argument is
    # still a bad argument: the model should hear about it, not get [].
    for kwargs in [
        {"attendees": ["bob"], "duration_minutes": 30},
        {"attendees": ["luis"], "duration_minutes": 0},
        {"attendees": ["luis"], "duration_minutes": 30, "earliest": "9am"},
        {"attendees": ["luis"], "duration_minutes": 30,
         "earliest": "15:00", "latest": "13:00"},
    ]:
        with pytest.raises(ToolError):
            find_free_slots_in_range(
                store, start_date="2026-11-07", end_date="2026-11-08",
                **kwargs,
            )


def test_find_free_slots_in_range_is_registered_as_a_tool():
    from scheduler.tools import TOOLS

    assert TOOLS["find_free_slots_in_range"] is find_free_slots_in_range


def test_get_busy_times_rejects_weekends_and_unparsable_dates():
    store = Store.load()
    for date in ["2026-11-07", "next tuesday"]:
        with pytest.raises(ToolError) as excinfo:
            get_busy_times(store, "sam", date)
        assert date in str(excinfo.value)


def test_find_free_slots_accepts_a_single_digit_hour():
    store = Store.load()
    slots = find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="9:00", latest="10:00",
    )
    assert slots == [
        {"start": "09:00", "end": "09:30"},
        {"start": "09:30", "end": "10:00"},
    ]
    assert slots == find_free_slots(
        store, attendees=["luis"], date="2026-11-02", duration_minutes=30,
        earliest="09:00", latest="10:00",
    )


def test_find_free_slots_rejects_malformed_or_out_of_range_times():
    store = Store.load()
    for clock in ["24:00", "9:60", "9am", "09:00:00", "09:00\n", "", "9", ":30"]:
        with pytest.raises(ToolError):
            find_free_slots(
                store, attendees=["luis"], date="2026-11-02",
                duration_minutes=30, earliest=clock,
            )
