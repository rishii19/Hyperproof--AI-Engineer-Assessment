"""The scheduling agent: a simple tool-calling loop."""

import json

from .model import Model
from .prompts import build_system_prompt
from .store import Store
from .tools import TOOLS


class SchedulingAgent:
    def __init__(self, model: Model, store: Store, today: str = "2026-11-02"):
        self.model = model
        self.store = store
        self.today = today

    def run(self, user_request: str) -> str:
        """Handle one user request and return the assistant's final answer."""
        messages = [
            {"role": "system", "content": build_system_prompt(self.store.people, self.today)},
            {"role": "user", "content": user_request},
        ]

        while True:
            raw = self.model.complete(messages)
            action = json.loads(raw)
            messages.append({"role": "assistant", "content": raw})

            if "final" in action:
                return action["final"]

            tool = TOOLS[action["tool"]]
            result = tool(self.store, **action["args"])
            messages.append({"role": "tool", "content": json.dumps(result)})
