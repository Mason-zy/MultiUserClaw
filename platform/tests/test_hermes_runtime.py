import io
import json
import sys
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
async def test_dedicated_hermes_get_agent_info_uses_models_endpoint(monkeypatch, dedicated_user):
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_get_models(self):
        return {"data": [{"id": "hermes-agent", "object": "model"}]}

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.HermesClient.get_models", fake_get_models)

    payload = await backend.get_agent_info(RuntimeContext(user=dedicated_user, scope="dedicated"))

    assert payload == {"agents": [{"id": "hermes-agent", "object": "model"}]}


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

    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")
    client = await backend._client(RuntimeContext(user=dedicated_user, scope="dedicated"))

    assert client.api_key == "bridge-key"


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
async def test_dedicated_hermes_upload_file_puts_archive_into_container(monkeypatch, dedicated_user):
    from fastapi import UploadFile
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    class FakeContainer:
        def __init__(self):
            self.calls = []

        def put_archive(self, path, data):
            self.calls.append((path, data))
            return True

    fake_container = FakeContainer()
    backend = DedicatedHermesBackend(base_url="http://dedicated-hermes")

    async def fake_ensure_running(db, user_id):
        assert user_id == dedicated_user.id
        return fake_container

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.ensure_running", fake_ensure_running)

    upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"hello hermes"))
    payload = await backend.upload_file(RuntimeContext(user=dedicated_user, scope="dedicated"), upload)

    assert payload["original_name"] == "notes.txt"
    assert payload["size"] == len(b"hello hermes")
    assert payload["url"].startswith("/api/openclaw/filemanager/serve?path=/workspace/uploads/")
    assert fake_container.calls
    assert fake_container.calls[0][0] == "/"


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

    async def fake_container_url(db, user):
        assert user.id == dedicated_user.id
        return "http://dedicated-hermes"

    class FakeBinaryResponse:
        def __init__(self):
            self.content = b"hello"
            self.status_code = 200
            self.headers = {"content-type": "text/plain"}

    class FakeHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, **kwargs):
            captured.append((method, url, kwargs))
            return FakeBinaryResponse()

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr("app.auth.service.decode_token", fake_decode)
    monkeypatch.setattr("app.auth.service.get_user_by_id", fake_get_user)
    monkeypatch.setattr("app.routes.proxy.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.routes.proxy._container_url", fake_container_url)
    monkeypatch.setattr("app.routes.proxy.httpx.AsyncClient", lambda timeout=30.0: FakeHttpClient())
    monkeypatch.setattr(proxy.settings, "dedicated_runtime_backend", "hermes")

    response = await proxy._proxy_file_request(FakeRequest(), "tok", "filemanager/serve")

    assert response.body == b"hello"
    assert captured == [("GET", "http://dedicated-hermes/workspace/uploads/test.txt", {})]


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
