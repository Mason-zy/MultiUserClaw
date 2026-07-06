"""OAuth state storage with CSRF protection.

In-process one-time state store ported from agentgateway auth-service
``services/login_state.py`` (state portion only). Suitable for single-instance
deployment; replace with Redis/DB for multi-instance.

A state is created via :func:`create_state` and consumed exactly once via
:func:`consume_state_record` (pop-on-read, one-time semantics). States expire
after :data:`STATE_TTL_SECONDS`.
"""

from __future__ import annotations

import secrets
import time

STATE_TTL_SECONDS = 600
_STATE_STORE: dict[str, dict] = {}


def _cleanup_expired(now: float | None = None) -> None:
    """Drop expired state records. ``now`` is injectable for tests."""
    if now is None:
        now = time.time()
    expired = [
        state
        for state, record in _STATE_STORE.items()
        if now - record["created_at"] >= STATE_TTL_SECONDS
    ]
    for state in expired:
        _STATE_STORE.pop(state, None)


def create_state(intent: str, metadata: dict | None = None) -> str:
    """Issue a random one-time state token bound to ``intent``."""
    _cleanup_expired()
    state = secrets.token_urlsafe(32)
    while state in _STATE_STORE:
        state = secrets.token_urlsafe(32)
    record: dict = {"intent": intent, "created_at": time.time()}
    if metadata:
        record.update(metadata)
    _STATE_STORE[state] = record
    return state


def consume_state_record(state: str) -> dict | None:
    """Pop and return the record for ``state``; one-time (returns None after)."""
    _cleanup_expired()
    record = _STATE_STORE.pop(state, None)
    if record is None:
        return None
    return record
