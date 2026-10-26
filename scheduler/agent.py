"""The scheduling agent: a simple tool-calling loop."""

import inspect
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

TOOL_FAILED = (
    "That tool failed while it ran. Its arguments were fine, so this is a "
    "fault in the tool rather than in the call: try another way of getting "
    "what you need, or answer without it."
)

FENCE_PATTERN = re.compile(r"```(?:json)?[ \t]*\r?\n?(.*?)```", re.DOTALL)


def fenced_blocks(raw: str) -> list[str]:
    """Return the contents of every ``` fenced block in a reply, in order."""
    return FENCE_PATTERN.findall(raw)


def _invalid_json(exc: ValueError) -> str:
    return (
        f"Your reply was not valid JSON ({exc}). Reply with a single JSON "
        'object: {"tool": ..., "args": {...}} or {"final": "..."}.'
    )


def _argument_error(
    name: str, signature: inspect.Signature, args: dict
) -> str | None:
    """Name the arguments that stop a call binding, or None if they all bind.

    Written from the signature rather than from the binder's TypeError: the
    binder stops at the first thing it trips over and words it for whoever
    wrote the Python, so a call with two faults in it costs two turns. Every
    wrong name at once, in the tool's own order, is the whole of what the
    next turn needs. The store is the agent's to pass rather than the
    model's, so it is left out of both the check and the message.

    None means the names are all fine and the binder objected to something
    else; the caller then lets the call itself fail.
    """
    nameable = (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
    parameters = list(signature.parameters.values())[1:]  # drop the store
    expected = {p.name: p for p in parameters if p.kind in nameable}

    missing = [
        argument
        for argument, parameter in expected.items()
        if parameter.default is inspect.Parameter.empty and argument not in args
    ]
    # A tool that takes **kwargs has no unexpected arguments to report.
    takes_extra = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters
    )
    unexpected = [] if takes_extra else [a for a in args if a not in expected]

    clauses = []
    if missing:
        clauses.append(f"missing required argument(s): {', '.join(missing)}")
    if unexpected:
        clauses.append(f"unexpected argument(s): {', '.join(unexpected)}")
    if not clauses:
        return None
    return f"{name}: {'; '.join(clauses)}"


def parse_action(raw: str) -> tuple[dict | None, str | None]:
    """Parse one model reply into an action.

    Returns `(action, None)` for a usable action, or `(None, message)` where
    the message explains to the model what was wrong with its reply.
    """
    if not isinstance(raw, str):
        return None, "Your reply must be text containing a single JSON object."

    try:
        action = json.loads(raw)
    except ValueError as exc:
        # Models like to fence the object, and to think out loud before it.
        # A single fenced block is unambiguous, so read the action out of
        # that; with none, or with several to choose between, guessing which
        # one was meant is worse than asking for a clean reply.
        blocks = fenced_blocks(raw)
        if len(blocks) != 1:
            return None, _invalid_json(exc)
        try:
            action = json.loads(blocks[0])
        except ValueError as fenced_exc:
            return None, _invalid_json(fenced_exc)

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

    def _call_tool(self, name: str, args: dict) -> tuple[str | None, str | None]:
        """Run one tool call, returning `(json_result, None)` or `(None, error)`.

        Binding the arguments first keeps the two kinds of failure apart. A
        call the model got wrong comes back as the argument names it missed
        or invented, which the next turn can act on directly. Anything the
        tool then raises - a bug in it, or a result that will not serialise -
        is the model's to work around rather than to correct, so it comes
        back as one generic failure with no internals quoted at it.

        A callable with no signature to read - a builtin, say - is simply
        called: there is nothing to check the arguments against, so whatever
        goes wrong there is the tool's rather than the call's.
        """
        tool = TOOLS[name]
        try:
            signature = inspect.signature(tool)
        except (ValueError, TypeError):
            signature = None

        if signature is not None:
            try:
                signature.bind(self.store, **args)
            except TypeError:
                error = _argument_error(name, signature, args)
                if error is not None:
                    return None, error

        try:
            return json.dumps(tool(self.store, **args)), None
        except ToolError as exc:
            return None, str(exc)
        except Exception:  # a tool bug must not kill the loop
            return None, TOOL_FAILED

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
                content, error = self._call_tool(
                    action["tool"], action["args"]
                )
                if error is None:
                    consecutive_errors = 0
                    messages.append({"role": "tool", "content": content})
                    continue

            messages.append({"role": "tool", "content": json.dumps({"error": error})})
            consecutive_errors += 1
            if consecutive_errors >= self.max_consecutive_errors:
                return FALLBACK_ANSWER

        return FALLBACK_ANSWER
