"""Optional adapter for any OpenAI-compatible chat completions endpoint.

Works with OpenAI, Azure OpenAI (v1-compatible endpoints), Ollama
(http://localhost:11434/v1) and similar. Configure with environment variables:

    LLM_BASE_URL   e.g. http://localhost:11434/v1
    LLM_API_KEY    optional for local servers
    LLM_MODEL      e.g. llama3.1

You do NOT need this to complete the assignment. All grading uses FakeModel.
"""

import json
import os
import urllib.request


class OpenAICompatibleModel:
    def __init__(self):
        self.base_url = os.environ["LLM_BASE_URL"].rstrip("/")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ["LLM_MODEL"]

    def complete(self, messages: list[dict]) -> str:
        # Most endpoints don't accept a bare "tool" role without tool_call ids,
        # so tool results are sent back as user messages.
        converted = [
            {"role": "user", "content": f"Tool result: {m['content']}"}
            if m["role"] == "tool"
            else m
            for m in messages
        ]
        body = json.dumps({"model": self.model, "messages": converted}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        return payload["choices"][0]["message"]["content"]
