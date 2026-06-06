"""GET/PUT /api/openclaw/models — per-user model provider configuration.

Reads and writes the hermes container's /opt/data/config.yaml so each
user can add providers, configure API keys, and switch default models.
"""

from __future__ import annotations

import io
import logging
import tarfile
import time

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.container.manager import ensure_running, get_docker_container
from app.db.engine import get_db
from app.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/openclaw", tags=["models"])


# ---------------------------------------------------------------------------
# Helpers — read/write container config.yaml
# ---------------------------------------------------------------------------

def _read_container_config(container_name: str) -> dict:
    container = get_docker_container(container_name)
    result = container.exec_run(["cat", "/opt/data/config.yaml"], user="hermes")
    if result.exit_code != 0:
        return {}
    try:
        return yaml.safe_load(result.output.decode("utf-8")) or {}
    except Exception:
        return {}


def _write_container_config(container_name: str, config: dict) -> None:
    content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode("utf-8")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        info = tarfile.TarInfo(name="config.yaml")
        info.size = len(content)
        info.mode = 0o644
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(content))
    tar_buffer.seek(0)
    container = get_docker_container(container_name)
    ok = container.put_archive("/opt/data", tar_buffer.read())
    if not ok:
        raise RuntimeError("failed to write config.yaml into container")
    container.exec_run(["chown", "hermes:hermes", "/opt/data/config.yaml"], user="root")


def _container_name(user_id: str) -> str:
    return f"hermes-user-{user_id[:8]}"


# ---------------------------------------------------------------------------
# Format conversion: hermes config.yaml <-> frontend providers format
# ---------------------------------------------------------------------------

def _hermes_to_frontend(config: dict) -> dict:
    """Convert hermes config.yaml to frontend format."""
    from app.config import settings

    default_model = ""
    model_section = config.get("model") or {}
    if isinstance(model_section, dict):
        default_model = model_section.get("default", "")

    providers: dict = {}

    # Platform default model — read-only, no API key exposed
    if settings.default_model:
        providers["platform"] = {
            "baseUrl": "",
            "api": "openai-completions",
            "apiKey": "",
            "models": [{"id": settings.default_model, "name": settings.default_model}],
            "_system": True,
        }

    # User-added providers
    custom_providers = config.get("custom_providers") or []
    for cp in custom_providers:
        if not isinstance(cp, dict):
            continue
        name = cp.get("name", "")
        if not name or name == "platform-gateway":
            continue
        providers[name] = {
            "baseUrl": cp.get("base_url", ""),
            "api": "openai-completions",
            "apiKey": cp.get("api_key", ""),
            "models": cp.get("models") or [],
        }

    return {
        "models": [],
        "configuredModel": default_model,
        "configuredProviders": providers,
    }


def _frontend_to_hermes_providers(providers: dict) -> list[dict]:
    """Convert frontend providers format to hermes custom_providers list."""
    result = []
    for name, p in providers.items():
        if not isinstance(p, dict):
            continue
        entry = {
            "name": name,
            "base_url": p.get("baseUrl", ""),
            "api_key": p.get("apiKey", ""),
        }
        models = p.get("models")
        if models:
            entry["models"] = models
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UpdateModelsConfig(BaseModel):
    providers: dict | None = None
    defaultModel: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    container = await ensure_running(db, user.id)
    container_name = _container_name(user.id)
    try:
        config = _read_container_config(container_name)
    except Exception as e:
        logger.warning("Failed to read config from %s: %s", container_name, e)
        config = {}
    return _hermes_to_frontend(config)


@router.put("/models/config")
async def update_models_config(
    body: UpdateModelsConfig,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    container = await ensure_running(db, user.id)
    container_name = _container_name(user.id)

    try:
        config = _read_container_config(container_name)
    except Exception:
        config = {}

    if body.providers is not None:
        existing_providers = config.get("custom_providers") or []
        platform_gateway = [
            p for p in existing_providers
            if isinstance(p, dict) and p.get("name") == "platform-gateway"
        ]
        new_providers = [
            p for p in _frontend_to_hermes_providers(body.providers)
            if p.get("name") != "platform"
        ]
        config["custom_providers"] = platform_gateway + new_providers

    if body.defaultModel is not None:
        if "model" not in config or not isinstance(config.get("model"), dict):
            config["model"] = {}
        config["model"]["default"] = body.defaultModel

    try:
        _write_container_config(container_name, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {e}")

    return {"ok": True}
