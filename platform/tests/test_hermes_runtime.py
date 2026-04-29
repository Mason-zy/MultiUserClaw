import io
import sys
import tarfile
import types
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

if "docker" not in sys.modules:
    docker_stub = types.ModuleType("docker")
    docker_stub.from_env = lambda: None
    docker_stub.DockerClient = object
    docker_stub.models = SimpleNamespace(containers=SimpleNamespace(Container=object))
    docker_errors = types.ModuleType("docker.errors")
    docker_errors.APIError = RuntimeError
    docker_errors.NotFound = RuntimeError
    docker_stub.errors = docker_errors
    sys.modules["docker"] = docker_stub
    sys.modules["docker.errors"] = docker_errors

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.ModuleType("asyncpg")

from app.db.models import User
from app.runtime_backend import RuntimeContext


class FakeStreamResponse:
    def __init__(self, chunks, status_code=200):
        self.status_code = status_code
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeAsyncClient:
    def __init__(self, *, response_map=None, stream_map=None, capture=None, timeout=None):
        self.response_map = response_map or {}
        self.stream_map = stream_map or {}
        self.capture = capture if capture is not None else []
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(self, method, url, **kwargs):
        self.capture.append((method, url, kwargs))
        responder = self.response_map[(method, url)]
        if isinstance(responder, Exception):
            raise responder
        if callable(responder):
            return responder(method, url, kwargs)
        return responder

    def stream(self, method, url, **kwargs):
        self.capture.append((f"STREAM {method}", url, kwargs))
        responder = self.stream_map[(method, url)]
        if isinstance(responder, Exception):
            raise responder
        if callable(responder):
            responder = responder(method, url, kwargs)
        return responder


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


@pytest.fixture
def dedicated_user():
    return User(
        id="u-hermes",
        username="hermes",
        email="hermes@example.com",
        password_hash="x",
        runtime_mode="dedicated",
        is_active=True,
    )


@pytest.fixture
def shared_user():
    return User(
        id="shared-user-1234567890abcdef",
        username="shared",
        email="shared@example.com",
        password_hash="x",
        runtime_mode="shared",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_hermes_client_get_models_wraps_response(monkeypatch):
    from app.hermes_client import HermesClient

    captured = []

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            response_map={
                ("GET", "http://hermes.local/v1/models"): FakeResponse(
                    json_data={"data": [{"id": "hermes-agent"}]}
                )
            },
            capture=captured,
        )

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)

    client = HermesClient(base_url="http://hermes.local")
    payload = await client.get_models()

    assert payload == {"data": [{"id": "hermes-agent"}]}
    assert captured[0][0] == "GET"
    assert captured[0][1] == "http://hermes.local/v1/models"


@pytest.mark.asyncio
async def test_hermes_client_sends_bearer_auth_header(monkeypatch):
    from app.hermes_client import HermesClient

    captured = []

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            response_map={
                ("GET", "http://hermes.local/v1/models"): FakeResponse(
                    json_data={"data": [{"id": "hermes-agent"}]}
                )
            },
            capture=captured,
        )

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)

    client = HermesClient(base_url="http://hermes.local", api_key="bridge-key")
    await client.get_models()

    assert captured[0][2]["headers"]["Authorization"] == "Bearer bridge-key"


@pytest.mark.asyncio
async def test_hermes_client_retries_connect_errors(monkeypatch):
    from app.hermes_client import HermesClient

    captured = []
    attempts = {"count": 0}

    def responder(method, url, kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("not ready")
        return FakeResponse(json_data={"data": [{"id": "hermes-agent"}]})

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            response_map={
                ("GET", "http://hermes.local/v1/models"): responder,
            },
            capture=captured,
        )

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)
    monkeypatch.setattr("app.hermes_client.asyncio.sleep", fake_sleep)

    client = HermesClient(base_url="http://hermes.local", connect_retries=1)
    payload = await client.get_models()

    assert payload == {"data": [{"id": "hermes-agent"}]}
    assert attempts["count"] == 2
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_dedicated_hermes_get_agent_info_uses_models_endpoint(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_get_models(self):
        return {"data": [{"id": "hermes-agent", "object": "model"}]}

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.HermesClient.get_models", fake_get_models)

    payload = await backend.get_agent_info(RuntimeContext(user=dedicated_user, scope="dedicated"))

    assert payload == {"agents": [{"id": "hermes-agent", "object": "model"}]}


@pytest.mark.asyncio
async def test_dedicated_hermes_list_skills_reads_container_metadata(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    class FakeContainer:
        docker_id = "container-123"

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_ensure_running(db, user_id):
        assert user_id == dedicated_user.id
        return FakeContainer()

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.ensure_running", fake_ensure_running)
    monkeypatch.setattr(
        "app.runtime_backends.dedicated_hermes.list_skills_from_hermes_container",
        lambda container_id: [
            {
                "name": "dogfood",
                "description": "Systematic QA testing",
                "source": "hermes",
                "disabled": False,
            }
        ],
    )

    payload = await DedicatedHermesBackend().list_skills(
        RuntimeContext(user=dedicated_user, scope="dedicated")
    )

    assert payload == [
        {
            "name": "dogfood",
            "description": "Systematic QA testing",
            "source": "hermes",
            "disabled": False,
        }
    ]


@pytest.mark.asyncio
async def test_shared_hermes_context_does_not_call_openclaw_agent_api(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        def __init__(self):
            self.added = None
            self.committed = False

        async def execute(self, _stmt):
            return FakeResult()

        def add(self, binding):
            self.added = binding

        async def commit(self):
            self.committed = True

        async def refresh(self, _binding):
            return None

    async def fail_create_shared_agent(*_args, **_kwargs):
        raise AssertionError("shared Hermes must not call OpenClaw /api/agents")

    async def fake_audit_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.shared_runtime.create_shared_agent", fail_create_shared_agent)
    monkeypatch.setattr("app.shared_runtime.write_audit_log", fake_audit_log)

    db = FakeDB()
    ctx = await SharedHermesBackend()._context_for_user(db, shared_user)

    assert db.added is not None
    assert db.committed is True
    assert ctx.binding.openclaw_agent_id.startswith("usr_")
    assert ctx.session_prefix == f"agent:{ctx.binding.openclaw_agent_id}:"


@pytest.mark.asyncio
async def test_shared_hermes_get_agent_info_uses_models_endpoint(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeSharedContext:
        class Binding:
            openclaw_agent_id = "usr_sharedagent"

        binding = Binding()

    async def fake_context(self, db, user):
        assert user is shared_user
        return FakeSharedContext()

    async def fake_get_models(self):
        return {"data": [{"id": "hermes-agent", "object": "model"}]}

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.HermesClient.get_models", fake_get_models)

    backend = SharedHermesBackend()
    payload = await backend.get_agent_info(RuntimeContext(user=shared_user, scope="shared"))

    assert payload == {
        "agents": [{"id": "hermes-agent", "object": "model"}],
        "defaultId": "usr_sharedagent",
        "runtime_mode": "shared",
    }


def test_shared_hermes_client_uses_platform_api_key(monkeypatch):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    monkeypatch.setattr("app.runtime_backends.shared_hermes.settings.shared_hermes_url", "http://shared-hermes")
    monkeypatch.setattr(
        "app.runtime_backends.shared_hermes.settings.shared_hermes_api_key",
        "shared-key",
        raising=False,
    )
    monkeypatch.setattr("app.runtime_backends.shared_hermes.settings.hermes_connect_retries", 12, raising=False)
    monkeypatch.setattr(
        "app.runtime_backends.shared_hermes.settings.hermes_retry_delay_seconds",
        0.1,
        raising=False,
    )

    client = SharedHermesBackend()._client()

    assert client.api_key == "shared-key"
    assert client.connect_retries == 12
    assert client.retry_delay_seconds == 0.1


@pytest.mark.asyncio
async def test_dedicated_hermes_send_message_starts_run_with_session_id(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    captured = {}

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_create_run(self, *, message, session_id):
        captured["message"] = message
        captured["session_id"] = session_id
        return {
            "run_id": "run-123",
            "session_id": session_id,
            "status": "started",
        }

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.HermesClient.create_run", fake_create_run)

    payload = await backend.send_message(
        RuntimeContext(user=dedicated_user, scope="dedicated"),
        session_key="sess-123",
        message="Hi",
    )

    assert captured == {"message": "Hi", "session_id": "sess-123"}
    assert payload["run_id"] == "run-123"
    assert payload["runId"] == "run-123"
    assert payload["session_key"] == "sess-123"
    assert payload["sessionKey"] == "sess-123"
    assert payload["raw"]["run_id"] == "run-123"


@pytest.mark.asyncio
async def test_dedicated_hermes_client_uses_platform_api_key(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.settings.dedicated_hermes_api_key", "bridge-key")
    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.settings.hermes_connect_retries", 12, raising=False)
    monkeypatch.setattr(
        "app.runtime_backends.dedicated_hermes.settings.hermes_retry_delay_seconds",
        0.1,
        raising=False,
    )

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")
    client = await backend._client(RuntimeContext(user=dedicated_user, scope="dedicated"))

    assert client.api_key == "bridge-key"
    assert client.connect_retries == 12
    assert client.retry_delay_seconds == 0.1


@pytest.mark.asyncio
async def test_dedicated_hermes_wait_run_reads_sse_events(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_collect(self, run_id, timeout_ms=25000):
        assert run_id == "run-123"
        assert timeout_ms == 9000
        return [
            {"type": "run.started"},
            {"type": "message.completed", "message": {"role": "assistant", "content": "Done"}},
            {"type": "run.completed"},
        ]

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.HermesClient.collect_run_events", fake_collect)

    payload = await backend.wait_run(RuntimeContext(user=dedicated_user, scope="dedicated"), "run-123", 9000)

    assert payload["run_id"] == "run-123"
    assert payload["status"] == "completed"
    assert payload["message"]["content"] == "Done"
    assert payload["events"][0]["type"] == "run.started"


@pytest.mark.asyncio
async def test_dedicated_hermes_wait_run_uses_completed_output(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_collect(self, run_id, timeout_ms=25000):
        assert run_id == "run-123"
        return [
            {"type": "message.delta", "delta": "<think>private"},
            {"type": "message.delta", "delta": " reasoning</think>\n\npong"},
            {"type": "run.completed", "output": "<think>private</think>\n\npong"},
        ]

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.HermesClient.collect_run_events", fake_collect)

    payload = await backend.wait_run(RuntimeContext(user=dedicated_user, scope="dedicated"), "run-123", 9000)

    assert payload["status"] == "completed"
    assert payload["message"] == {"role": "assistant", "content": "pong"}
    assert payload["events"] == [
        {"type": "message.delta", "delta": "pong"},
        {"type": "run.completed", "output": "pong"},
    ]


def test_hermes_event_sanitizer_filters_split_thinking_delta():
    from app.runtime_backends.hermes_run import HermesEventSanitizer

    sanitizer = HermesEventSanitizer()

    assert sanitizer.sanitize_event({"type": "message.delta", "delta": "<think>\nThe user"}) is None

    event = sanitizer.sanitize_event({"type": "message.delta", "delta": " wants pong</think>\n\npong"})

    assert event == {"type": "message.delta", "delta": "pong"}
    assert sanitizer.sanitize_event({"type": "reasoning.available", "text": "private"}) is None


def test_sanitize_sse_block_filters_split_thinking_delta():
    from app.runtime_backends.hermes_run import HermesEventSanitizer, sanitize_sse_block

    sanitizer = HermesEventSanitizer()

    assert sanitize_sse_block('data: {"type":"message.delta","delta":"<think>private"}', sanitizer) is None

    block = sanitize_sse_block(
        'data: {"type":"message.delta","delta":" reasoning</think>\\n\\npong"}',
        sanitizer,
    )

    assert block == 'data: {"type":"message.delta","delta":"pong"}\n\n'


def test_summarize_run_events_strips_completed_output_thinking():
    from app.runtime_backends.hermes_run import summarize_run_events

    status_text, final_message = summarize_run_events(
        [{"type": "run.completed", "output": "<think>private</think>\n\npong"}]
    )

    assert status_text == "completed"
    assert final_message == {"role": "assistant", "content": "pong"}


@pytest.mark.asyncio
async def test_shared_hermes_wait_run_uses_completed_output(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    async def fake_collect(self, run_id, timeout_ms=25000):
        assert run_id == "run-123"
        return [
            {"type": "message.delta", "delta": "<think>private"},
            {"type": "message.delta", "delta": " reasoning</think>\n\npong"},
            {"type": "run.completed", "output": "<think>private</think>\n\npong"},
        ]

    monkeypatch.setattr("app.runtime_backends.shared_hermes.HermesClient.collect_run_events", fake_collect)

    payload = await SharedHermesBackend().wait_run(
        RuntimeContext(user=shared_user, scope="shared"),
        "run-123",
        9000,
    )

    assert payload["status"] == "completed"
    assert payload["message"] == {"role": "assistant", "content": "pong"}
    assert payload["events"] == [
        {"type": "message.delta", "delta": "pong"},
        {"type": "run.completed", "output": "pong"},
    ]


@pytest.mark.asyncio
async def test_hermes_client_collect_run_events_parses_sse(monkeypatch):
    from app.hermes_client import HermesClient

    captured = []
    chunks = [
        b'event: run.started\n',
        b'data: {"type":"run.started"}\n\n',
        b'data: {"type":"message.completed","message":{"content":"ok"}}\n\n',
        b'data: [DONE]\n\n',
    ]

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            stream_map={
                ("GET", "http://hermes.local/v1/runs/run-1/events"): FakeStreamResponse(chunks)
            },
            capture=captured,
        )

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)

    client = HermesClient(base_url="http://hermes.local")
    events = await client.collect_run_events("run-1", timeout_ms=5000)

    assert events == [
        {"type": "run.started"},
        {"type": "message.completed", "message": {"content": "ok"}},
    ]
    assert captured[0][0] == "STREAM GET"
    assert captured[0][1] == "http://hermes.local/v1/runs/run-1/events"
    assert captured[0][2]["params"] == {"timeout_ms": 5000}


@pytest.mark.asyncio
async def test_hermes_client_collect_run_events_normalizes_event_field(monkeypatch):
    from app.hermes_client import HermesClient

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            stream_map={
                ("GET", "http://hermes.local/v1/runs/run-2/events"): FakeStreamResponse(
                    [b'data: {"event":"run.completed","output":"ok"}\n\n']
                )
            }
        )

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)

    client = HermesClient(base_url="http://hermes.local")
    events = await client.collect_run_events("run-2")

    assert events == [{"event": "run.completed", "output": "ok", "type": "run.completed"}]


@pytest.mark.asyncio
async def test_hermes_client_raises_http_exception_for_upstream_errors(monkeypatch):
    from app.hermes_client import HermesClient

    def fake_client(*args, **kwargs):
        return FakeAsyncClient(
            response_map={
                ("GET", "http://hermes.local/v1/models"): FakeResponse(
                    status_code=503,
                    json_data={"error": {"message": "booting"}},
                )
            }
        )

    monkeypatch.setattr("app.hermes_client.httpx.AsyncClient", fake_client)

    client = HermesClient(base_url="http://hermes.local")

    with pytest.raises(HTTPException, match="booting") as exc:
        await client.get_models()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_dedicated_hermes_list_sessions_maps_api_payload(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_request(self, ctx, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/hermes/sessions"
        return {
            "sessions": [
                {
                    "session_id": "sess-1",
                    "title": "First",
                    "message_count": 3,
                    "updated_at": "2026-04-13T15:00:00Z",
                }
            ]
        }

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.DedicatedHermesBackend._request", fake_request)

    payload = await backend.list_sessions(RuntimeContext(user=dedicated_user, scope="dedicated"))

    assert payload == [
        {
            "key": "sess-1",
            "sessionKey": "sess-1",
            "title": "First",
            "updatedAt": "2026-04-13T15:00:00Z",
            "messageCount": 3,
        }
    ]


@pytest.mark.asyncio
async def test_shared_hermes_list_sessions_filters_by_session_prefix(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeSharedContext:
        session_prefix = "agent:usr_sharedagent:"

    async def fake_context(self, db, user):
        assert user is shared_user
        return FakeSharedContext()

    async def fake_request(self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/hermes/sessions"
        return {
            "sessions": [
                {
                    "session_id": "agent:usr_sharedagent:session-1",
                    "title": "Mine",
                    "message_count": 3,
                    "updated_at": "2026-04-13T15:00:00Z",
                },
                {
                    "session_id": "agent:other:session-2",
                    "title": "Other",
                    "message_count": 1,
                    "updated_at": "2026-04-13T16:00:00Z",
                },
            ]
        }

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._request", fake_request)

    backend = SharedHermesBackend()
    payload = await backend.list_sessions(RuntimeContext(user=shared_user, scope="shared"))

    assert payload == [
        {
            "key": "agent:usr_sharedagent:session-1",
            "sessionKey": "agent:usr_sharedagent:session-1",
            "title": "Mine",
            "updatedAt": "2026-04-13T15:00:00Z",
            "messageCount": 3,
        }
    ]


@pytest.mark.asyncio
async def test_dedicated_hermes_get_session_maps_messages(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_request(self, ctx, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/hermes/sessions/sess-2"
        return {
            "session_id": "sess-2",
            "title": "Second",
            "message_count": 2,
            "created_at": "2026-04-13T14:00:00Z",
            "updated_at": "2026-04-13T15:00:00Z",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        }

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.DedicatedHermesBackend._request", fake_request)

    payload = await backend.get_session(RuntimeContext(user=dedicated_user, scope="dedicated"), "sess-2")

    assert payload["sessionKey"] == "sess-2"
    assert payload["title"] == "Second"
    assert payload["messageCount"] == 2
    assert payload["messages"][1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_dedicated_hermes_get_session_strips_thinking_blocks(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_request(self, ctx, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/hermes/sessions/sess-think"
        return {
            "session_id": "sess-think",
            "messages": [
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": "<think>\nprivate reasoning\n</think>\n\nHello",
                    "reasoning": "private reasoning",
                },
            ],
        }

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.DedicatedHermesBackend._request", fake_request)

    payload = await backend.get_session(RuntimeContext(user=dedicated_user, scope="dedicated"), "sess-think")

    assert payload["messages"][1] == {"role": "assistant", "content": "Hello"}


@pytest.mark.asyncio
async def test_shared_hermes_get_session_strips_thinking_blocks(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeSharedContext:
        session_prefix = "agent:usr_sharedagent:"

    async def fake_context(self, db, user):
        assert user is shared_user
        return FakeSharedContext()

    async def fake_request(self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/api/hermes/sessions/agent:usr_sharedagent:sess-think"
        return {
            "session_id": "agent:usr_sharedagent:sess-think",
            "messages": [
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": "<think>private reasoning</think>\n\nHello",
                    "reasoning": "private reasoning",
                },
            ],
        }

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._request", fake_request)

    payload = await SharedHermesBackend().get_session(
        RuntimeContext(user=shared_user, scope="shared"),
        "agent:usr_sharedagent:sess-think",
    )

    assert payload["messages"][1] == {"role": "assistant", "content": "Hello"}


@pytest.mark.asyncio
async def test_dedicated_hermes_upload_file_puts_archive_into_container(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend
    from fastapi import UploadFile

    class FakeDockerContainer:
        def __init__(self):
            self.calls = []
            self.exec_calls = []

        def put_archive(self, path, data):
            self.calls.append((path, data))
            return True

        def exec_run(self, cmd):
            self.exec_calls.append(cmd)
            return SimpleNamespace(exit_code=0, output=b"")

    class FakeDockerClient:
        def __init__(self, container):
            self.container = container
            self.requested_ids = []
            self.containers = self

        def get(self, container_id):
            self.requested_ids.append(container_id)
            return self.container

    fake_docker_container = FakeDockerContainer()
    fake_docker_client = FakeDockerClient(fake_docker_container)
    container_record = SimpleNamespace(docker_id="docker-123")
    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_ensure_running(db, user_id):
        assert user_id == dedicated_user.id
        return container_record

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.ensure_running", fake_ensure_running)
    monkeypatch.setattr("app.container.manager._docker", lambda: fake_docker_client)

    upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"hello hermes"))
    payload = await backend.upload_file(RuntimeContext(user=dedicated_user, scope="dedicated"), upload)

    assert payload["original_name"] == "notes.txt"
    assert payload["size"] == len(b"hello hermes")
    assert payload["path"].startswith("workspace/uploads/")
    assert payload["url"].startswith("/api/openclaw/filemanager/serve?path=/workspace/uploads/")
    assert fake_docker_client.requested_ids == ["docker-123"]
    assert fake_docker_container.exec_calls
    assert "/root/.openclaw" in fake_docker_container.exec_calls[0][-1]
    assert fake_docker_container.calls
    assert fake_docker_container.calls[0][0] == "/opt/data"
    with tarfile.open(fileobj=io.BytesIO(fake_docker_container.calls[0][1]), mode="r") as tar:
        members = {member.name: member for member in tar.getmembers()}
        assert members["home/.openclaw"].issym()
        assert members["home/.openclaw"].linkname == "/opt/data"
        uploaded_name = next(
            name
            for name in members
            if name.startswith("workspace/uploads/") and name.endswith("notes.txt")
        )
        assert tar.extractfile(uploaded_name).read() == b"hello hermes"


@pytest.mark.asyncio
async def test_shared_hermes_upload_file_puts_archive_into_shared_container(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend
    from fastapi import UploadFile

    class FakeBinding:
        openclaw_agent_id = "usr_sharedagent"

    class FakeSharedContext:
        binding = FakeBinding()
        session_prefix = "agent:usr_sharedagent:"
        upload_dir = "workspace-usr_sharedagent/uploads"

    class FakeDockerContainer:
        def __init__(self):
            self.calls = []
            self.exec_calls = []

        def put_archive(self, path, data):
            self.calls.append((path, data))
            return True

        def exec_run(self, cmd):
            self.exec_calls.append(cmd)
            return SimpleNamespace(exit_code=0, output=b"")

    class FakeDockerClient:
        def __init__(self, container):
            self.container = container
            self.requested_ids = []
            self.containers = self

        def get(self, container_id):
            self.requested_ids.append(container_id)
            return self.container

    async def fake_context(self, db, user):
        assert user is shared_user
        return FakeSharedContext()

    async def fail_old_upload_endpoint(*args, **kwargs):
        pytest.fail("Shared Hermes upload must not call the old OpenClaw filemanager endpoint")

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    fake_docker_container = FakeDockerContainer()
    fake_docker_client = FakeDockerClient(fake_docker_container)

    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.shared_runtime.shared_runtime_request", fail_old_upload_endpoint)
    monkeypatch.setattr("app.container.manager._docker", lambda: fake_docker_client)

    upload = UploadFile(filename="shared.txt", file=io.BytesIO(b"shared hermes"))
    payload = await SharedHermesBackend().upload_file(RuntimeContext(user=shared_user, scope="shared"), upload)

    assert payload["original_name"] == "shared.txt"
    assert payload["size"] == len(b"shared hermes")
    assert payload["path"].startswith("workspace-usr_sharedagent/uploads/")
    assert fake_docker_client.requested_ids == ["openclaw-shared"]
    assert fake_docker_container.exec_calls
    assert "/root/.openclaw" in fake_docker_container.exec_calls[0][-1]
    assert fake_docker_container.calls
    assert fake_docker_container.calls[0][0] == "/opt/data"
    with tarfile.open(fileobj=io.BytesIO(fake_docker_container.calls[0][1]), mode="r") as tar:
        members = {member.name: member for member in tar.getmembers()}
        assert members["home/.openclaw"].issym()
        assert members["home/.openclaw"].linkname == "/opt/data"
        uploaded_name = next(
            name
            for name in members
            if name.startswith("workspace-usr_sharedagent/uploads/") and name.endswith("shared.txt")
        )
        assert tar.extractfile(uploaded_name).read() == b"shared hermes"


@pytest.mark.asyncio
async def test_dedicated_hermes_stream_maps_upstream_events(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    class FakeRequest:
        async def is_disconnected(self):
            return False

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_text(self):
            yield 'data: {"type":"message.delta","session_id":"sess-9","delta":"Hi"}\n\n'
            yield 'data: {"type":"message.completed","session_id":"sess-9","message":{"role":"assistant","content":"Hello"}}\n\n'

    class FakeAsyncClientForStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, **kwargs):
            assert method == "GET"
            assert url == "http://dedicated-hermes/api/hermes/events/stream"
            return FakeStreamResponse()

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.decode_token", lambda token: {"type": "access", "sub": dedicated_user.id})

    async def fake_get_user(db, user_id):
        assert user_id == dedicated_user.id
        return dedicated_user

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.get_user_by_id", fake_get_user)

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.httpx.AsyncClient", lambda timeout=None: FakeAsyncClientForStream())

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")
    response = await backend.stream_events(RuntimeContext(user=dedicated_user, scope="dedicated"), FakeRequest(), "tok")

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    text = body.decode("utf-8")
    assert '"state": "delta"' in text
    assert '"state": "final"' in text
    assert '"sessionKey": "sess-9"' in text


@pytest.mark.asyncio
async def test_shared_hermes_stream_events_sends_bridge_key(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeRequest:
        async def is_disconnected(self):
            return False

    class FakeSharedContext:
        session_prefix = "agent:usr_sharedagent:"

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_text(self):
            yield (
                'data: {"type":"message.delta",'
                '"session_id":"agent:usr_sharedagent:sess-9","delta":"Hi"}\n\n'
            )

    captured = []

    class FakeAsyncClientForStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, **kwargs):
            captured.append((method, url, kwargs))
            return FakeStreamResponse()

    async def fake_get_user(db, user_id):
        assert user_id == shared_user.id
        return shared_user

    async def fake_context(self, db, user):
        assert user is shared_user
        return FakeSharedContext()

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.shared_hermes.settings.shared_hermes_url", "http://shared-hermes")
    monkeypatch.setattr(
        "app.runtime_backends.shared_hermes.settings.shared_hermes_api_key",
        "shared-key",
        raising=False,
    )
    monkeypatch.setattr("app.runtime_backends.shared_hermes.decode_token", lambda token: {"type": "access", "sub": shared_user.id})
    monkeypatch.setattr("app.runtime_backends.shared_hermes.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.httpx.AsyncClient", lambda timeout=None: FakeAsyncClientForStream())

    response = await SharedHermesBackend().stream_events(
        RuntimeContext(user=shared_user, scope="shared"),
        FakeRequest(),
        "tok",
    )

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    assert captured[0] == (
        "GET",
        "http://shared-hermes/api/hermes/events/stream",
        {"headers": {"Authorization": "Bearer shared-key"}},
    )
    assert '"sessionKey": "agent:usr_sharedagent:sess-9"' in body.decode("utf-8")


@pytest.mark.asyncio
async def test_shared_hermes_stream_run_events_sends_bridge_key(monkeypatch, shared_user):
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    class FakeRequest:
        async def is_disconnected(self):
            return False

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_bytes(self):
            yield b'data: {"event":"run.completed"}\n\n'

    captured = []

    class FakeAsyncClientForStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, **kwargs):
            captured.append((method, url, kwargs))
            return FakeStreamResponse()

    async def fake_get_user(db, user_id):
        assert user_id == shared_user.id
        return shared_user

    async def fake_context(self, db, user):
        assert user is shared_user
        return object()

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.runtime_backends.shared_hermes.settings.shared_hermes_url", "http://shared-hermes")
    monkeypatch.setattr(
        "app.runtime_backends.shared_hermes.settings.shared_hermes_api_key",
        "shared-key",
        raising=False,
    )
    monkeypatch.setattr("app.runtime_backends.shared_hermes.decode_token", lambda token: {"type": "access", "sub": shared_user.id})
    monkeypatch.setattr("app.runtime_backends.shared_hermes.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.shared_hermes.SharedHermesBackend._context_for_user", fake_context)
    monkeypatch.setattr("app.runtime_backends.shared_hermes.httpx.AsyncClient", lambda timeout=None: FakeAsyncClientForStream())

    response = await SharedHermesBackend().stream_run_events(
        RuntimeContext(user=shared_user, scope="shared"),
        FakeRequest(),
        "tok",
        "run-123",
    )

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    assert captured[0] == (
        "GET",
        "http://shared-hermes/v1/runs/run-123/events",
        {"headers": {"Authorization": "Bearer shared-key"}},
    )
    assert body == b'data: {"event":"run.completed"}\n\n'


@pytest.mark.asyncio
async def test_proxy_file_request_maps_workspace_paths_for_dedicated_hermes(monkeypatch, dedicated_user):
    from app.routes import proxy

    class FakeRequest:
        headers = {}
        query_params = SimpleNamespace(get=lambda key, default="": "/workspace/uploads/test.txt" if key == "path" else default)

    captured = []

    def fake_decode(token):
        assert token == "tok"
        return {"type": "access", "sub": dedicated_user.id}

    async def fake_get_user(db, user_id):
        assert user_id == dedicated_user.id
        return dedicated_user

    async def fake_ensure_running(db, user_id):
        assert user_id == dedicated_user.id
        return SimpleNamespace(docker_id="docker-123")

    class FakeDockerContainer:
        def __init__(self):
            self.paths = []

        def get_archive(self, path):
            self.paths.append(path)
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
                info = tarfile.TarInfo(name="test.txt")
                info.size = len(b"hello")
                tar.addfile(info, io.BytesIO(b"hello"))
            tar_buffer.seek(0)
            return [tar_buffer.read()], {"name": "test.txt", "size": len(b"hello")}

    class FakeDockerClient:
        def __init__(self, container):
            self.container = container
            self.requested_ids = []
            self.containers = self

        def get(self, container_id):
            self.requested_ids.append(container_id)
            return self.container

    fake_docker_container = FakeDockerContainer()
    fake_docker_client = FakeDockerClient(fake_docker_container)

    async def fail_container_url(db, user):
        assert user.id == dedicated_user.id
        pytest.fail("Dedicated Hermes file serving must not rely on upstream static HTTP")

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.auth.service.decode_token", fake_decode)
    monkeypatch.setattr("app.auth.service.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.routes.proxy.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.routes.proxy.ensure_running", fake_ensure_running)
    monkeypatch.setattr("app.routes.proxy._container_url", fail_container_url)
    monkeypatch.setattr("app.container.manager._docker", lambda: fake_docker_client)
    monkeypatch.setattr(proxy.settings, "dedicated_runtime_backend", "hermes")

    response = await proxy._proxy_file_request(FakeRequest(), "tok", "filemanager/serve")

    assert response.body == b"hello"
    assert fake_docker_client.requested_ids == ["docker-123"]
    assert fake_docker_container.paths == ["/opt/data/workspace/uploads/test.txt"]
    assert captured == []


@pytest.mark.asyncio
async def test_proxy_file_request_rejects_unsupported_dedicated_hermes_download(monkeypatch, dedicated_user):
    from app.routes import proxy

    class FakeRequest:
        headers = {}
        query_params = SimpleNamespace(get=lambda key, default="": "/workspace/uploads/test.txt" if key == "path" else default)

    def fake_decode(token):
        return {"type": "access", "sub": dedicated_user.id}

    async def fake_get_user(db, user_id):
        return dedicated_user

    async def fake_container_url(db, user):
        return "http://dedicated-hermes"

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.auth.service.decode_token", fake_decode)
    monkeypatch.setattr("app.auth.service.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.routes.proxy.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.routes.proxy._container_url", fake_container_url)
    monkeypatch.setattr(proxy.settings, "dedicated_runtime_backend", "hermes")

    with pytest.raises(HTTPException, match="supports /workspace paths") as exc:
        await proxy._proxy_file_request(FakeRequest(), "tok", "filemanager/download")

    assert exc.value.status_code == 404
