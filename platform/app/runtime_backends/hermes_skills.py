from __future__ import annotations

import io
import json
import posixpath
import re
import tarfile
import time
import zipfile

from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import HTTPException, UploadFile, status

from app.container.manager import get_docker_container

HERMES_SKILLS_ROOT = "/opt/data/skills"
_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}$")

_LIST_SKILLS_SCRIPT = r"""
import json
from pathlib import Path

root = Path("/opt/data/skills")


def clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def frontmatter(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"name", "description"}:
            result[key] = clean_scalar(value)
    return result


skills = []
if root.exists():
    for skill_file in sorted(root.rglob("SKILL.md")):
        meta = frontmatter(skill_file)
        rel = skill_file.relative_to(root)
        fallback_name = skill_file.parent.name
        name = meta.get("name") or fallback_name
        skills.append(
            {
                "name": name,
                "description": meta.get("description", ""),
                "source": "hermes",
                "disabled": False,
                "path": str(rel.parent),
            }
        )

print(json.dumps(skills, ensure_ascii=False))
"""


def _exec_output(result) -> tuple[int, bytes]:
    if isinstance(result, tuple):
        exit_code, output = result
    else:
        exit_code = getattr(result, "exit_code", 0)
        output = getattr(result, "output", b"")
    if isinstance(output, str):
        output = output.encode("utf-8")
    return int(exit_code or 0), output or b""


def _clean_skill_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def _skill_frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"name", "description"}:
            result[key] = _clean_skill_scalar(value)
    return result


def _safe_skill_name(value: str) -> str:
    normalized = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    normalized = normalized.removesuffix(".zip").strip()
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", normalized).strip(".-")
    if not normalized or not _SKILL_NAME_RE.match(normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill name")
    return normalized


def _zip_member_target(member_name: str, prefix: str) -> str | None:
    raw = member_name.replace("\\", "/").strip("/")
    if not raw or raw.endswith("/"):
        return None
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or "/../" in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill zip contains unsafe paths")
    if prefix and (normalized == prefix or normalized.startswith(f"{prefix}/")):
        normalized = normalized[len(prefix) :].lstrip("/")
    if not normalized or normalized in {".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def _safe_skill_path(value: str) -> str:
    parts = [part for part in value.strip().replace("\\", "/").strip("/").split("/") if part]
    if not parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill path")
    return "/".join(_safe_skill_name(part) for part in parts)


def _archive_root_from_prefix(prefix: str, filename: str | None) -> str | None:
    first_part = prefix.strip("/").split("/", 1)[0].strip() if prefix.strip("/") else ""
    candidate = first_part or filename or ""
    if not candidate:
        return None
    try:
        return _safe_skill_name(candidate)
    except HTTPException:
        return None


def _build_skills_archive(skill_files: dict[str, dict[str, bytes]]) -> bytes:
    tar_buffer = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        created_dirs: set[str] = set()

        def ensure_dirs(path: str) -> None:
            current = ""
            for part in path.split("/"):
                if not part:
                    continue
                current = f"{current}/{part}" if current else part
                if current in created_dirs:
                    continue
                directory = tarfile.TarInfo(name=current)
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                directory.mtime = now
                tar.addfile(directory)
                created_dirs.add(current)

        for skill_path, files in sorted(skill_files.items()):
            ensure_dirs(skill_path)
            for rel_path, contents in sorted(files.items()):
                target_path = f"{skill_path}/{rel_path}"
                ensure_dirs(posixpath.dirname(target_path))
                info = tarfile.TarInfo(name=target_path)
                info.size = len(contents)
                info.mode = 0o644
                info.mtime = now
                tar.addfile(info, io.BytesIO(contents))

    tar_buffer.seek(0)
    return tar_buffer.read()


def _build_skill_archive(skill_name: str, files: dict[str, bytes]) -> bytes:
    return _build_skills_archive({skill_name: files})


async def upload_skill_zip_to_hermes_container(container_id_or_name: str | None, file: UploadFile) -> dict:
    if not container_id_or_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        )

    contents = await file.read()
    try:
        zip_file = zipfile.ZipFile(io.BytesIO(contents))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded skill must be a zip file") from exc

    names = [name for name in zip_file.namelist() if not name.endswith("/")]
    skill_md_names = sorted(
        name for name in names if name.replace("\\", "/").strip("/").endswith("SKILL.md")
    )
    if not skill_md_names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill zip must contain SKILL.md")

    multi_skill = len(skill_md_names) > 1
    archive_root = _archive_root_from_prefix(skill_md_names[0], file.filename) if multi_skill else None
    skill_files: dict[str, dict[str, bytes]] = {}
    installed: list[dict] = []

    for skill_md_name in skill_md_names:
        skill_md_parts = skill_md_name.replace("\\", "/").strip("/").split("/")
        prefix = "/".join(skill_md_parts[:-1]) if len(skill_md_parts) > 1 else ""
        skill_md = zip_file.read(skill_md_name).decode("utf-8", errors="replace")
        meta = _skill_frontmatter(skill_md)
        skill_name = _safe_skill_name(meta.get("name") or prefix or file.filename or "uploaded-skill")
        install_path = _safe_skill_path(f"{archive_root}/{skill_name}" if archive_root else skill_name)

        extracted: dict[str, bytes] = {}
        for name in names:
            normalized_name = name.replace("\\", "/").strip("/")
            if prefix and not (normalized_name == prefix or normalized_name.startswith(f"{prefix}/")):
                continue
            target = _zip_member_target(name, prefix)
            if target is None:
                continue
            extracted[target] = zip_file.read(name)
        if "SKILL.md" not in extracted:
            extracted["SKILL.md"] = skill_md.encode("utf-8")
        skill_files[install_path] = extracted
        installed.append(
            {
                "name": skill_name,
                "description": meta.get("description", ""),
                "source": "hermes",
                "disabled": False,
                "path": install_path,
            }
        )

    archive = _build_skills_archive(skill_files)
    try:
        container = get_docker_container(container_id_or_name)
        result = container.exec_run(["mkdir", "-p", HERMES_SKILLS_ROOT])
        exit_code, _output = _exec_output(result)
        if exit_code != 0:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to prepare Hermes skills directory")
        ok = container.put_archive(HERMES_SKILLS_ROOT, archive)
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        ) from exc
    except DockerAPIError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to install Hermes skill") from exc

    if not ok:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to install Hermes skill")

    payload = {
        "name": installed[0]["name"],
        "description": installed[0]["description"],
        "source": "hermes",
        "disabled": False,
    }
    if len(installed) > 1:
        payload["installed"] = installed
    return payload


def list_skills_from_hermes_container(container_id_or_name: str | None) -> list[dict]:
    if not container_id_or_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        )

    try:
        container = get_docker_container(container_id_or_name)
        result = container.exec_run(["python3", "-c", _LIST_SKILLS_SCRIPT])
    except DockerNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes runtime container is unavailable",
        ) from exc
    except DockerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list Hermes skills",
        ) from exc

    exit_code, output = _exec_output(result)
    if exit_code != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list Hermes skills",
        )

    try:
        payload = json.loads(output.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected Hermes skills response",
        ) from exc

    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and item.get("name")]


def _validate_skill_path(skill_name: str) -> str:
    """Validate and return the full container path for a skill name (may contain /)."""
    normalized = posixpath.normpath(skill_name)
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill name")
    return posixpath.join(HERMES_SKILLS_ROOT, normalized)


def delete_skill_from_hermes_container(container_id_or_name: str | None, skill_name: str) -> dict:
    if not container_id_or_name:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Hermes runtime container is unavailable")

    skill_path = _validate_skill_path(skill_name)
    try:
        container = get_docker_container(container_id_or_name)
        result = container.exec_run(["rm", "-rf", skill_path])
        exit_code, _ = _exec_output(result)
    except DockerNotFound as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Hermes runtime container is unavailable") from exc
    except DockerAPIError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete skill") from exc

    if exit_code != 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete skill")
    return {"ok": True, "name": skill_name}


def download_skill_from_hermes_container(container_id_or_name: str | None, skill_name: str) -> bytes:
    """Download a skill directory from the container as a zip file."""
    if not container_id_or_name:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Hermes runtime container is unavailable")

    skill_path = _validate_skill_path(skill_name)
    try:
        container = get_docker_container(container_id_or_name)
        # Check skill exists
        result = container.exec_run(["test", "-d", skill_path])
        exit_code, _ = _exec_output(result)
        if exit_code != 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_name}' not found")
        # Get tar archive from container
        bits, _ = container.get_archive(skill_path)
    except DockerNotFound as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Hermes runtime container is unavailable") from exc
    except DockerAPIError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to download skill") from exc

    # Convert tar to zip
    tar_data = b"".join(bits)
    zip_buffer = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r") as tar, \
         zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            # Strip leading directory from path (container returns skill_name/...)
            zf.writestr(member.name, f.read())
    zip_buffer.seek(0)
    return zip_buffer.read()
