"""Tests for Feishu router registration (Phase 6, TASK-1).

Asserts the feishu_auth router is mounted, existing /api/auth/* routes survive,
and the callback redirect carries access_token/refresh_token via an ASGI client.
"""

from __future__ import annotations

import sys
import types
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Local-dev import guard: ``app.main`` pulls in heavy optional deps (litellm,
# docker SDK) that only exist in the Docker runtime venv. Stub them when
# missing so the router-registration assertions can run anywhere. These stubs
# do not affect the FastAPI route table under test.
# ---------------------------------------------------------------------------
def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for key, val in (attrs or {}).items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


def _install_heavy_dep_stubs() -> None:
    try:
        import litellm  # noqa: F401
    except Exception:
        _lit = _ensure_stub(
            "litellm",
            {"acompletion": lambda *a, **k: None, "completion": lambda *a, **k: None},
        )
        _lit.Router = type("Router", (), {})
        _lit.RateLimitError = type("RateLimitError", (Exception,), {})
    try:
        import docker  # noqa: F401
    except Exception:
        dpkg = _ensure_stub("docker")
        dpkg.__path__ = []  # mark as package
        for sub in ("errors", "models", "client", "transport", "auth", "types", "tls", "utils"):
            _ensure_stub(f"docker.{sub}")
        de = sys.modules["docker.errors"]
        for cls in ("DockerException", "APIError", "NotFound", "ImageNotFound", "BuildError"):
            setattr(de, cls, type(cls, (Exception,), {}))
    _ensure_stub("pypdf")
    _ensure_stub("pptx")


_install_heavy_dep_stubs()

import httpx
import pytest

from app.main import app
from app.routes import feishu_auth
from app.services import oauth_state


def _route_paths() -> set[str]:
    paths = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
    return paths


def test_feishu_auth_router_mounted():
    """Feishu endpoints are present on the mounted app."""
    paths = _route_paths()
    assert "/api/auth/feishu/login" in paths
    assert "/api/auth/feishu/callback" in paths
    assert "/api/auth/feishu/token" in paths


def test_existing_auth_routes_preserved():
    """Regression guard: username/password routes remain mounted."""
    paths = _route_paths()
    for must in ("/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/auth/me"):
        assert must in paths, f"{must} missing after feishu router mount"


async def test_feishu_callback_redirect_carries_token(monkeypatch):
    """End-to-end via ASGI: callback 302 Location query has access_token+refresh_token."""
    # Seed a valid state in the in-process store
    oauth_state._STATE_STORE.clear()
    state = oauth_state.create_state("web")

    async def fake_full(code):
        return {"sub": "ou_abc", "name": "Alice", "email": "a@b.com",
                "department": "R&D", "position": "", "avatar": ""}

    monkeypatch.setattr(feishu_auth.feishu_client, "get_full_user_info", fake_full)

    # Stub the DB dependency so we don't need a live Postgres
    class _FakeResult:
        def __init__(self, r):
            self._r = r

        def scalar_one_or_none(self):
            return self._r

    class _FakeDb:
        added = []

        async def execute(self, stmt):
            return _FakeResult(None)

        def add(self, rec):
            _FakeDb.added.append(rec)

        async def flush(self):
            import uuid

            for rec in _FakeDb.added:
                if getattr(rec, "id", None) is None:
                    rec.id = str(uuid.uuid4())
                if getattr(rec, "role", None) is None:
                    rec.role = "user"

        async def commit(self):
            pass

    async def _override_db():
        return _FakeDb()

    app.dependency_overrides[feishu_auth.get_db] = _override_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/auth/feishu/callback",
                params={"code": "c", "state": state},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        qs = parse_qs(urlparse(resp.headers["location"]).query)
        assert qs.get("access_token")
        assert qs.get("refresh_token")
    finally:
        app.dependency_overrides.pop(feishu_auth.get_db, None)
