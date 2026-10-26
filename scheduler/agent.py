"""The scheduling agent: a simple tool-calling loop."""

import json
import re

from .model import Model
from .prompts import build_system_prompt
from .store import Store
from .tools import TOOLS, ToolError

FALLBACK_ANSWER = (
    "Sorry - I wasn't able to work that out. Could you try rephrasing your "
    "request, with the people and the date you have in mind?"
)

FENCE_PATTERN = re.compile(r"\A\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*\Z", re.DOTALL)


def strip_code_fence(raw: str) -> str:
    """Remove a single surrounding ```json ... ``` fence, if there is one."""
    match = FENCE_PATTERN.match(raw)
    return match.group(1) if match else raw


def parse_action(raw: str) -> tuple[dict | None, str | None]:
    """Parse one model reply into an action.

    Returns `(action, None)` for a usable action, or `(None, message)` where
    the message explains to the model what was wrong with its reply.
    """
    if not isinstance(raw, str):
        return None, "Your reply must be text containing a single JSON object."

    try:
        action = json.loads(strip_code_fence(raw))
    except ValueError as exc:
        return None, (
            f"Your reply was not valid JSON ({exc}). Reply with a single JSON "
            'object: {"tool": ..., "args": {...}} or {"final": "..."}.'
        )

    if not isinstance(action, dict):
        return None, (
            f"Your reply must be a JSON object, not a {type(action).__name__}."
        )
    if "final" in action:
        if not isinstance(action["final"], str):
            return None, '"final" must be a string.'
        return action, None
    if "tool" not in action:
        return None, 'Your reply must contain either "final" or "tool".'

    tool = action["tool"]
    if not isinstance(tool, str) or tool not in TOOLS:
        return None, f"Unknown tool {tool!r}. Available tools: {', '.join(TOOLS)}."
    if not isinstance(action.get("args"), dict):
        return None, f'"args" must be a JSON object of arguments for {tool}.'
    return action, None


class SchedulingAgent:
    def __init__(
        self,
        model: Model,
        store: Store,
        today: str = "2026-11-02",
        max_steps: int = 8,
        max_consecutive_errors: int = 3,
    ):
        self.model = model
        self.store = store
        self.today = today
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors

    def run(self, user_request: str) -> str:
        """Handle one user request and return the assistant's final answer.

        A malformed reply or a failing tool call is never raised at the caller:
        it is described back to the model as a tool result so that the next
        turn can correct it. If the model runs past `max_steps` turns, or gets
        `max_consecutive_errors` replies wrong in a row, give up and say so
        rather than looping forever. If the model call itself fails, give up
        immediately with the same answer.
        """
        messages = [
            {"role": "system", "content": build_system_prompt(self.store.people, self.today)},
            {"role": "user", "content": user_request},
        ]

        consecutive_errors = 0
        for _ in range(self.max_steps):
            try:
                raw = self.model.complete(messages)
            except Exception:
                # The endpoint is down, timing out or rejecting us. Retrying
                # would most likely fail the same way, so say so at once
                # rather than burning the remaining steps on it.
                return FALLBACK_ANSWER
            messages.append({"role": "assistant", "content": raw})

            action, error = parse_action(raw)
            if error is None:
                if "final" in action:
                    return action["final"]
                try:
                    result = TOOLS[action["tool"]](self.store, **action["args"])
                except (TypeError, ToolError) as exc:
                    error = str(exc)
                except Exception as exc:  # a tool bug must not kill the loop
                    error = f"{type(exc).__name__}: {exc}"
                else:
                    consecutive_errors = 0
                    messages.append({"role": "tool", "content": json.dumps(result)})
                    continue

            messages.append({"role": "tool", "content": json.dumps({"error": error})})
            consecutive_errors += 1
            if consecutive_errors >= self.max_consecutive_errors:
                return FALLBACK_ANSWER

        return FALLBACK_ANSWER
