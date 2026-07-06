"""Tests for Feishu API client (Phase 3, TASK-1).

Mock httpx.AsyncClient to avoid real network calls.
"""

from __future__ import annotations

import json
import pytest

from app.services import feishu_client


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    """Records calls and returns scripted responses keyed by URL substring."""

    def __init__(self, responses: dict[str, list[dict]] | None = None, default: dict | None = None):
        # responses: url_substring -> list of payloads (consumed in order)
        self.responses = responses or {}
        self.default = default or {}
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _match(self, url: str) -> dict:
        for key, queue in self.responses.items():
            if key in url:
                if queue:
                    return queue.pop(0)
        return self.default

    async def post(self, url, json=None, **kwargs):
        self.calls.append(("POST", url, json, None))
        return _FakeResponse(self._match(url))

    async def get(self, url, headers=None, params=None, **kwargs):
        self.calls.append(("GET", url, None, params))
        return _FakeResponse(self._match(url))


@pytest.fixture
def patch_settings(monkeypatch):
    """Point feishu_client.settings at fixed credentials for assertions."""
    fake = type("S", (), {})()
    fake.feishu_app_id = "cli_test_app"
    fake.feishu_app_secret = "secret_test"
    fake.feishu_base_url = "https://open.feishu.cn/open-apis"
    monkeypatch.setattr(feishu_client, "settings", fake)
    return fake


async def test_get_full_user_info_returns_claims(monkeypatch, patch_settings):
    """Full code->claims flow returns sub/name/email/department."""
    responses = {
        "/auth/v3/app_access_token/internal": [{"code": 0, "app_access_token": "APP_TOK"}],
        "/authen/v1/oidc/access_token": [{
            "code": 0, "data": {"access_token": "USER_TOK"},
        }],
        "/authen/v1/user_info": [{
            "code": 0,
            "data": {
                "open_id": "ou_abc", "name": "Alice", "email": "a@b.com",
                "job_title": "Eng", "avatar_url": "http://x/a.png",
            },
        }],
        "/contact/v3/users/": [{
            "code": 0,
            "data": {"user": {"department_ids": ["od_1"]}},
        }],
        "/contact/v3/departments/": [{
            "code": 0,
            "data": {"department": {"name": "R&D"}},
        }],
    }
    fake = FakeAsyncClient(responses=responses)
    monkeypatch.setattr(feishu_client.httpx, "AsyncClient", lambda *a, **kw: fake)

    claims = await feishu_client.get_full_user_info("CODE")
    assert claims["sub"] == "ou_abc"
    assert claims["name"] == "Alice"
    assert claims["email"] == "a@b.com"
    assert claims["department"] == "R&D"


async def test_get_app_access_token_raises_on_error(monkeypatch, patch_settings):
    """Non-zero code from app_access_token endpoint raises with action text."""
    fake = FakeAsyncClient(default={"code": 99999, "msg": "bad creds"})
    monkeypatch.setattr(feishu_client.httpx, "AsyncClient", lambda *a, **kw: fake)
    with pytest.raises(Exception) as exc:
        await feishu_client.get_app_access_token()
    assert "app_access_token" in str(exc.value)


async def test_get_user_department_fallback_unknown(monkeypatch, patch_settings):
    """When contact API fails, department falls back to 'unknown'."""
    fake = FakeAsyncClient(default={"code": 99998, "msg": "no permission"})
    monkeypatch.setattr(feishu_client.httpx, "AsyncClient", lambda *a, **kw: fake)
    dept = await feishu_client.get_user_department("ou_x", "APP_TOK")
    assert dept == "unknown"


async def test_uses_settings_for_credentials(monkeypatch, patch_settings):
    """Client reads app_id/app_secret/base_url from settings (not hardcoded)."""
    captured = {}

    class CaptureClient(FakeAsyncClient):
        async def post(self, url, json=None, **kwargs):
            captured["url"] = url
            captured["body"] = json
            return _FakeResponse({"code": 0, "app_access_token": "TOK"})

    fake = CaptureClient()
    monkeypatch.setattr(feishu_client.httpx, "AsyncClient", lambda *a, **kw: fake)
    await feishu_client.get_app_access_token()
    assert captured["body"]["app_id"] == "cli_test_app"
    assert captured["body"]["app_secret"] == "secret_test"
    assert "open.feishu.cn/open-apis" in captured["url"]
