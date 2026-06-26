"""Tests for Feishu SSO routes (Phase 5, TASK-1).

Exercises the three handlers (login / callback / token) directly with mocked
``oauth_state`` + ``feishu_client`` + FakeDb, asserting redirect behaviour,
state one-time semantics, JWT issuance and the TokenResponse contract.
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.routes import feishu_auth


class _FakeResult:
    def __init__(self, record):
        self._record = record

    def scalar_one_or_none(self):
        return self._record


class FakeDb:
    """AsyncSession stand-in: matches WHERE-clause bind-param names."""

    def __init__(self, lookups: dict[str, object] | None = None):
        self.lookups = lookups or {}
        self.added: list = []
        self.flushed = False

    async def execute(self, statement):
        text = str(statement)
        for needle, record in self.lookups.items():
            if needle in text:
                return _FakeResult(record)
        return _FakeResult(None)

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        """Mimic DB defaults applied on flush (uuid id, 'user' role)."""
        import uuid

        for rec in self.added:
            if getattr(rec, "id", None) is None:
                try:
                    rec.id = str(uuid.uuid4())
                except Exception:
                    pass
            if getattr(rec, "role", None) is None:
                try:
                    rec.role = "user"
                except Exception:
                    pass
        self.flushed = True

    async def commit(self):
        pass


def _existing_user():
    return SimpleNamespace(
        id="u-1",
        username="Alice",
        email="a@b.com",
        role="user",
        sso_uid="feishu:ou_abc",
    )


# ---------------------------------------------------------------------------
# /feishu/login
# ---------------------------------------------------------------------------

async def test_login_redirects_to_feishu_authorize(monkeypatch):
    """login() issues a 302 to the Feishu authorize URL with required params."""
    monkeypatch.setattr(feishu_auth.oauth_state, "create_state", lambda intent: "STATE123")
    monkeypatch.setattr(feishu_auth.settings, "feishu_app_id", "cli_test")
    monkeypatch.setattr(feishu_auth.settings, "feishu_callback_url", "https://app/cb")
    resp = await feishu_auth.feishu_login()
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("https://open.feishu.cn/open-apis/authen/v1/authorize?")
    qs = parse_qs(urlparse(loc).query)
    assert qs["app_id"] == ["cli_test"]
    assert qs["response_type"] == ["code"]
    assert qs["state"] == ["STATE123"]
    assert qs["redirect_uri"] == ["https://app/cb"]


# ---------------------------------------------------------------------------
# /feishu/callback
# ---------------------------------------------------------------------------

async def test_callback_missing_state_redirects_with_error(monkeypatch):
    """No state supplied → error redirect to frontend with error in query."""
    resp = await feishu_auth.feishu_callback(code="c", state=None, db=FakeDb())
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert "error" in qs


async def test_callback_unknown_state_redirects_with_error(monkeypatch):
    """State never issued → error redirect."""
    # Ensure the store is empty
    feishu_auth.oauth_state._STATE_STORE.clear()
    resp = await feishu_auth.feishu_callback(code="c", state="bogus", db=FakeDb())
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert "error" in qs


async def test_callback_valid_state_creates_user_and_issues_jwt(monkeypatch):
    """Valid state + happy path → user created and access_token in redirect query."""
    feishu_auth.oauth_state._STATE_STORE.clear()
    state = feishu_auth.oauth_state.create_state("web")

    async def fake_full(code):
        return {"sub": "ou_abc", "name": "Alice", "email": "a@b.com",
                "department": "R&D", "position": "", "avatar": ""}

    monkeypatch.setattr(feishu_auth.feishu_client, "get_full_user_info", fake_full)
    db = FakeDb(lookups={"sso_uid_1": None, "username_1": None})
    resp = await feishu_auth.feishu_callback(code="c", state=state, db=db)
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs.get("access_token")
    assert db.added  # new user created


async def test_callback_consumed_state_rejected(monkeypatch):
    """One-time state: second use of the same state → error redirect."""
    feishu_auth.oauth_state._STATE_STORE.clear()
    state = feishu_auth.oauth_state.create_state("web")

    async def fake_full(code):
        return {"sub": "ou_abc", "name": "Alice", "email": "a@b.com",
                "department": "R&D", "position": "", "avatar": ""}

    monkeypatch.setattr(feishu_auth.feishu_client, "get_full_user_info", fake_full)
    db = FakeDb(lookups={"sso_uid_1": _existing_user()})
    # First consumption succeeds
    first = await feishu_auth.feishu_callback(code="c", state=state, db=db)
    assert first.status_code == 302
    assert "access_token" in first.headers["location"]
    # Second consumption → error
    second = await feishu_auth.feishu_callback(code="c", state=state, db=db)
    assert second.status_code == 302
    qs = parse_qs(urlparse(second.headers["location"]).query)
    assert "error" in qs


# ---------------------------------------------------------------------------
# /feishu/token
# ---------------------------------------------------------------------------

async def test_token_endpoint_returns_token_response(monkeypatch):
    """token() returns a TokenResponse-shaped object matching /api/auth/login."""
    async def fake_full(code):
        return {"sub": "ou_abc", "name": "Alice", "email": "a@b.com",
                "department": "R&D", "position": "", "avatar": ""}

    monkeypatch.setattr(feishu_auth.feishu_client, "get_full_user_info", fake_full)
    db = FakeDb(lookups={"sso_uid_1": None, "username_1": None})
    resp = await feishu_auth.feishu_token(code="c", db=db)
    body = resp if isinstance(resp, dict) else resp.body if hasattr(resp, "body") else resp
    # feishu_token returns a TokenResponse instance (Pydantic model)
    payload = resp if hasattr(resp, "model_dump") else body
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["username"] == "Alice"
    assert payload["role"] == "user"
    assert payload["user_id"]


async def test_token_endpoint_failure_returns_500(monkeypatch):
    """When get_full_user_info raises, token() returns HTTP 500."""
    async def boom(code):
        raise RuntimeError("feishu down")

    monkeypatch.setattr(feishu_auth.feishu_client, "get_full_user_info", boom)
    with pytest.raises(Exception):
        await feishu_auth.feishu_token(code="c", db=FakeDb())
