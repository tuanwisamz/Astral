"""Decision Assistant against a fake Gemini client (U1): tool replies carry the call's id, the
tool loop is capped, and an API error becomes AI_UNAVAILABLE."""

from google.genai import errors as genai_errors
from google.genai import types

from app.api.v1 import ai
from app.services import gemini

QUESTION = {"message": "Which roads in Kinta first?"}


def _call(call_id: str, name: str = "find_segments", args: dict | None = None) -> types.GenerateContentResponse:
    part = types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args or {"query": "FT1"}))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))]
    )


def _text(text: str) -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=[types.Part(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


class FakeClient:
    """Plays back scripted model turns and records what it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent: list[list] = []
        self.aio = self
        self.models = self

    async def generate_content(self, *, model, contents, config):
        self.sent.append(list(contents))
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        if isinstance(turn, Exception):
            raise turn
        return turn


def test_tool_reply_carries_the_call_id(api, monkeypatch):
    fake = FakeClient([_call("call-1"), _text("Fix Jalan Sultan Azlan Shah first (segment 1).")])
    monkeypatch.setattr(gemini, "client", lambda: fake)
    res = api("officer", "A").post("/api/v1/ai/assistant", json=QUESTION)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer"].startswith("Fix Jalan Sultan Azlan Shah") and body["segments"] == [1]
    assert body["tool_calls"] == [{"tool": "find_segments", "args": {"query": "FT1"}}]
    tool_turn = fake.sent[1][-1]
    reply = tool_turn.parts[0].function_response
    # The Gemini API rejects role "tool"; function responses must go back as a user turn.
    assert tool_turn.role == "user" and (reply.id, reply.name) == ("call-1", "find_segments")
    assert reply.response["result"]["roads"]  # the real tool ran against the fixture network


def test_a_failed_lookup_goes_back_to_the_model(api, monkeypatch):
    fake = FakeClient(
        [_call("c1", "get_segment_analysis", {"segment_id": 999999}), _text("I couldn't find that road.")]
    )
    monkeypatch.setattr(gemini, "client", lambda: fake)
    res = api("officer", "A").post("/api/v1/ai/assistant", json=QUESTION)
    assert res.status_code == 200 and res.json()["answer"] == "I couldn't find that road."
    assert "error" in fake.sent[1][-1].parts[0].function_response.response["result"]


def test_tool_loop_is_capped(api, monkeypatch):
    fake = FakeClient([_call("again")])  # the model never stops asking for tools
    monkeypatch.setattr(gemini, "client", lambda: fake)
    body = api("officer", "A").post("/api/v1/ai/assistant", json=QUESTION).json()
    assert len(body["tool_calls"]) == ai.MAX_TOOL_CALLS
    assert body["answer"].startswith("I couldn't find an answer")


def test_api_error_becomes_ai_unavailable(api, monkeypatch):
    fake = FakeClient([genai_errors.APIError(401, {"error": {"message": "bad key", "status": "UNAUTHENTICATED"}})])
    monkeypatch.setattr(gemini, "client", lambda: fake)
    res = api("officer", "A").post("/api/v1/ai/assistant", json=QUESTION)
    assert res.status_code == 503 and res.json()["error"]["code"] == "AI_UNAVAILABLE"
    assert len(fake.sent) == 1  # a 401 isn't retried


def test_public_accounts_cannot_use_the_assistant(api):
    assert api("public").post("/api/v1/ai/assistant", json=QUESTION).status_code == 403
