"""Model interface plus a deterministic fake for tests and local development."""

import copy
import json
from typing import Protocol


class Model(Protocol):
    def complete(self, messages: list[dict]) -> str:
        """Given the conversation so far, return the model's raw text reply."""
        ...


class FakeModel:
    """A scripted model. Returns the responses in `script` in order.

    Each response is the raw text the "model" produces, so you can script
    malformed output as well as well-formed JSON. If `loop_last` is True,
    the final response is returned forever once the script runs out
    (useful for simulating a model that gets stuck).
    """

    def __init__(self, script: list[str], loop_last: bool = False):
        self.script = list(script)
        self.loop_last = loop_last
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(copy.deepcopy(messages))
        if not self.script:
            raise RuntimeError("FakeModel script exhausted")
        if self.loop_last and len(self.script) == 1:
            return self.script[0]
        return self.script.pop(0)


def tool_call(name: str, **args) -> str:
    """Helper to build a scripted tool-call response."""
    return json.dumps({"tool": name, "args": args})


def final(text: str) -> str:
    """Helper to build a scripted final answer."""
    return json.dumps({"final": text})
