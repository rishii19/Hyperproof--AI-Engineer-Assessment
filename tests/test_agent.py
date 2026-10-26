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
