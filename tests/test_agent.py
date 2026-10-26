import json

import pytest

from scheduler import agent as agent_module
from scheduler.agent import SchedulingAgent
from scheduler.model import FakeModel, final, tool_call
from scheduler.store import Store
from scheduler.tools import ToolError, find_free_slots


def withheld_values() -> list[str]:
    """Every value in the directory the model is not allowed to see.

    Built from the data rather than listed by hand, so a new person - or a
    new contact detail on an existing one - is covered without the test
    being updated. Manager ids are ordinary person ids, so they are checked
    as the JSON key that would carry them.
    """
    secrets = []
    for person in Store.load().people:
        secrets += [person["email"], person["phone"], person["home_city"]]
        if person["manager"] is not None:
            secrets.append('"manager"')
    return secrets


def test_agent_returns_final_answer():
    model = FakeModel([final("Happy to help!")])
    agent = SchedulingAgent(model, Store.load())
    assert agent.run("hello") == "Happy to help!"


def test_agent_calls_tool_and_returns_result_to_model():
    model = FakeModel([
        tool_call("find_free_slots", attendees=["priya", "sam"],
                  date="2026-11-03", duration_minutes=60, earliest="12:00"),
        final("13:00 works for both."),
    ])
    agent = SchedulingAgent(model, Store.load())

    answer = agent.run("Find an hour for Priya and Sam on Tuesday afternoon")

    assert answer == "13:00 works for both."
    second_call = model.calls[1]
    assert second_call[-1]["role"] == "tool"
    assert {"start": "13:00", "end": "14:00"} in json.loads(second_call[-1]["content"])


def test_system_prompt_includes_directory():
    model = FakeModel([final("ok")])
    SchedulingAgent(model, Store.load()).run("hi")
    system = model.calls[0][0]["content"]
    assert "Priya Raman" in system
    assert "Engineering Manager" in system


def test_system_prompt_omits_personal_contact_details():
    model = FakeModel([final("ok")])
    SchedulingAgent(model, Store.load()).run("hi")
    system = model.calls[0][0]["content"]
    for secret in withheld_values() + ["email", "phone", "home_city"]:
        assert secret not in system, secret


def test_agent_strips_a_json_code_fence():
    model = FakeModel(["```json\n" + final("Fenced answer") + "\n```"])
    assert SchedulingAgent(model, Store.load()).run("hi") == "Fenced answer"


def test_agent_feeds_malformed_json_back_to_the_model():
    model = FakeModel(["I think Tuesday works?", final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    feedback = model.calls[1][-1]
    assert feedback["role"] == "tool"
    assert "error" in json.loads(feedback["content"])


def test_agent_reports_badly_shaped_actions():
    bad_replies = [
        json.dumps({"tool": "teleport", "args": {}}),      # unknown tool
        json.dumps({"tool": "list_people", "args": "no"}),  # args not an object
        json.dumps({"tool": "list_people"}),                # args missing
        json.dumps({"final": 42}),                          # final not a string
        json.dumps({"hello": "world"}),                     # neither key
        json.dumps(["list_people"]),                        # not an object
    ]
    for raw in bad_replies:
        model = FakeModel([raw, final("Recovered.")])
        answer = SchedulingAgent(model, Store.load()).run("hi")
        assert answer == "Recovered."
        feedback = model.calls[1][-1]
        assert feedback["role"] == "tool"
        assert "error" in json.loads(feedback["content"]), raw


def test_agent_feeds_tool_errors_back_to_the_model():
    model = FakeModel([
        tool_call("find_free_slots", attendees=["bob"], date="2026-11-02",
                  duration_minutes=30),
        final("Recovered."),
    ])
    store = Store.load()
    agent = SchedulingAgent(model, store)

    assert agent.run("hi") == "Recovered."
    # A ToolError is written for the model, so it reaches it word for word
    # rather than being flattened into the generic failure.
    with pytest.raises(ToolError) as excinfo:
        find_free_slots(store, attendees=["bob"], date="2026-11-02",
                        duration_minutes=30)
    error = json.loads(model.calls[1][-1]["content"])["error"]
    assert error == str(excinfo.value)
    assert "bob" in error


def test_agent_feeds_bad_tool_arguments_back_to_the_model():
    # Arguments are bound before the call, so a bad call list is named for
    # what it is - something the next turn can fix - and never mistaken for
    # the tool falling over.
    bad_calls = [
        (tool_call("list_people", when="now"),
         "list_people: unexpected argument(s): when"),
        (tool_call("get_busy_times", person="sam"),
         "get_busy_times: missing required argument(s): date"),
    ]
    for raw, expected in bad_calls:
        model = FakeModel([raw, final("Recovered.")])
        agent = SchedulingAgent(model, Store.load())

        assert agent.run("hi") == "Recovered."
        error = json.loads(model.calls[1][-1]["content"])["error"]
        assert error == expected, raw
        assert error != agent_module.TOOL_FAILED, raw


def test_agent_survives_an_unexpected_tool_exception(monkeypatch):
    def boom(store):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(agent_module.TOOLS, "list_people", boom)
    model = FakeModel([tool_call("list_people"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    feedback = model.calls[1][-1]["content"]
    assert json.loads(feedback)["error"] == agent_module.TOOL_FAILED
    assert "kaboom" not in feedback


def test_agent_hides_a_type_error_raised_inside_a_tool(monkeypatch):
    def boom(store):
        raise TypeError("unsupported operand type(s) for +: 'int' and 'str'")

    monkeypatch.setitem(agent_module.TOOLS, "list_people", boom)
    model = FakeModel([tool_call("list_people"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    # The call itself was fine, so a TypeError from inside the tool is a bug
    # in the tool. Repeating it as an argument error would only send the
    # model off correcting arguments that were right all along.
    feedback = model.calls[1][-1]["content"]
    assert json.loads(feedback)["error"] == agent_module.TOOL_FAILED
    assert "unsupported operand" not in feedback


def test_agent_survives_an_unserialisable_tool_result(monkeypatch):
    def gives_a_set(store):
        return {"priya", "sam"}

    monkeypatch.setitem(agent_module.TOOLS, "list_people", gives_a_set)
    model = FakeModel([tool_call("list_people"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    feedback = model.calls[1][-1]
    assert feedback["role"] == "tool"
    assert json.loads(feedback["content"])["error"] == agent_module.TOOL_FAILED
    assert "JSON serializable" not in feedback["content"]


def test_agent_gives_up_after_max_steps():
    model = FakeModel([tool_call("list_people")], loop_last=True)
    agent = SchedulingAgent(model, Store.load(), max_steps=8)

    assert agent.run("who is everyone?") == agent_module.FALLBACK_ANSWER
    assert len(model.calls) == 8


def test_agent_gives_up_after_consecutive_errors():
    model = FakeModel(["still not json"], loop_last=True)
    agent = SchedulingAgent(model, Store.load(), max_consecutive_errors=3)

    assert agent.run("hi") == agent_module.FALLBACK_ANSWER
    assert len(model.calls) == 3


def test_consecutive_error_count_resets_after_a_good_tool_call():
    model = FakeModel([
        "nope", "still nope",
        tool_call("list_people"),
        "nope again", "and again",
        final("Got there in the end."),
    ])
    agent = SchedulingAgent(model, Store.load(), max_consecutive_errors=3)

    assert agent.run("hi") == "Got there in the end."


def test_agent_calls_find_free_slots_in_range_across_several_days():
    model = FakeModel([
        tool_call("find_free_slots_in_range", attendees=["priya", "sam"],
                  start_date="2026-11-02", end_date="2026-11-04",
                  duration_minutes=60, earliest="13:00", max_results=5),
        final("The best options are Monday at 14:00 or Tuesday at 13:00."),
    ])
    agent = SchedulingAgent(model, Store.load())

    answer = agent.run("Find an hour for Priya and Sam sometime this week")

    assert answer == "The best options are Monday at 14:00 or Tuesday at 13:00."
    result = json.loads(model.calls[1][-1]["content"])
    # Five results drawn a day at a time, so the model sees all three days
    # rather than three near-identical options from the 2nd. The three days
    # hold twelve hour-long windows between them, so the model is also told
    # the list was cut short.
    assert result == {
        "slots": [
            {"date": "2026-11-02", "start": "14:00", "end": "15:00"},
            {"date": "2026-11-02", "start": "15:30", "end": "16:30"},
            {"date": "2026-11-03", "start": "13:00", "end": "14:00"},
            {"date": "2026-11-03", "start": "16:00", "end": "17:00"},
            {"date": "2026-11-04", "start": "13:00", "end": "14:00"},
        ],
        "truncated": True,
    }


def test_system_prompt_documents_the_range_tool():
    model = FakeModel([final("ok")])
    SchedulingAgent(model, Store.load()).run("hi")
    system = model.calls[0][0]["content"]
    assert "find_free_slots_in_range" in system


def test_system_prompt_states_the_range_tool_contract():
    """Naming the tool is not enough: say the limits it answers within.

    Each of these changes what the model does next. `truncated` says the
    list was cut short; the cap and the 14-day span say how far a second
    search can stretch; the weekend rule says an all-weekend range comes
    back as an error, not as an empty week. The claim that a short list
    reaches every day is not one of them - the round-robin fills up from
    the earliest days and stops - so it must not be here to be believed.
    """
    model = FakeModel([final("ok")])
    SchedulingAgent(model, Store.load()).run("hi")
    # The prompt is wrapped prose, so every phrase below is checked against
    # it with the line breaks flattened: rewrapping a paragraph should not
    # fail a test about what the paragraph says.
    system = " ".join(model.calls[0][0]["content"].split())

    assert "truncated" in system
    assert "capped at 20" in system
    assert "at most 14 days" in system
    assert "no weekday in it is rejected as an error" in system
    assert "every day that has something free" not in system


def test_list_people_withholds_personal_contact_details():
    model = FakeModel([tool_call("list_people"), final("Here they are.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("who works here?") == "Here they are."
    result = model.calls[1][-1]
    assert result["role"] == "tool"
    for secret in withheld_values():
        assert secret not in result["content"], secret
    assert json.loads(result["content"])[0] == {
        "id": "priya", "name": "Priya Raman", "title": "Engineering Manager",
    }


def test_agent_feeds_get_busy_times_date_errors_back_to_the_model():
    for date in ["2026-11-07", "next tuesday"]:
        model = FakeModel([
            tool_call("get_busy_times", person="sam", date=date),
            final("Recovered."),
        ])

        assert SchedulingAgent(model, Store.load()).run("when is Sam busy?") == "Recovered."
        feedback = model.calls[1][-1]
        assert feedback["role"] == "tool"
        assert date in json.loads(feedback["content"])["error"], date


class ExplodingModel:
    """A model whose endpoint is down: every call raises."""

    def __init__(self, error=None):
        self.calls = 0
        self.error = error or TimeoutError("request timed out")

    def complete(self, messages):
        self.calls += 1
        raise self.error


def test_agent_falls_back_when_the_model_call_fails():
    model = ExplodingModel()
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("Find an hour for Priya and Sam") == agent_module.FALLBACK_ANSWER
    assert model.calls == 1  # no retry


def test_agent_finds_a_fenced_action_after_prose():
    model = FakeModel([
        "Let me check their calendars.\n\n```json\n"
        + tool_call("find_free_slots", attendees=["priya", "sam"],
                    date="2026-11-03", duration_minutes=60, earliest="12:00")
        + "\n```\n",
        final("13:00 works for both."),
    ])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("Find an hour on Tuesday afternoon") == "13:00 works for both."
    assert {"start": "13:00", "end": "14:00"} in json.loads(
        model.calls[1][-1]["content"]
    )


def test_agent_rejects_a_reply_with_two_fenced_blocks():
    model = FakeModel([
        "Either of these:\n```json\n" + final("First") + "\n```\n"
        "or\n```json\n" + final("Second") + "\n```",
        final("Recovered."),
    ])
    agent = SchedulingAgent(model, Store.load())

    # Two candidate actions is a guess, not a parse: ask for one instead.
    assert agent.run("hi") == "Recovered."
    assert "error" in json.loads(model.calls[1][-1]["content"])


def test_agent_rejects_an_unfenced_object_buried_in_prose():
    model = FakeModel([
        'I think ' + final("Buried") + ' is the answer.',
        final("Recovered."),
    ])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    assert "error" in json.loads(model.calls[1][-1]["content"])


def argument_error(model: FakeModel) -> str:
    """The error the agent fed back after the first scripted reply."""
    feedback = model.calls[1][-1]
    assert feedback["role"] == "tool"
    return json.loads(feedback["content"])["error"]


def test_an_empty_call_names_the_tool_and_every_argument_it_needs():
    model = FakeModel([tool_call("find_free_slots"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("find us a time") == "Recovered."
    # Every required argument in signature order, so one turn is enough to
    # fix the call. The store is the agent's to pass and earliest/latest
    # have defaults, so neither is anything for the model to supply.
    assert argument_error(model) == (
        "find_free_slots: missing required argument(s): "
        "attendees, date, duration_minutes"
    )


def test_one_error_names_both_the_missing_and_the_unexpected_arguments():
    model = FakeModel([
        tool_call("get_busy_times", person="sam", when="now", why="curious"),
        final("Recovered."),
    ])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("when is Sam busy?") == "Recovered."
    # Both faults in one message: fixing either alone would only earn the
    # same error back with the other half of it.
    assert argument_error(model) == (
        "get_busy_times: missing required argument(s): date; "
        "unexpected argument(s): when, why"
    )


def named_arguments(error: str, clause: str) -> list[str]:
    """The argument names one clause of an argument error lists."""
    for part in error.split("; "):
        prefix = f"{clause}: "
        if prefix in part:
            return part.split(prefix, 1)[1].split(", ")
    return []


class AdaptiveModel:
    """A model that corrects exactly what the last error named, and no more.

    It reads neither the request nor the tool's documentation: every argument
    name it sends is one it was handed, by the test to begin with and by the
    agent's own error message afterwards. Getting the call right after a
    single error is therefore the test that the message named the whole of
    what was wrong with it.
    """

    PLAUSIBLE = {
        "attendees": ["priya", "sam"],
        "date": "2026-11-03",
        "start_date": "2026-11-02",
        "end_date": "2026-11-04",
        "duration_minutes": 60,
    }

    def __init__(self, tool: str, args: dict):
        self.tool = tool
        self.args = dict(args)
        self.errors = 0

    def complete(self, messages: list[dict]) -> str:
        last = messages[-1]
        if last["role"] == "tool":
            result = json.loads(last["content"])
            if not (isinstance(result, dict) and "error" in result):
                return final("Found it.")
            self.errors += 1
            error = result["error"]
            # A KeyError from either line would mean the message named an
            # argument the model had no way to act on.
            for argument in named_arguments(error, "missing required argument(s)"):
                self.args[argument] = self.PLAUSIBLE[argument]
            for argument in named_arguments(error, "unexpected argument(s)"):
                del self.args[argument]
        return tool_call(self.tool, **self.args)


def test_a_model_that_fixes_what_the_error_names_recovers_in_one_turn():
    muddled_calls = [
        ("find_free_slots",
         {"attendee": ["priya"], "day": "2026-11-03"}),
        ("find_free_slots_in_range",
         {"attendees": ["priya", "sam"], "date": "2026-11-03",
          "duration_minutes": 60}),
    ]
    for tool, args in muddled_calls:
        model = AdaptiveModel(tool, args)
        agent = SchedulingAgent(model, Store.load())

        assert agent.run("find us a time") == "Found it.", tool
        assert model.errors == 1, tool


def test_agent_survives_a_tool_with_no_readable_signature(monkeypatch):
    # A builtin has no signature to read, so there is nothing to bind the
    # arguments against. The call goes ahead and whatever it raises is the
    # tool's failure, not a call the model can be asked to correct.
    monkeypatch.setitem(agent_module.TOOLS, "list_people", min)
    model = FakeModel([tool_call("list_people"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    answer = agent.run("who works here?")

    assert isinstance(answer, str)
    assert answer == "Recovered."
    assert argument_error(model) == agent_module.TOOL_FAILED
