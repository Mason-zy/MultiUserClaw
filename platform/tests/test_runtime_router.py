import sys
import types

import pytest
from fastapi import HTTPException

if "docker" not in sys.modules:
    docker_stub = types.ModuleType("docker")
    docker_stub.from_env = lambda: None
    docker_stub.DockerClient = object
    docker_stub.models = types.SimpleNamespace(containers=types.SimpleNamespace(Container=object))
    docker_errors = types.ModuleType("docker.errors")
    docker_errors.APIError = RuntimeError
    docker_errors.NotFound = RuntimeError
    docker_stub.errors = docker_errors
    sys.modules["docker"] = docker_stub
    sys.modules["docker.errors"] = docker_errors

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = types.ModuleType("asyncpg")

from app.config import Settings
from app.db.models import User
from app.runtime_router import _load_backend, get_runtime_backend


class DummyBackend:
    pass


class CloseableBackend:
    def __init__(self):
        self.close_count = 0

    async def aclose(self):
        self.close_count += 1


class DedicatedHermesMarker:
    pass


class SharedHermesMarker:
    pass


def make_user(runtime_mode: str) -> User:
    return User(
        id="u1",
        username="tester",
        email="tester@example.com",
        password_hash="x",
        runtime_mode=runtime_mode,
    )


def test_dedicated_users_use_configured_dedicated_backend(monkeypatch):
    user = make_user("dedicated")
    settings = Settings(dedicated_runtime_backend="openclaw")
    backend = DummyBackend()

    monkeypatch.setattr("app.runtime_router._load_backend", lambda kind, backend_name: backend)

    assert get_runtime_backend(user, settings) is backend


def test_shared_users_use_configured_shared_backend(monkeypatch):
    user = make_user("shared")
    settings = Settings(shared_runtime_backend="openclaw")
    backend = DummyBackend()

    monkeypatch.setattr("app.runtime_router._load_backend", lambda kind, backend_name: backend)

    assert get_runtime_backend(user, settings) is backend


def test_dedicated_hermes_backend_is_supported(monkeypatch):
    imported = []

    class FakeImporter:
        class DedicatedHermesBackend(DedicatedHermesMarker):
            pass

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.runtime_backends.dedicated_hermes":
            imported.append(name)
            return FakeImporter
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    backend = _load_backend("dedicated", "hermes")

    assert isinstance(backend, DedicatedHermesMarker)
    assert imported == ["app.runtime_backends.dedicated_hermes"]


def test_shared_hermes_backend_is_supported(monkeypatch):
    imported = []

    class FakeImporter:
        class SharedHermesBackend(SharedHermesMarker):
            pass

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.runtime_backends.shared_hermes":
            imported.append(name)
            return FakeImporter
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    backend = _load_backend("shared", "hermes")

    assert isinstance(backend, SharedHermesMarker)
    assert imported == ["app.runtime_backends.shared_hermes"]


@pytest.mark.asyncio
async def test_dedicated_hermes_without_config_reports_clear_error(monkeypatch):
    from app.runtime_backend import RuntimeContext
    from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

    user = make_user("dedicated")
    backend = DedicatedHermesBackend()

    class FakeContainer:
        internal_host = ""
        internal_port = 18080

    class FakeAsyncSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_ensure_running(db, user_id):
        assert user_id == user.id
        return FakeContainer()

    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.async_session", lambda: FakeAsyncSessionContext())
    monkeypatch.setattr("app.runtime_backends.dedicated_hermes.ensure_running", fake_ensure_running)

    with pytest.raises(HTTPException, match="Hermes runtime address is unavailable") as exc:
        await backend.get_agent_info(RuntimeContext(user=user, scope="dedicated"))

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_shared_hermes_without_config_reports_clear_error(monkeypatch):
    from app.runtime_backend import RuntimeContext
    from app.runtime_backends.shared_hermes import SharedHermesBackend

    user = make_user("shared")
    backend = SharedHermesBackend()

    monkeypatch.setattr("app.runtime_backends.shared_hermes.settings", Settings(shared_openclaw_url="", shared_hermes_url=""))

    with pytest.raises(HTTPException, match="Shared Hermes URL is not configured") as exc:
        await backend.get_agent_info(RuntimeContext(user=user, scope="shared"))

    assert exc.value.status_code == 503


def test_unknown_dedicated_backend_raises_clear_error():
    try:
        _load_backend("dedicated", "mystery")
    except ValueError as exc:
        assert "Unsupported dedicated runtime backend" in str(exc)
        assert "mystery" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unknown_shared_backend_raises_clear_error():
    try:
        _load_backend("shared", "mystery")
    except ValueError as exc:
        assert "Unsupported shared runtime backend" in str(exc)
        assert "mystery" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@pytest.mark.asyncio
async def test_close_runtime_backends_closes_cached_backends_once():
    import app.runtime_router as runtime_router

    backend = CloseableBackend()
    runtime_router._dedicated_backends.clear()
    runtime_router._shared_backends.clear()
    runtime_router._dedicated_backends["hermes"] = backend
    runtime_router._shared_backends["hermes"] = backend

    await runtime_router.close_runtime_backends()

    assert backend.close_count == 1
    assert runtime_router._dedicated_backends == {}
    assert runtime_router._shared_backends == {}
