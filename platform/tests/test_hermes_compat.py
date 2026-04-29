import pytest
from app.db.models import User
from app.runtime.event_translator import hermes_event_to_openclaw_sse
from app.runtime.run_mapper import normalize_platform_run_id
from app.runtime.session_mapper import normalize_platform_session_key
from app.runtime_backend import RuntimeContext


def make_user(runtime_mode: str = "dedicated") -> User:
    return User(
        id="u1",
        username="tester",
        email="tester@example.com",
        password_hash="x",
        runtime_mode=runtime_mode,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_openclaw_skills_route_uses_runtime_backend(monkeypatch):
    from app.api_compat import openclaw_compat

    class FakeBackend:
        async def list_skills(self, ctx: RuntimeContext):
            assert ctx.user.username == "tester"
            assert ctx.scope == "dedicated"
            return [{"name": "dogfood", "description": "QA testing", "source": "hermes"}]

    monkeypatch.setattr(openclaw_compat, "get_runtime_backend", lambda user: FakeBackend())

    payload = await openclaw_compat.list_dedicated_skills(make_user())

    assert payload == [{"name": "dogfood", "description": "QA testing", "source": "hermes"}]


def test_normalize_platform_session_key_preserves_existing_key():
    key = "agent:main:session-123"
    assert normalize_platform_session_key(key) == key


def test_normalize_platform_session_key_generates_default_when_missing():
    key = normalize_platform_session_key(None)
    assert key.startswith("agent:main:session-")
    assert len(key) > len("agent:main:session-")


def test_normalize_platform_run_id_preserves_existing_id():
    run_id = "run_abc123"
    assert normalize_platform_run_id(run_id) == run_id


def test_normalize_platform_run_id_generates_default_when_missing():
    run_id = normalize_platform_run_id(None)
    assert run_id.startswith("run_")
    assert len(run_id) > len("run_")


def test_hermes_event_to_openclaw_sse_translates_delta_event():
    payload = {
        "type": "response.output_text.delta",
        "delta": "Hello",
        "run_id": "hermes-run-1",
    }

    sse = hermes_event_to_openclaw_sse(payload, session_key="agent:main:session-1", platform_run_id="run_1")

    assert sse.startswith("data: ")
    assert '"event": "chat"' in sse
    assert '"state": "delta"' in sse
    assert '"sessionKey": "agent:main:session-1"' in sse
    assert '"runId": "run_1"' in sse
    assert '"text": "Hello"' in sse


def test_hermes_event_to_openclaw_sse_translates_completed_event():
    payload = {
        "type": "response.completed",
        "run_id": "hermes-run-1",
    }

    sse = hermes_event_to_openclaw_sse(payload, session_key="agent:main:session-1", platform_run_id="run_1")

    assert '"state": "final"' in sse


def test_hermes_event_to_openclaw_sse_ignores_unknown_event_without_text():
    payload = {"type": "response.unknown"}
    assert hermes_event_to_openclaw_sse(payload, session_key="agent:main:session-1", platform_run_id="run_1") is None
