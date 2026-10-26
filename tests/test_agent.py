import json

from scheduler import agent as agent_module
from scheduler.agent import SchedulingAgent
from scheduler.model import FakeModel, final, tool_call
from scheduler.store import Store


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
    for secret in ["priya.raman@northwind.example", "555-0142", "Oakland",
                   "email", "phone", "home_city", "manager"]:
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
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    assert "bob" in json.loads(model.calls[1][-1]["content"])["error"]


def test_agent_feeds_bad_tool_arguments_back_to_the_model():
    model = FakeModel([tool_call("list_people", when="now"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    assert "error" in json.loads(model.calls[1][-1]["content"])


def test_agent_survives_an_unexpected_tool_exception(monkeypatch):
    def boom(store):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(agent_module.TOOLS, "list_people", boom)
    model = FakeModel([tool_call("list_people"), final("Recovered.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("hi") == "Recovered."
    assert "kaboom" in json.loads(model.calls[1][-1]["content"])["error"]


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
    assert result == [
        {"date": "2026-11-02", "start": "14:00", "end": "15:00"},
        {"date": "2026-11-02", "start": "15:30", "end": "16:30"},
        {"date": "2026-11-02", "start": "16:00", "end": "17:00"},
        {"date": "2026-11-03", "start": "13:00", "end": "14:00"},
        {"date": "2026-11-03", "start": "16:00", "end": "17:00"},
    ]


def test_system_prompt_documents_the_range_tool():
    model = FakeModel([final("ok")])
    SchedulingAgent(model, Store.load()).run("hi")
    system = model.calls[0][0]["content"]
    assert "find_free_slots_in_range" in system


def test_list_people_withholds_personal_contact_details():
    model = FakeModel([tool_call("list_people"), final("Here they are.")])
    agent = SchedulingAgent(model, Store.load())

    assert agent.run("who works here?") == "Here they are."
    result = model.calls[1][-1]
    assert result["role"] == "tool"
    for secret in ["@northwind.example", "+1-415", "Oakland"]:
        assert secret not in result["content"], secret
    assert json.loads(result["content"])[0] == {
        "id": "priya", "name": "Priya Raman", "title": "Engineering Manager",
    }
