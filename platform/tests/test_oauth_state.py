"""Tests for OAuth state storage with CSRF protection (Phase 2, TASK-1)."""

from __future__ import annotations

from app.services import oauth_state


def test_create_state_returns_urlsafe_token():
    """create_state returns a non-empty string, unique across calls."""
    a = oauth_state.create_state("web")
    b = oauth_state.create_state("web")
    assert isinstance(a, str) and len(a) > 0
    assert a != b


def test_consume_state_record_returns_record_and_deletes():
    """A freshly created state can be consumed once, returning its record."""
    state = oauth_state.create_state("web", metadata={"foo": "bar"})
    record = oauth_state.consume_state_record(state)
    assert record is not None
    assert record["intent"] == "web"
    assert record["foo"] == "bar"
    # one-time: second consume returns None
    assert oauth_state.consume_state_record(state) is None


def test_consume_unknown_state_returns_none():
    """An unknown state yields None."""
    assert oauth_state.consume_state_record("definitely-not-issued") is None


def test_expired_state_returns_none(monkeypatch):
    """A state older than STATE_TTL_SECONDS is treated as expired."""
    state = oauth_state.create_state("web")
    # Move the clock forward past TTL for the consume path.
    fake_now = oauth_state.time.time() + oauth_state.STATE_TTL_SECONDS + 1
    monkeypatch.setattr(oauth_state.time, "time", lambda: fake_now)
    assert oauth_state.consume_state_record(state) is None
