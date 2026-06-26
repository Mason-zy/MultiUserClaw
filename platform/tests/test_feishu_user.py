"""Tests for Feishu SSO user mapping (Phase 4, TASK-1).

Verifies ``get_or_create_feishu_user`` (new, zero-intrusion addition to
``app/auth/service.py``) and guards that the original InfoX-Med
``create_or_update_sso_user`` remains untouched.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.auth import service
from app.auth.service import get_or_create_feishu_user


class _FakeResult:
    def __init__(self, record):
        self._record = record

    def scalar_one_or_none(self):
        return self._record


class FakeDb:
    """Minimal AsyncSession stand-in.

    ``lookups`` maps a WHERE-clause signature -> record. We match on the bound
    parameter name rendered by SQLAlchemy (e.g. ``sso_uid_1`` / ``username_1``)
    so the two queries in get_or_create_feishu_user (by sso_uid, then by
    username) don't collide — both SELECTs list all columns.
    """

    def __init__(self, lookups: dict[str, object] | None = None):
        self.lookups = lookups or {}
        self.added: list = []
        self.flushed = False
        self.committed = False

    async def execute(self, statement):
        text = str(statement)
        for needle, record in self.lookups.items():
            if needle in text:
                return _FakeResult(record)
        return _FakeResult(None)

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def refresh(self, record):
        # no-op stand-in: record is already a SimpleNamespace; mirrors
        # SQLAlchemy re-fetching the persisted row after COMMIT.
        return record


def _user(sso_uid=None, username="taken", email="taken@x.com"):
    return SimpleNamespace(
        id="u-existing",
        sso_uid=sso_uid,
        username=username,
        email=email,
        role="user",
    )


async def test_get_or_create_feishu_user_creates_new():
    """No existing sso_uid → new User created with feishu-prefixed sso_uid."""
    db = FakeDb(lookups={"sso_uid_1": None, "username_1": None})
    user = await get_or_create_feishu_user(
        db, sso_uid="feishu:ou_xxx", display_name="Alice", email="a@b.com"
    )
    assert user.sso_uid == "feishu:ou_xxx"
    assert user.username == "Alice"
    assert user.email == "a@b.com"
    assert user.password_hash  # non-empty random placeholder
    assert db.added == [user]
    assert db.committed is True  # TASK-1 hotfix: must commit (flush alone doesn't persist)


async def test_get_or_create_feishu_user_returns_existing():
    """Existing sso_uid user is returned directly, no new row added."""
    existing = _user(sso_uid="feishu:ou_xxx", username="Alice", email="a@b.com")
    db = FakeDb(lookups={"sso_uid_1": existing})
    user = await get_or_create_feishu_user(
        db, sso_uid="feishu:ou_xxx", display_name="Alice", email="a@b.com"
    )
    assert user is existing
    assert db.added == []  # no creation


async def test_get_or_create_feishu_user_username_collision_suffix():
    """Display name collides with an existing username → suffix appended."""
    collision = _user(username="Alice", email="other@x.com")
    db = FakeDb(lookups={"sso_uid_1": None, "username_1": collision})
    user = await get_or_create_feishu_user(
        db, sso_uid="feishu:ou_xxx", display_name="Alice", email="alice@x.com"
    )
    # username gets the last 6 chars of sso_uid appended for uniqueness
    assert user.username != "Alice"
    assert user.username.startswith("Alice")
    assert "ou_xxx"[-6:] in user.username


async def test_existing_create_or_update_sso_user_unchanged():
    """Regression guard: InfoX-Med create_or_update_sso_user signature untouched."""
    sig = inspect.signature(service.create_or_update_sso_user)
    params = sig.parameters
    # Required positional params unchanged
    assert "sso_uid" in params
    assert "sso_token" in params
    # No feishu-specific params leaked in
    assert "email" not in params
    assert "provider" not in params
    # And the new feishu function exists separately
    assert hasattr(service, "get_or_create_feishu_user")


async def test_create_new_user_commits_not_flushes():
    """Regression: new user MUST commit (not just flush) to persist.

    TASK-1 hotfix: ``get_or_create_feishu_user`` originally used ``db.flush()``,
    which assigns an id in-transaction but does NOT persist. The callback then
    issued a JWT, but ``/me`` -> ``get_user_by_id`` returned None -> 401 ->
    frontend cleared the token and kicked back to /login. FakeDb's flush/commit
    are no-ops, so only an explicit ``committed`` assertion catches this class
    of bug — see CLAUDE.md "写操作测试约定".
    """
    db = FakeDb(lookups={"sso_uid_1": None, "username_1": None})
    await get_or_create_feishu_user(
        db, sso_uid="feishu:ou_new", display_name="Bob", email="b@x.com"
    )
    assert db.committed is True
    assert db.flushed is False  # hotfix replaced flush with commit+refresh
