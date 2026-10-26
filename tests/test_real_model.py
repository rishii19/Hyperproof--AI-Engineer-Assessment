import json


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()


def test_real_model_sets_a_request_timeout(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")
    from scheduler.real_model import OpenAICompatibleModel

    seen = {}

    def fake_urlopen(request, *args, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert OpenAICompatibleModel().complete([{"role": "user", "content": "hi"}]) == "hi"
    assert seen.get("timeout") == 30
