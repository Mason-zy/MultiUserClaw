"""Request routing — reverse-proxy from gateway to per-user openclaw containers.

Authenticated users' API requests (chat, sessions, WebSocket) are
forwarded to their individual Docker container.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import docker
import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.container.manager import ensure_running, get_container, get_docker_container
from app.db.engine import async_session, get_db
from app.db.models import User
from app.runtime_backends.hermes_files import normalize_hermes_filemanager_path, read_file_from_hermes_container

logger = logging.getLogger("platform.routes.proxy")
router = APIRouter(prefix="/api/openclaw", tags=["proxy"])


def _dedicated_runtime_backend() -> str:
    return (settings.dedicated_runtime_backend or "openclaw").strip().lower()


def _query_string(request: Request) -> str:
    if isinstance(request.query_params, dict):
        query = urlencode(request.query_params)
        return f"?{query}" if query else ""
    query = str(request.query_params)
    return f"?{query}" if query else ""


def _hermes_auth_headers() -> dict[str, str]:
    if not settings.dedicated_hermes_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.dedicated_hermes_api_key}"}


def _iso_to_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def _hermes_model_to_openclaw_model(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    model_id = str(item.get("id") or item.get("name") or "").strip()
    if not model_id:
        return None
    provider = model_id.split("/", 1)[0] if "/" in model_id else "hermes"
    return {
        "id": model_id,
        "name": model_id,
        "provider": provider,
    }


def _hermes_job_to_openclaw_cron_job(job: dict[str, Any]) -> dict[str, Any]:
    schedule = job.get("schedule")
    if not isinstance(schedule, dict):
        schedule = {}
    schedule_kind = str(schedule.get("kind") or "")
    schedule_expr = None
    schedule_every_ms = None
    if schedule_kind == "cron":
        schedule_expr = schedule.get("expr")
    elif schedule_kind == "interval":
        minutes = schedule.get("minutes")
        if isinstance(minutes, int):
            schedule_every_ms = minutes * 60_000
    elif schedule_kind == "once":
        schedule_expr = schedule.get("run_at")

    return {
        "id": str(job.get("id") or ""),
        "name": job.get("name") or str(job.get("id") or ""),
        "enabled": bool(job.get("enabled", True)),
        "schedule_kind": schedule_kind or "unknown",
        "schedule_display": job.get("schedule_display") or schedule.get("display") or "",
        "schedule_expr": schedule_expr,
        "schedule_every_ms": schedule_every_ms,
        "message": job.get("prompt") or "",
        "deliver": bool(job.get("deliver") and job.get("deliver") != "local"),
        "channel": None if job.get("deliver") in (None, "local") else str(job.get("deliver")),
        "to": None,
        "next_run_at_ms": _iso_to_ms(job.get("next_run_at")),
        "last_run_at_ms": _iso_to_ms(job.get("last_run_at")),
        "last_status": job.get("last_status"),
        "last_error": job.get("last_error"),
        "created_at_ms": _iso_to_ms(job.get("created_at")) or 0,
    }


def _openclaw_cron_schedule_to_hermes(body: dict[str, Any]) -> str:
    cron_expr = str(body.get("cron_expr") or "").strip()
    if cron_expr:
        return cron_expr
    at_iso = str(body.get("at_iso") or "").strip()
    if at_iso:
        return at_iso
    every_seconds = body.get("every_seconds")
    if isinstance(every_seconds, (int, float)) and every_seconds > 0:
        minutes = max(1, math.ceil(float(every_seconds) / 60))
        return f"every {minutes}m"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Hermes cron compatibility requires cron_expr, at_iso, or every_seconds",
    )


def _safe_json_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {}


async def _hermes_request(method: str, base_url: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            return await client.request(
                method=method,
                url=f"{base_url}{path}",
                headers={**_hermes_auth_headers(), **kwargs.pop("headers", {})},
                **kwargs,
            )
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hermes runtime is starting up, please retry in a few seconds",
            ) from exc


async def _proxy_hermes_models(base_url: str) -> JSONResponse:
    response = await _hermes_request("GET", base_url, "/v1/models")
    if response.status_code >= 400:
        return JSONResponse(
            status_code=response.status_code,
            content={"models": [], "configuredModel": settings.default_model, "configuredProviders": {}},
        )
    payload = _safe_json_payload(response)
    raw_models = payload.get("data") if isinstance(payload, dict) else []
    models = [
        mapped
        for mapped in (_hermes_model_to_openclaw_model(item) for item in raw_models or [])
        if mapped is not None
    ]
    return JSONResponse(
        {
            "models": models,
            "configuredModel": settings.default_model,
            "configuredProviders": {"hermes": {"configured": True}},
            "runtime": "hermes",
        }
    )


async def _proxy_hermes_status(base_url: str) -> JSONResponse:
    response = await _hermes_request("GET", base_url, "/health")
    payload = _safe_json_payload(response)
    connected = response.status_code < 400 and (
        not isinstance(payload, dict)
        or str(payload.get("status") or "").lower() in {"", "ok", "healthy", "ready"}
    )
    return JSONResponse(
        status_code=response.status_code,
        content={
            "ok": response.status_code < 400,
            "gateway_connected": connected,
            "config_path": "platform://hermes",
            "workspace": "/workspace",
            "model": settings.default_model,
            "runtime": "hermes",
            "upstream": payload,
        },
    )


async def _proxy_hermes_cron(path: str, request: Request, base_url: str) -> JSONResponse:
    parts = path.strip("/").split("/")
    if parts == ["cron", "jobs"] and request.method == "GET":
        response = await _hermes_request("GET", base_url, f"/api/jobs{_query_string(request)}")
        payload = _safe_json_payload(response)
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        return JSONResponse(
            status_code=response.status_code,
            content=[
                _hermes_job_to_openclaw_cron_job(job)
                for job in jobs
                if isinstance(job, dict)
            ],
        )

    if parts == ["cron", "jobs"] and request.method == "POST":
        body = json.loads((await request.body()) or b"{}")
        hermes_body = {
            "name": body.get("name") or "cron job",
            "prompt": body.get("message") or "",
            "schedule": _openclaw_cron_schedule_to_hermes(body),
            "deliver": body.get("channel") if body.get("deliver") and body.get("channel") else "local",
        }
        response = await _hermes_request("POST", base_url, "/api/jobs", json=hermes_body)
        payload = _safe_json_payload(response)
        job = payload.get("job") if isinstance(payload, dict) else None
        return JSONResponse(
            status_code=response.status_code,
            content=_hermes_job_to_openclaw_cron_job(job) if isinstance(job, dict) else payload,
        )

    if len(parts) == 3 and parts[:2] == ["cron", "jobs"] and request.method == "DELETE":
        response = await _hermes_request("DELETE", base_url, f"/api/jobs/{parts[2]}")
        payload = _safe_json_payload(response)
        return JSONResponse(status_code=response.status_code, content=payload or {"ok": True})

    if len(parts) == 4 and parts[:2] == ["cron", "jobs"] and request.method == "POST":
        if parts[3] == "run":
            response = await _hermes_request("POST", base_url, f"/api/jobs/{parts[2]}/run")
        else:
            return JSONResponse(status_code=404, content={"detail": "Unsupported Hermes cron action"})
        payload = _safe_json_payload(response)
        return JSONResponse(status_code=response.status_code, content=payload or {"ok": True})

    if len(parts) == 4 and parts[:2] == ["cron", "jobs"] and parts[3] == "toggle" and request.method == "PUT":
        body = json.loads((await request.body()) or b"{}")
        action = "resume" if body.get("enabled") else "pause"
        response = await _hermes_request("POST", base_url, f"/api/jobs/{parts[2]}/{action}")
        payload = _safe_json_payload(response)
        job = payload.get("job") if isinstance(payload, dict) else None
        return JSONResponse(
            status_code=response.status_code,
            content=_hermes_job_to_openclaw_cron_job(job) if isinstance(job, dict) else payload,
        )

    return JSONResponse(status_code=404, content={"detail": "Unsupported Hermes cron compatibility path"})


def _hermes_empty_compat(path: str, request: Request) -> JSONResponse | None:
    if path == "commands" and request.method == "GET":
        agent_id = request.query_params.get("agentId") or "main"
        return JSONResponse(
            {
                "agentId": agent_id,
                "commands": [],
                "runtime": "hermes",
                "compatibility": "openclaw-empty",
            }
        )
    if path == "channels/status" and request.method == "GET":
        return JSONResponse(
            {
                "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
                "channelOrder": [],
                "channelLabels": {},
                "channelDetailLabels": {},
                "channelSystemImages": {},
                "channelMeta": [],
                "channels": {},
                "channelAccounts": {},
                "channelDefaultAccountId": {},
                "runtime": "hermes",
            }
        )
    if path == "channels/configured" and request.method == "GET":
        return JSONResponse({"success": True, "channels": [], "runtime": "hermes"})
    if path.startswith("channels/") and path.endswith("/config"):
        if request.method == "GET":
            return JSONResponse({"config": None, "runtime": "hermes"})
        if request.method in {"PUT", "DELETE"}:
            return JSONResponse({"ok": False, "runtime": "hermes", "detail": "Hermes channel config is not exposed through OpenClaw compatibility API"})
    if path.startswith("channels/") and path.endswith("/logout") and request.method == "POST":
        return JSONResponse({"ok": False, "runtime": "hermes", "detail": "Hermes channel logout is not exposed through OpenClaw compatibility API"})
    if path == "plugins" and request.method == "GET":
        return JSONResponse([])
    if path == "plugins/install" and request.method == "POST":
        return JSONResponse({"ok": False, "output": "Hermes runtime does not expose OpenClaw plugin installation API"})
    if path.startswith("plugins/") and request.method == "DELETE":
        return JSONResponse({"ok": False, "runtime": "hermes"})
    if path == "nodes" and request.method == "GET":
        return JSONResponse({"nodes": [], "pending": [], "paired": [], "runtime": "hermes"})
    if path.startswith("nodes/") and request.method in {"GET", "POST", "DELETE"}:
        return JSONResponse({"ok": False, "runtime": "hermes"})
    if path == "marketplaces/skills/search" and request.method == "POST":
        return JSONResponse({"results": [], "runtime": "hermes"})
    if path in {"marketplaces/skills/install", "marketplaces/recommended/install", "marketplaces/git/install-skills"} and request.method == "POST":
        return JSONResponse({"ok": False, "output": "Hermes runtime does not expose OpenClaw marketplace installation API", "installed": [], "errors": []})
    # marketplaces/recommended is handled by openclaw_compat.router
    if path == "marketplaces/git/scan-skills" and request.method == "POST":
        return JSONResponse({"repo": "", "repoName": "", "skills": [], "cacheKey": "", "runtime": "hermes"})
    if path == "settings/gateway/restart" and request.method == "POST":
        return JSONResponse({"success": False, "message": "Hermes runtime restart is managed by the platform container lifecycle"})
    if path == "settings/config" and request.method == "GET":
        return JSONResponse(
            {
                "config": {
                    "gateway": {
                        "bind": "platform",
                        "port": int(getattr(settings, "port", 8080) or 8080),
                        "controlUi": {"allowedOrigins": ["*"]},
                    },
                    "runtime": {"backend": "hermes"},
                },
                "runtime": "hermes",
                "compatibility": "openclaw-readonly",
            }
        )
    if path == "settings/config" and request.method == "PUT":
        return JSONResponse(
            {
                "ok": False,
                "runtime": "hermes",
                "detail": "Hermes settings are managed by platform environment variables",
            }
        )
    if path == "models/config" and request.method == "PUT":
        return JSONResponse({"ok": False, "runtime": "hermes", "detail": "Hermes model config is controlled by platform environment variables"})
    if path == "filemanager/browse" and request.method == "GET":
        requested_path = request.query_params.get("path", "")
        return JSONResponse({"type": "directory", "path": requested_path, "root": "/opt/data", "items": [], "runtime": "hermes"})
    if path in {"filemanager/delete", "filemanager/mkdir"} and request.method in {"DELETE", "POST"}:
        return JSONResponse({"ok": False, "runtime": "hermes", "detail": "Hermes file mutation is limited to upload and serve compatibility endpoints"})
    return None


async def _container_url(db: AsyncSession, user: User) -> str:
    """Get the internal URL for the user's openclaw container, starting it if needed."""
    # Local dev mode: bypass Docker, forward to local openclaw web directly
    if settings.dev_openclaw_url:
        return settings.dev_openclaw_url
    container = await ensure_running(db, user.id)
    return f"http://{container.internal_host}:{container.internal_port}"


# ---------------------------------------------------------------------------
# Container info & maintenance (must be before the catch-all route)
# ---------------------------------------------------------------------------

@router.get("/container/info")
async def container_info(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's container name and status for troubleshooting."""
    container = await get_container(db, user.id)
    if container is None:
        return {"container_name": None, "status": "none", "docker_id": None}
    short_id = user.id[:8]
    prefix = settings.dedicated_runtime_container_name_prefix
    container_name = f"{prefix}-{short_id}"

    # Get real Docker status and port mappings
    docker_status = container.status
    ports: list[dict] = []
    try:
        client = docker.from_env()
        dc = client.containers.get(container.docker_id)
        docker_status = dc.status
        # Extract port mappings: {container_port: [{HostIp, HostPort}]}
        port_bindings = dc.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
        for container_port, bindings in port_bindings.items():
            entry: dict = {"container_port": container_port, "host_port": None}
            if bindings:
                host_port = bindings[0].get("HostPort", "")
                host_ip = bindings[0].get("HostIp", "0.0.0.0")
                if host_port:
                    entry["host_port"] = f"{host_ip}:{host_port}"
            ports.append(entry)
    except Exception:
        pass

    return {
        "container_name": container_name,
        "status": docker_status,
        "docker_id": container.docker_id,
        "created_at": container.created_at.isoformat() if container.created_at else None,
        "ports": ports,
    }


@router.get("/ping")
async def proxy_ping(user: User = Depends(get_current_user)):
    """Authenticated liveness probe for frontend service status checks."""
    return {"message": "pong", "service": "openclaw-proxy", "user_id": user.id}


def _sanitize_openclaw_config(config_json: str) -> tuple[str, list[str]]:
    """Remove known invalid config entries that prevent openclaw from starting.

    Returns (fixed_json, list_of_fixes_applied).
    """
    import json as _json

    fixes: list[str] = []
    try:
        cfg = _json.loads(config_json)
    except _json.JSONDecodeError:
        return config_json, ["Config is not valid JSON — cannot auto-fix"]

    # Fix: remove unknown channel ids (e.g. "web" which is not a valid channel)
    known_channels = {"telegram", "discord", "slack", "signal", "imessage", "feishu", "qqbot", "whatsapp", "matrix", "msteams", "zalo"}
    channels = cfg.get("channels", {})
    bad_channels = [ch for ch in list(channels.keys()) if ch not in known_channels]
    for ch in bad_channels:
        del channels[ch]
        fixes.append(f"Removed unknown channel: channels.{ch}")

    # Fix: remove duplicate plugin entries that cause warnings
    # (just a cleanup, not a blocker)

    return _json.dumps(cfg, indent=2, ensure_ascii=False), fixes


@router.post("/container/doctor-fix")
async def container_doctor_fix(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fix the user's container config and restart.

    Directly edits openclaw.json to remove known invalid entries, then runs
    'openclaw doctor --fix', and restarts the container. Works even when the
    container is in a restart loop.
    """
    container = await get_container(db, user.id)
    if container is None:
        raise HTTPException(status_code=404, detail="No container found")

    short_id = user.id[:8]
    volume_prefix = settings.dedicated_runtime_data_volume_prefix
    volume_name = f"{volume_prefix}-{short_id}"

    try:
        client = docker.from_env()
        dc = client.containers.get(container.docker_id)
        docker_status = dc.status

        # Step 1: Stop the container if it's misbehaving
        need_external_fix = docker_status in ("restarting", "exited", "created")
        if need_external_fix:
            logger.info("Container %s is %s, stopping for repair", short_id, docker_status)
            try:
                dc.stop(timeout=5)
            except Exception:
                try:
                    dc.kill()
                except Exception:
                    pass

        # Step 2: Sanitize config via a lightweight helper container
        # Read config
        read_result = client.containers.run(
            image="python:3.13-alpine",
            command=["cat", "/data/openclaw.json"],
            volumes={volume_name: {"bind": "/data", "mode": "ro"}},
            remove=True,
            detach=False,
            stdout=True,
            stderr=False,
        )
        config_content = read_result.decode("utf-8", errors="replace") if isinstance(read_result, bytes) else str(read_result)
        fixed_content, fixes = _sanitize_openclaw_config(config_content)

        if fixes:
            # Write fixed config back
            import base64
            b64 = base64.b64encode(fixed_content.encode("utf-8")).decode("ascii")
            client.containers.run(
                image="python:3.13-alpine",
                command=["sh", "-c", f"echo '{b64}' | base64 -d > /data/openclaw.json"],
                volumes={volume_name: {"bind": "/data", "mode": "rw"}},
                remove=True,
                detach=False,
            )
            logger.info("Config sanitized for %s: %s", short_id, fixes)

        # Step 3: Run openclaw doctor --fix
        doctor_stdout = ""
        if docker_status == "running" and not need_external_fix:
            exit_code, output = dc.exec_run(
                cmd=["node", "/app/openclaw.mjs", "doctor", "--fix"],
                user="root",
                demux=True,
            )
            doctor_stdout = (output[0] or b"").decode("utf-8", errors="replace")
            doctor_stderr = (output[1] or b"").decode("utf-8", errors="replace")
            if doctor_stderr:
                doctor_stdout += "\n" + doctor_stderr
        else:
            # Run via helper container
            try:
                image = dc.image.id
                result = client.containers.run(
                    image=image,
                    command=["node", "/app/openclaw.mjs", "doctor", "--fix"],
                    volumes={volume_name: {"bind": "/root/.openclaw", "mode": "rw"}},
                    user="root",
                    remove=True,
                    detach=False,
                    stdout=True,
                    stderr=True,
                )
                doctor_stdout = result.decode("utf-8", errors="replace") if isinstance(result, bytes) else str(result)
            except Exception as e:
                doctor_stdout = f"doctor --fix skipped: {e}"

        # Step 4: Restart the container
        dc.reload()
        if dc.status != "running":
            dc.start()
        else:
            dc.restart(timeout=10)

        summary = "\n".join(f"- {f}" for f in fixes) if fixes else "No config issues found"
        return {
            "exit_code": 0,
            "stdout": f"Config fixes:\n{summary}\n\nDoctor output:\n{doctor_stdout}",
            "stderr": "",
            "restarted": True,
        }

    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Docker container not found")
    except Exception as e:
        logger.error("doctor --fix failed for %s: %s", short_id, e, exc_info=True)
        # Try to restart the container even if fix failed
        try:
            dc = client.containers.get(container.docker_id)
            if dc.status != "running":
                dc.start()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# File proxy (supports token as query param for <img> tags)
# Covers both /filemanager/download and /filemanager/serve
# ---------------------------------------------------------------------------

async def _proxy_file_request(request: Request, token: str, bridge_path: str):
    """Shared helper: authenticate via query-param or header, then proxy to runtime."""
    from app.auth.service import decode_token, get_user_by_id

    # Try query-param token first, fall back to Authorization header
    user = None
    if token:
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            async with async_session() as db:
                user = await get_user_by_id(db, payload["sub"])
    if not user:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_token(auth_header[7:])
            if payload and payload.get("type") == "access":
                async with async_session() as db:
                    user = await get_user_by_id(db, payload["sub"])

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    bridge_path = bridge_path.lstrip("/")
    runtime_backend = (settings.dedicated_runtime_backend or "openclaw").strip().lower()
    if runtime_backend == "hermes":
        requested_path = request.query_params.get("path", "")
        normalized_path = requested_path
        if bridge_path == "filemanager/download" and requested_path and not requested_path.startswith("/"):
            normalized_path = normalize_hermes_filemanager_path(requested_path)
        if bridge_path in {"filemanager/serve", "filemanager/download"}:
            async with async_session() as db:
                container = await ensure_running(db, user.id)
            content, media_type = read_file_from_hermes_container(container.docker_id, normalized_path)
            return Response(content=content, media_type=media_type)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dedicated Hermes file proxy only supports filemanager/serve and filemanager/download",
        )
    else:
        async with async_session() as db:
            base_url = await _container_url(db, user)
        target_url = f"{base_url}/api/{bridge_path}"
        if request.query_params:
            target_url += f"?{request.query_params}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.request(method="GET", url=target_url)
        except httpx.ConnectError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Container not ready",
            )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
        headers={k: v for k, v in resp.headers.items() if k.lower() in ("content-disposition",)},
    )


@router.get("/filemanager/download")
async def proxy_file_download(request: Request, token: str = ""):
    """Proxy file download — supports query-param token for <img> tags."""
    return await _proxy_file_request(request, token, "filemanager/download")


@router.get("/filemanager/serve")
async def proxy_file_serve(request: Request, token: str = ""):
    """Proxy file serve — supports query-param token for <img> tags."""
    return await _proxy_file_request(request, token, "filemanager/serve")


# ---------------------------------------------------------------------------
# HTTP reverse proxy  (catch-all for /api/openclaw/{path})
# ---------------------------------------------------------------------------

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(
    path: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Forward HTTP requests to the user's openclaw container."""
    path = path.strip("/")
    if _dedicated_runtime_backend() == "hermes":
        empty_compat = _hermes_empty_compat(path, request)
        if empty_compat is not None:
            return empty_compat

    base_url = await _container_url(db, user)
    # Close the session explicitly so the connection returns to the pool
    # before the potentially long upstream call (up to 120s).
    close_db = getattr(db, "close", None)
    if close_db is not None:
        await close_db()

    if _dedicated_runtime_backend() == "hermes":
        if path == "status" and request.method == "GET":
            return await _proxy_hermes_status(base_url)
        if path == "models" and request.method == "GET":
            return await _proxy_hermes_models(base_url)
        if path == "models/config" and request.method == "PUT":
            return _hermes_empty_compat(path, request)
        if path == "cron/jobs" or path.startswith("cron/jobs/"):
            return await _proxy_hermes_cron(path, request, base_url)

    target_url = f"{base_url}/api/{path}"

    # Forward query params
    if request.query_params:
        target_url += f"?{request.query_params}"

    body = await request.body()

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenClaw container is starting up, please retry in a few seconds",
            )

    from fastapi.responses import Response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
        headers={k: v for k, v in resp.headers.items() if k.lower() in ("content-disposition",)},
    )


# ---------------------------------------------------------------------------
# WebSocket reverse proxy
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def proxy_websocket(
    websocket: WebSocket,
    token: str = "",  # passed as query param ?token=xxx
):
    """Forward WebSocket connections directly to OpenClaw Gateway."""
    from app.auth.service import decode_token, get_user_by_id

    # Authenticate, then release DB session immediately
    async with async_session() as db:
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token")
            return

        user = await get_user_by_id(db, payload["sub"])
        if user is None or not user.is_active:
            await websocket.close(code=4001, reason="User not found")
            return

        if settings.dev_gateway_url:
            target_ws_url = settings.dev_gateway_url
        elif settings.dev_openclaw_url:
            # Fallback: derive gateway URL from openclaw URL
            target_ws_url = settings.dev_openclaw_url.replace("http://", "ws://").replace("https://", "wss://")
            if not target_ws_url.endswith("/ws"):
                target_ws_url = target_ws_url.rstrip("/") + "/ws"
        else:
            container = await ensure_running(db, user.id)
            # Connect to the per-user runtime websocket relay when available.
            target_ws_url = f"ws://{container.internal_host}:{container.internal_port}/ws"
    # DB session is now released — not held during long-lived WebSocket relay

    await websocket.accept()

    import asyncio

    import websockets

    try:
        # Retry connection — container gateway may still be starting
        upstream = None
        for _attempt in range(10):
            try:
                upstream = await websockets.connect(target_ws_url, origin="http://127.0.0.1:8080")
                break
            except (ConnectionRefusedError, OSError):
                if _attempt < 9:
                    await asyncio.sleep(2)
        if upstream is None:
            await websocket.close(code=1013, reason="Container gateway not ready")
            return

        async def client_to_upstream():
            try:
                while True:
                    data = await websocket.receive_text()
                    await upstream.send(data)
            except (WebSocketDisconnect, Exception):
                pass

        async def upstream_to_client():
            try:
                async for message in upstream:
                    try:
                        await websocket.send_text(message)
                    except RuntimeError:
                        break
            except websockets.ConnectionClosed:
                pass

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        finally:
            await upstream.close()

    except Exception as exc:
        logger.error("WebSocket 代理异常: %s", exc, exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/terminal/ws")
async def proxy_terminal_websocket(
    websocket: WebSocket,
    token: str = "",
):
    """Forward WebSocket terminal stream to per-user bridge terminal endpoint."""
    from app.auth.service import decode_token, get_user_by_id

    hermes_terminal_container_id = ""
    async with async_session() as db:
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token")
            return

        user = await get_user_by_id(db, payload["sub"])
        if user is None or not user.is_active:
            await websocket.close(code=4001, reason="User not found")
            return

        if _dedicated_runtime_backend() == "hermes":
            container = await ensure_running(db, user.id)
            container_id = container.docker_id or container.container_name
            if not container_id:
                await websocket.close(code=1013, reason="Hermes container is unavailable")
                return
            hermes_terminal_container_id = container_id

        else:
            if settings.dev_openclaw_url:
                target_ws_url = settings.dev_openclaw_url.replace("http://", "ws://").replace("https://", "wss://")
                target_ws_url = target_ws_url.rstrip("/") + "/api/terminal/ws"
            else:
                container = await ensure_running(db, user.id)
                target_ws_url = f"ws://{container.internal_host}:{container.internal_port}/api/terminal/ws"

    if hermes_terminal_container_id:
        await _bridge_hermes_terminal_websocket(websocket, hermes_terminal_container_id)
        return

    await websocket.accept()

    import asyncio

    import websockets

    try:
        upstream = None
        for _attempt in range(10):
            try:
                upstream = await websockets.connect(target_ws_url, origin="http://127.0.0.1:8080")
                break
            except (ConnectionRefusedError, OSError):
                if _attempt < 9:
                    await asyncio.sleep(1)
        if upstream is None:
            await websocket.close(code=1013, reason="Terminal service not ready")
            return

        async def client_to_upstream():
            try:
                while True:
                    data = await websocket.receive_text()
                    await upstream.send(data)
            except (WebSocketDisconnect, Exception):
                pass

        async def upstream_to_client():
            try:
                async for message in upstream:
                    try:
                        await websocket.send_text(message)
                    except RuntimeError:
                        break
            except websockets.ConnectionClosed:
                pass

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        try:
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        finally:
            await upstream.close()
    except Exception as exc:
        logger.error("Terminal WebSocket 代理异常: %s", exc, exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _terminal_command_from_init(raw: str) -> tuple[str, str]:
    try:
        payload = json.loads(raw)
    except ValueError:
        return "bash -il", ""
    if not isinstance(payload, dict) or payload.get("type") != "init":
        return "bash -il", ""
    command = str(payload.get("command") or "bash -il").strip() or "bash -il"
    session_key = str(payload.get("session_key") or "")
    return command, session_key


def _terminal_socket_target(sock):
    return getattr(sock, "_sock", sock)


def _terminal_socket_recv(sock, size: int = 4096) -> bytes:
    target = _terminal_socket_target(sock)
    data = target.recv(size)
    return data or b""


def _terminal_socket_send(sock, data: bytes) -> None:
    target = _terminal_socket_target(sock)
    if hasattr(target, "sendall"):
        target.sendall(data)
    else:
        target.send(data)


def _terminal_socket_close(sock) -> None:
    for target in (sock, _terminal_socket_target(sock)):
        close = getattr(target, "close", None)
        if close is None:
            continue
        try:
            close()
        except Exception:
            pass


def _start_hermes_terminal_socket(container_id_or_name: str, command: str):
    container = get_docker_container(container_id_or_name)
    result = container.exec_run(
        ["sh", "-lc", command],
        stdin=True,
        stdout=True,
        stderr=True,
        tty=True,
        socket=True,
        workdir="/workspace",
    )
    return getattr(result, "output", result[1] if isinstance(result, tuple) else result)


async def _bridge_hermes_terminal_websocket(websocket: WebSocket, container_id_or_name: str) -> None:
    await websocket.accept()
    terminal_socket = None
    try:
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        command, session_key = _terminal_command_from_init(init_raw)
        terminal_socket = await asyncio.to_thread(_start_hermes_terminal_socket, container_id_or_name, command)
        await websocket.send_text(json.dumps({"type": "session", "session_key": session_key, "reused": False}))
        await websocket.send_text(json.dumps({"type": "started", "command": command}))

        async def socket_to_client():
            while True:
                data = await asyncio.to_thread(_terminal_socket_recv, terminal_socket)
                if not data:
                    break
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "output",
                            "data": data.decode("utf-8", errors="replace"),
                        }
                    )
                )
            await websocket.send_text(json.dumps({"type": "exit", "code": "", "signal": ""}))

        async def client_to_socket():
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                except ValueError:
                    await asyncio.to_thread(_terminal_socket_send, terminal_socket, raw.encode("utf-8"))
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") == "input":
                    text = str(payload.get("data") or "")
                    await asyncio.to_thread(_terminal_socket_send, terminal_socket, text.encode("utf-8"))

        tasks = [asyncio.create_task(socket_to_client()), asyncio.create_task(client_to_socket())]
        try:
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
        finally:
            await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.TimeoutError:
        await websocket.send_text(json.dumps({"type": "error", "message": "Terminal init message timed out"}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Hermes terminal bridge error: %s", exc, exc_info=True)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass
    finally:
        if terminal_socket is not None:
            await asyncio.to_thread(_terminal_socket_close, terminal_socket)
        try:
            await websocket.close()
        except Exception:
            pass
