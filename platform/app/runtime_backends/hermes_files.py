from __future__ import annotations

import io
import mimetypes
import posixpath
import tarfile
import time

from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import HTTPException, UploadFile, status

from app.container.manager import get_docker_container

DEFAULT_HERMES_UPLOAD_DIR = "workspace/uploads"
HERMES_DATA_ROOT = "/opt/data"
SHARED_HERMES_CONTAINER_NAME = "openclaw-shared"


def normalize_hermes_upload_dir(target_dir: str | None, default: str = DEFAULT_HERMES_UPLOAD_DIR) -> str:
    raw = (target_dir or default).strip().replace("\\", "/")
    raw = raw.removeprefix("~/.openclaw/")
    raw = raw.removeprefix("/root/.openclaw/")
    raw = raw.removeprefix("root/.openclaw/")
    raw = raw.lstrip("/")
    normalized = posixpath.normpath(raw or default)
    if normalized in {"", "."}:
        normalized = default
    if normalized == ".." or normalized.startswith("../"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hermes upload path cannot escape the workspace",
        )
    if not (
        normalized == "workspace"
        or normalized.startswith("workspace/")
        or normalized.startswith("workspace-")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hermes upload path must be under a workspace directory",
        )
    return normalized.rstrip("/")


def normalize_hermes_workspace_path(requested_path: str | None) -> str:
    raw = (requested_path or "").strip().replace("\\", "/")
    raw = raw.removeprefix("~/.openclaw/")
    raw = raw.removeprefix("/root/.openclaw/")
    raw = raw.removeprefix("root/.openclaw/")
    raw = raw.lstrip("/")
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hermes file path is unavailable",
        )
    if not (
        normalized == "workspace"
        or normalized.startswith("workspace/")
        or normalized.startswith("workspace-")
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hermes file path is unavailable",
        )
    return normalized


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "upload.bin").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return normalized or "upload.bin"


def _build_upload_archive(relative_path: str, contents: bytes) -> bytes:
    tar_buffer = io.BytesIO()
    now = int(time.time())
    upload_dir = posixpath.dirname(relative_path)

    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        home_dir = tarfile.TarInfo(name="home")
        home_dir.type = tarfile.DIRTYPE
        home_dir.mode = 0o755
        home_dir.mtime = now
        tar.addfile(home_dir)

        openclaw_link = tarfile.TarInfo(name="home/.openclaw")
        openclaw_link.type = tarfile.SYMTYPE
        openclaw_link.linkname = HERMES_DATA_ROOT
        openclaw_link.mode = 0o777
        openclaw_link.mtime = now
        tar.addfile(openclaw_link)

        current_dir = ""
        for part in upload_dir.split("/"):
            if not part:
                continue
            current_dir = f"{current_dir}/{part}" if current_dir else part
            directory = tarfile.TarInfo(name=current_dir)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            directory.mtime = now
            tar.addfile(directory)

        upload_file = tarfile.TarInfo(name=relative_path)
        upload_file.size = len(contents)
        upload_file.mode = 0o644
        upload_file.mtime = now
        tar.addfile(upload_file, io.BytesIO(contents))

    tar_buffer.seek(0)
    return tar_buffer.read()


def _ensure_openclaw_compat_links(container) -> None:
    result = container.exec_run(
        [
            "sh",
            "-lc",
            "mkdir -p /opt/data/home /root "
            "&& ln -sfn /opt/data /opt/data/home/.openclaw "
            "&& ln -sfn /opt/data /root/.openclaw",
        ]
    )
    exit_code = getattr(result, "exit_code", result[0] if isinstance(result, tuple) else 0)
    if exit_code != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare Hermes OpenClaw workspace compatibility links",
        )


async def write_upload_to_hermes_container(
    container_id_or_name: str | None,
    file: UploadFile,
    target_dir: str | None,
) -> dict:
    if not container_id_or_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        )

    contents = await file.read()
    original_name = _safe_filename(file.filename)
    stored_name = f"{int(time.time() * 1000)}-{original_name}"
    upload_dir = normalize_hermes_upload_dir(target_dir)
    relative_path = f"{upload_dir}/{stored_name}"
    archive = _build_upload_archive(relative_path, contents)

    try:
        container = get_docker_container(container_id_or_name)
        _ensure_openclaw_compat_links(container)
        ok = container.put_archive(HERMES_DATA_ROOT, archive)
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        ) from exc
    except DockerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write upload into Hermes workspace",
        ) from exc

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write upload into Hermes workspace",
        )

    return {
        "path": relative_path,
        "name": stored_name,
        "original_name": original_name,
        "size": len(contents),
        "content_type": file.content_type or "application/octet-stream",
    }


def read_file_from_hermes_container(
    container_id_or_name: str | None,
    requested_path: str | None,
) -> tuple[bytes, str]:
    if not container_id_or_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        )

    relative_path = normalize_hermes_workspace_path(requested_path)
    try:
        container = get_docker_container(container_id_or_name)
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        ) from exc

    try:
        stream, _stat = container.get_archive(f"{HERMES_DATA_ROOT}/{relative_path}")
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hermes file not found",
        ) from exc
    except DockerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read Hermes file",
        ) from exc

    archive = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar:
        for member in tar:
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            media_type = mimetypes.guess_type(relative_path)[0] or "application/octet-stream"
            return extracted.read(), media_type

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Hermes file not found",
    )
