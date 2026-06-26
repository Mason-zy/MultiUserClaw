"""Tests for Feishu SSO config fields (Phase 1, TASK-1)."""

from __future__ import annotations

from app.config import Settings


def test_feishu_app_id_field_exists():
    """Settings instance exposes a feishu_app_id attribute defaulting to empty string."""
    s = Settings()
    assert hasattr(s, "feishu_app_id")
    assert s.feishu_app_id == ""


def test_feishu_base_url_default():
    """feishu_base_url defaults to the Feishu open-apis endpoint."""
    s = Settings()
    assert s.feishu_base_url == "https://open.feishu.cn/open-apis"


def test_feishu_env_prefix_mapping(monkeypatch):
    """PLATFORM_FEISHU_APP_ID env var maps to feishu_app_id (env_prefix PLATFORM_)."""
    monkeypatch.setenv("PLATFORM_FEISHU_APP_ID", "cli_xxx")
    s = Settings()
    assert s.feishu_app_id == "cli_xxx"
