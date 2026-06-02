#!/usr/bin/env python3
"""Generic guardrail checks before container image builds.

This script intentionally uses only the Python standard library. It scans a
repository for common container build inputs, infers external network sources,
performs lightweight DNS/TCP/HTTPS probes without downloading large files, and
can generate foreground log-wrapping snippets for long builds.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_TIMEOUT = 5.0
MAX_FILE_BYTES = 2_000_000
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
}


@dataclass
class Finding:
    severity: str
    message: str
    source: str = ""


@dataclass
class Endpoint:
    key: str
    host: str
    port: int = 443
    scheme: str = "https"
    path: str = "/"
    reason: str = ""
    source: str = ""
    kind: str = "generic"

    def url(self) -> str:
        return f"{self.scheme}://{self.host}{self.path or '/'}"


@dataclass
class ProbeResult:
    endpoint: Endpoint
    dns_ok: bool = False
    tcp_ok: bool = False
    https_ok: bool | None = None
    status: int | None = None
    error: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        if not self.dns_ok or not self.tcp_ok:
            return False
        if self.endpoint.scheme == "https" and self.https_ok is False:
            return False
        return True


@dataclass
class DockerManifestResult:
    image: str
    source: str = ""
    ok: bool = False
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class DockerPullResult:
    image: str
    source: str = ""
    ok: bool = False
    error: str = ""
    local_only_uncertain: bool = False
    elapsed_ms: int = 0


@dataclass
class ArtifactTarget:
    ecosystem: str
    base_url: str
    package: str
    source: str


@dataclass
class ArtifactProbeResult:
    ecosystem: str
    base_url: str
    package: str
    source: str = ""
    artifact_url: str = ""
    ok: bool = False
    status: int | None = None
    error: str = ""
    elapsed_ms: int = 0


def iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def endpoint_from_url(url: str, reason: str, source: str, kind: str = "url") -> Endpoint | None:
    if "{" in url or "}" in url:
        return None
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    if not is_external_host(parsed.hostname):
        return None
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    try:
        port = parsed.port or (80 if scheme == "http" else 443)
    except ValueError:
        return None
    path = parsed.path or "/"
    return Endpoint(
        key=f"{scheme}://{parsed.hostname}:{port}",
        host=parsed.hostname,
        port=port,
        scheme=scheme,
        path=path,
        reason=reason,
        source=source,
        kind=kind,
    )


def add_endpoint(endpoints: dict[str, Endpoint], endpoint: Endpoint | None) -> None:
    if endpoint is None:
        return
    existing = endpoints.get(endpoint.key)
    if existing:
        if endpoint.reason not in existing.reason:
            existing.reason += f"; {endpoint.reason}"
        if endpoint.source and endpoint.source not in existing.source:
            existing.source += f"; {endpoint.source}"
        return
    endpoints[endpoint.key] = endpoint


def registry_hosts_for_image(image: str) -> list[str]:
    image = image.strip().strip("'\"")
    if not image or image.startswith("${") or "{" in image or "}" in image:
        return []
    if "/" not in image:
        if image in {"scratch"}:
            return []
        return ["registry-1.docker.io", "auth.docker.io"]
    first = image.split("/", 1)[0]
    if "." in first or ":" in first or first == "localhost":
        return [first.split(":")[0]]
    return ["registry-1.docker.io", "auth.docker.io"]


def is_external_host(host: str) -> bool:
    host = host.strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return not (
            host.startswith("10.")
            or host.startswith("192.168.")
            or re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", host)
            or host.startswith("127.")
        )
    return "." in host


def discover_container_files(root: Path) -> list[Path]:
    names = []
    for path in iter_files(root):
        name = path.name.lower()
        if (
            name.startswith("dockerfile")
            or name.startswith("containerfile")
            or name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
            or re.match(r"docker-compose\..+\.(ya?ml)$", name)
            or re.match(r"compose\..+\.(ya?ml)$", name)
        ):
            names.append(path)
    return sorted(names)


def discover_package_manifests(root: Path) -> list[Path]:
    interesting = {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        ".npmrc",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "uv.lock",
        "poetry.lock",
        "pip.conf",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Cargo.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Gemfile",
        "Gemfile.lock",
        "nuget.config",
    }
    found = []
    for path in iter_files(root):
        if path.name in interesting:
            found.append(path)
    return sorted(found)


URL_RE = re.compile(r"https?://[^\s'\"<>\\)\|]+")
FROM_RE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)", re.IGNORECASE)
IMAGE_RE = re.compile(r"^\s*image:\s*([^\s#]+)", re.IGNORECASE)
PY_INDEX_RE = re.compile(r"(?:--index-url|--extra-index-url|--default-index|-i)\s+([^\s\\]+)")
COPY_RE = re.compile(r"^\s*(?:COPY|ADD)\s+(.*)$", re.IGNORECASE)
PY_PACKAGE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*")
PY_INDEX_DEFAULTS = (
    "https://pypi.org/simple/",
    "https://pypi.python.org/simple/",
)


def clean_image_ref(image: str) -> str:
    image = image.strip().strip("'\"")
    if " AS " in image.upper():
        image = re.split(r"\s+AS\s+", image, flags=re.IGNORECASE)[0]
    return image


def is_dynamic_ref(value: str) -> bool:
    return not value or value.startswith("${") or "{" in value or "}" in value or "$" in value


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_default_python_index(index_url: str) -> bool:
    return index_url.rstrip("/") in {url.rstrip("/") for url in PY_INDEX_DEFAULTS}


def add_image(images: dict[str, str], image: str, source: str) -> None:
    image = clean_image_ref(image)
    if is_dynamic_ref(image) or image == "scratch":
        return
    existing = images.get(image)
    if existing:
        if source not in existing:
            images[image] += f"; {source}"
        return
    images[image] = source


def discover_shell_references(text: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r"[\w./-]+\.sh\b", text):
        refs.add(match.group(0).lstrip("./"))
    return refs


def has_crlf_shebang(path: Path) -> bool:
    try:
        data = path.read_bytes()[:4096]
    except OSError:
        return False
    first_line = data.split(b"\n", 1)[0]
    return first_line.startswith(b"#!") and first_line.endswith(b"\r")


def scan_crlf_shebangs(root: Path, container_files: list[Path], findings: list[Finding]) -> None:
    referenced: set[str] = set()
    for path in container_files:
        referenced.update(discover_shell_references(read_text(path)))
    referenced_names = {Path(ref).name for ref in referenced}

    def is_referenced(source: str) -> bool:
        basename = Path(source).name
        for ref in referenced:
            normalized_ref = ref.replace("\\", "/").lstrip("/")
            if source == normalized_ref or source.endswith("/" + normalized_ref):
                return True
        return basename in referenced_names

    for path in iter_files(root):
        source = rel(path, root)
        if path.suffix.lower() not in {".sh", ".bash"} and not is_referenced(source):
            continue
        if not has_crlf_shebang(path):
            continue
        severity = "BLOCKER" if is_referenced(source) else "WARN"
        findings.append(
            Finding(
                severity,
                "Shell script has a CRLF shebang; Linux containers may fail with 'no such file or directory' when it is used as ENTRYPOINT/CMD or executed directly.",
                source,
            )
        )


def parse_copy_sources(rest: str) -> list[str]:
    rest = rest.split("#", 1)[0].strip()
    if not rest:
        return []
    try:
        tokens = shlex.split(rest)
    except ValueError:
        tokens = rest.split()
    tokens = [token for token in tokens if not token.startswith("--")]
    if len(tokens) < 2:
        return []
    return tokens[:-1]


def scan_missing_copy_sources(root: Path, container_files: list[Path], findings: list[Finding]) -> None:
    for path in container_files:
        lower_name = path.name.lower()
        if not (lower_name.startswith("dockerfile") or lower_name.startswith("containerfile")):
            continue
        source = rel(path, root)
        context_dir = path.parent
        for line_no, line in enumerate(read_text(path).splitlines(), start=1):
            match = COPY_RE.match(line)
            if not match:
                continue
            for copy_source in parse_copy_sources(match.group(1)):
                if is_dynamic_ref(copy_source) or copy_source.startswith("--from="):
                    continue
                normalized = copy_source.strip().strip("'\"").replace("\\", "/")
                if normalized.startswith("/") or normalized in {".", "./"}:
                    continue
                if any(ch in normalized for ch in "*?["):
                    continue
                candidate = (context_dir / normalized).resolve()
                try:
                    candidate.relative_to(context_dir.resolve())
                except ValueError:
                    findings.append(
                        Finding(
                            "BLOCKER",
                            f"Dockerfile {line_no} copies '{copy_source}', which escapes the build context.",
                            source,
                        )
                    )
                    continue
                if not candidate.exists():
                    findings.append(
                        Finding(
                            "BLOCKER",
                            f"Dockerfile {line_no} copies missing build-context path '{copy_source}'.",
                            source,
                        )
                    )


def add_python_index_checks(
    text: str,
    source: str,
    endpoints: dict[str, Endpoint],
    findings: list[Finding],
    warned_indexes: set[tuple[str, str]],
    python_indexes: dict[str, set[str]],
) -> None:
    for match in PY_INDEX_RE.finditer(text):
        raw = match.group(1).strip().strip("'\"")
        endpoint = endpoint_from_url(raw, "Python package index configured in build command", source, "python-index")
        add_endpoint(endpoints, endpoint)
        if endpoint:
            sample = urljoin(endpoint.url().rstrip("/") + "/", "wheel/")
            add_endpoint(
                endpoints,
                endpoint_from_url(sample, "Python package index simple page for wheel", source, "python-index"),
            )
            warn_key = (raw, source)
            if not is_default_python_index(raw) and warn_key not in warned_indexes:
                warned_indexes.add(warn_key)
                findings.append(
                    Finding(
                        "WARN",
                        f"Python package index '{raw}' should be artifact-tested; some mirrors return 200 for /simple but 403 for wheel files.",
                        source,
                    )
                )
            python_indexes.setdefault(raw, set()).add(source)


def extract_python_package_names(text: str, path: Path) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = normalize_package_name(name.strip())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            names.append(cleaned)

    if path.name in {"requirements.txt", "requirements-dev.txt"}:
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "http://", "https://", "git+")):
                continue
            match = PY_PACKAGE_TOKEN_RE.match(line)
            if match:
                add(match.group(0))
        return names

    if path.name == "pyproject.toml":
        for match in re.finditer(r"['\"]([A-Za-z0-9][A-Za-z0-9_.-]*)\s*(?:\[.*?\])?\s*(?:[<>=!~]=|[<>=~])", text):
            add(match.group(1))
        for match in re.finditer(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*=", text, flags=re.MULTILINE):
            if "[project]" not in text[: match.start()] and "[tool.poetry.dependencies]" not in text[: match.start()]:
                continue
            add(match.group(1))
        return names

    if path.name == "uv.lock":
        for match in re.finditer(r'^\s*name\s*=\s*"([^"]+)"', text, flags=re.MULTILINE):
            add(match.group(1))
        return names

    return names


def choose_artifact_targets(
    python_indexes: dict[str, set[str]],
    python_packages: dict[str, set[str]],
    limit: int,
) -> list[ArtifactTarget]:
    if not python_indexes or not python_packages or limit == 0:
        return []
    package_order = sorted(python_packages, key=lambda name: (-len(python_packages[name]), name))
    targets: list[ArtifactTarget] = []
    max_targets = max(0, limit)
    for index_url, sources in sorted(python_indexes.items()):
        if is_default_python_index(index_url):
            continue
        for package in package_order[:3]:
            targets.append(
                ArtifactTarget(
                    ecosystem="python",
                    base_url=index_url,
                    package=package,
                    source="; ".join(sorted(sources | python_packages.get(package, set()))),
                )
            )
            if len(targets) >= max_targets:
                return targets
    return targets


def analyze_text(
    path: Path,
    root: Path,
    text: str,
    endpoints: dict[str, Endpoint],
    findings: list[Finding],
    images: dict[str, str],
    warned_indexes: set[tuple[str, str]],
    python_indexes: dict[str, set[str]],
    python_packages: dict[str, set[str]],
) -> None:
    source = rel(path, root)
    lower = text.lower()
    is_lockfile = path.name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum", "Gemfile.lock"}
    lower_name = path.name.lower()
    is_container_file = (
        lower_name.startswith("dockerfile")
        or lower_name.startswith("containerfile")
        or lower_name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
        or bool(re.match(r"docker-compose\..+\.(ya?ml)$", lower_name))
        or bool(re.match(r"compose\..+\.(ya?ml)$", lower_name))
    )
    explicit_url_scan = is_container_file or path.name in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "pip.conf", ".npmrc", "nuget.config"}

    if explicit_url_scan and not is_lockfile:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("#"):
                continue
            for url in URL_RE.findall(raw_line):
                clean = url.rstrip(".,;")
                add_endpoint(endpoints, endpoint_from_url(clean, "explicit URL in build-related files", source, "url"))
        add_python_index_checks(text, source, endpoints, findings, warned_indexes, python_indexes)

    for package in extract_python_package_names(text, path):
        python_packages.setdefault(package, set()).add(source)

    for line in text.splitlines():
        from_match = FROM_RE.match(line)
        if from_match:
            image = clean_image_ref(from_match.group(1))
            add_image(images, image, source)
            for host in registry_hosts_for_image(image):
                add_endpoint(
                    endpoints,
                    Endpoint(
                        key=f"https://{host}:443",
                        host=host,
                        reason=f"base image registry for {image}",
                        source=source,
                        kind="registry",
                    ),
                )
        image_match = IMAGE_RE.match(line)
        if image_match:
            image = clean_image_ref(image_match.group(1))
            add_image(images, image, source)
            for host in registry_hosts_for_image(image):
                add_endpoint(
                    endpoints,
                    Endpoint(
                        key=f"https://{host}:443",
                        host=host,
                        reason=f"compose image registry for {image}",
                        source=source,
                        kind="registry",
                    ),
                )

    if re.search(r"\bapt(-get)?\s+.*\b(update|install)\b", lower):
        for host in ("deb.debian.org", "security.debian.org"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Debian/Ubuntu apt packages", source=source, kind="apt"))

    if re.search(r"\bapk\s+add\b|\bapk\s+update\b", lower):
        host = "dl-cdn.alpinelinux.org"
        add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Alpine apk packages", source=source, kind="apk"))

    if re.search(r"\b(yum|dnf|microdnf)\s+", lower):
        findings.append(Finding("WARN", "RPM package manager found; repository hosts depend on the base image repo files.", source))

    if re.search(r"\b(npm|npx|yarn|pnpm)\s+(install|ci|add|dlx|exec|create|i)\b", lower) or path.name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        host = "registry.npmjs.org"
        add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Node package registry", source=source, kind="npm"))

    if re.search(r"\b(pip|uv|poetry)\s+", lower) or path.name in {"pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock"}:
        for host in ("pypi.org", "files.pythonhosted.org"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Python package index/artifacts", source=source, kind="python"))

    if path.name == "go.mod" or re.search(r"\bgo\s+(mod\s+download|get|install|build)\b", lower):
        for host in ("proxy.golang.org", "sum.golang.org"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Go modules", source=source, kind="go"))

    if path.name in {"Cargo.toml", "Cargo.lock"} or re.search(r"\bcargo\s+(build|fetch|install|update)\b", lower):
        for host in ("index.crates.io", "static.crates.io", "crates.io"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Rust crates", source=source, kind="cargo"))

    if path.name in {"pom.xml", "build.gradle", "build.gradle.kts"} or re.search(r"\b(mvn|gradle|gradlew)\b", lower):
        for host in ("repo.maven.apache.org", "plugins.gradle.org", "services.gradle.org"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Java/Gradle dependencies", source=source, kind="java"))

    if "playwright" in lower:
        for host in ("cdn.playwright.dev", "playwright.azureedge.net"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Playwright browser downloads", source=source, kind="browser"))

    if "puppeteer" in lower:
        for host in ("storage.googleapis.com", "chrome-for-testing-public.storage.googleapis.com"):
            add_endpoint(endpoints, Endpoint(f"https://{host}:443", host, reason="Puppeteer/Chrome downloads", source=source, kind="browser"))

    if re.search(r"\bgit\s+clone\b|\bcurl\b|\bwget\b", lower):
        findings.append(Finding("WARN", "Dynamic download command found; static scan may miss URLs generated by scripts.", source))

    if re.search(r"\|\s*(bash|sh|powershell|pwsh)\b", lower):
        findings.append(Finding("WARN", "Pipe-to-shell installer found; it may download additional resources during build.", source))


def env_findings() -> list[Finding]:
    findings = []
    proxies = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy") if os.environ.get(k)}
    if proxies:
        keys = ", ".join(sorted(proxies))
        findings.append(Finding("INFO", f"Proxy environment variables are set: {keys}"))
    else:
        findings.append(Finding("INFO", "No HTTP(S) proxy environment variables detected in this shell."))

    docker_host = os.environ.get("DOCKER_HOST")
    if docker_host:
        findings.append(Finding("INFO", f"DOCKER_HOST is set: {docker_host}. Builder networking may differ from this shell."))
    return findings


def docker_findings(timeout: float) -> list[Finding]:
    findings = []
    docker = shutil.which("docker")
    if not docker:
        findings.append(Finding("WARN", "docker CLI was not found on PATH; skipping Docker daemon checks."))
        return findings
    try:
        result = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        findings.append(Finding("WARN", f"Could not query Docker daemon: {exc}"))
        return findings
    if result.returncode == 0:
        findings.append(Finding("OK", f"Docker daemon is reachable; server version {result.stdout.strip()}."))
    else:
        msg = (result.stderr or result.stdout).strip().splitlines()
        findings.append(Finding("WARN", f"Docker daemon check failed: {msg[0] if msg else 'unknown error'}"))
    return findings


def docker_manifest_probes(images: dict[str, str], timeout: float, limit: int = 0) -> list[DockerManifestResult]:
    docker = shutil.which("docker")
    if not docker:
        return []
    selected = sorted(images.items())
    if limit > 0:
        selected = selected[:limit]
    results: list[DockerManifestResult] = []
    for image, source in selected:
        start = time.time()
        try:
            result = subprocess.run(
                [docker, "manifest", "inspect", image],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            ok = result.returncode == 0
            output = (result.stderr or result.stdout or "").strip().splitlines()
            error = "" if ok else (output[-1] if output else f"exit code {result.returncode}")
        except Exception as exc:
            ok = False
            error = str(exc)
        results.append(
            DockerManifestResult(
                image=image,
                source=source,
                ok=ok,
                error=error,
                elapsed_ms=int((time.time() - start) * 1000),
            )
        )
    return results


def docker_pull_probes(images: dict[str, str], timeout: float, limit: int = 0) -> list[DockerPullResult]:
    docker = shutil.which("docker")
    if not docker:
        return []
    docker_hub_images = [
        (image, source)
        for image, source in sorted(images.items())
        if "registry-1.docker.io" in registry_hosts_for_image(image)
    ]
    if limit > 0:
        docker_hub_images = docker_hub_images[:limit]
    results: list[DockerPullResult] = []
    for image, source in docker_hub_images:
        start = time.time()
        local_only_uncertain = "/" not in image and "docker-compose" in source.lower()
        try:
            inspect_result = subprocess.run(
                [docker, "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=min(timeout, 10.0),
                check=False,
            )
            if inspect_result.returncode == 0:
                results.append(
                    DockerPullResult(
                        image=image,
                        source=source,
                        ok=True,
                        elapsed_ms=int((time.time() - start) * 1000),
                    )
                )
                continue
            result = subprocess.run(
                [docker, "pull", image],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            ok = result.returncode == 0
            output = (result.stderr or result.stdout or "").strip().splitlines()
            error = "" if ok else (output[-1] if output else f"exit code {result.returncode}")
        except Exception as exc:
            ok = False
            error = str(exc)
        results.append(
            DockerPullResult(
                image=image,
                source=source,
                ok=ok,
                error=error,
                local_only_uncertain=local_only_uncertain and not ok,
                elapsed_ms=int((time.time() - start) * 1000),
            )
        )
    return results


def http_head(url: str, timeout: float) -> tuple[bool, int | None, str]:
    try:
        request = Request(url, method="HEAD", headers={"User-Agent": "container-build-guard/1.0"})
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            return True, response.status, ""
    except HTTPError as exc:
        return exc.code < 500, exc.code, ""
    except URLError as exc:
        return False, None, f"HTTPS failed: {exc.reason}"
    except Exception as exc:
        return False, None, f"HTTPS failed: {exc}"


def find_python_artifact_url(index_url: str, package: str, timeout: float) -> tuple[str, int | None, str]:
    simple_url = urljoin(index_url.rstrip("/") + "/", normalize_package_name(package) + "/")
    try:
        request = Request(simple_url, method="GET", headers={"User-Agent": "container-build-guard/1.0"})
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            html_text = response.read(400_000).decode("utf-8", errors="ignore")
    except HTTPError as exc:
        return "", exc.code, f"simple page HTTP {exc.code}"
    except URLError as exc:
        return "", None, f"simple page HTTPS failed: {exc.reason}"
    except Exception as exc:
        return "", None, f"simple page HTTPS failed: {exc}"

    links = re.findall(r"""href=["']([^"']+)["']""", html_text, flags=re.IGNORECASE)
    for raw_link in links:
        link = html.unescape(raw_link).split("#", 1)[0]
        if re.search(r"\.(whl|tar\.gz|zip)$", urlparse(link).path, flags=re.IGNORECASE):
            return urljoin(simple_url, link), None, ""
    return "", None, "no wheel/sdist link found on simple page"


def artifact_probes(targets: list[ArtifactTarget], timeout: float) -> list[ArtifactProbeResult]:
    results: list[ArtifactProbeResult] = []
    for target in targets:
        start = time.time()
        artifact_url = ""
        ok = False
        status_code = None
        error = ""
        if target.ecosystem == "python":
            artifact_url, status_code, error = find_python_artifact_url(target.base_url, target.package, timeout)
            if artifact_url:
                ok, status_code, error = http_head(artifact_url, timeout)
                if status_code and status_code >= 400:
                    ok = False
                    error = f"artifact HTTP {status_code}"
        results.append(
            ArtifactProbeResult(
                ecosystem=target.ecosystem,
                base_url=target.base_url,
                package=target.package,
                source=target.source,
                artifact_url=artifact_url,
                ok=ok,
                status=status_code,
                error=error,
                elapsed_ms=int((time.time() - start) * 1000),
            )
        )
    return results


def probe(endpoint: Endpoint, timeout: float) -> ProbeResult:
    start = time.time()
    result = ProbeResult(endpoint=endpoint)
    try:
        infos = socket.getaddrinfo(endpoint.host, endpoint.port, type=socket.SOCK_STREAM)
        result.dns_ok = bool(infos)
    except socket.gaierror as exc:
        result.error = f"DNS failed: {exc}"
        result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout):
            result.tcp_ok = True
    except OSError as exc:
        result.error = f"TCP failed: {exc}"
        result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    if endpoint.scheme != "https":
        result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    try:
        request = Request(endpoint.url(), method="HEAD", headers={"User-Agent": "container-build-guard/1.0"})
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            result.https_ok = True
            result.status = response.status
    except HTTPError as exc:
        result.https_ok = True
        result.status = exc.code
    except URLError as exc:
        result.https_ok = False
        result.error = f"HTTPS failed: {exc.reason}"
    except Exception as exc:
        result.https_ok = False
        result.error = f"HTTPS failed: {exc}"

    result.elapsed_ms = int((time.time() - start) * 1000)
    return result


def build_report(
    root: Path,
    endpoints: dict[str, Endpoint],
    findings: list[Finding],
    probes: list[ProbeResult],
    manifest_probes: list[DockerManifestResult],
    pull_probes: list[DockerPullResult],
    package_artifact_probes: list[ArtifactProbeResult],
) -> dict:
    blockers = []
    warnings = [f for f in findings if f.severity == "WARN"]
    infos = [f for f in findings if f.severity in {"INFO", "OK"}]
    static_blockers = [f for f in findings if f.severity == "BLOCKER"]
    blockers.extend(static_blockers)

    docker_hub_pull_ok = bool(pull_probes) and any(item.ok for item in pull_probes)
    for item in probes:
        if not item.ok:
            if docker_hub_pull_ok and item.endpoint.host in {"registry-1.docker.io", "auth.docker.io"}:
                warnings.append(
                    Finding(
                        "WARN",
                        f"{item.endpoint.host}:{item.endpoint.port} is not reachable from the host shell, but Docker pull probes succeeded; the daemon may be using registry mirrors or a different network path.",
                        item.endpoint.source,
                    )
                )
                continue
            blockers.append(
                Finding(
                    "BLOCKER",
                    f"{item.endpoint.host}:{item.endpoint.port} is not reachable for {item.endpoint.reason}. {item.error}".strip(),
                    item.endpoint.source,
                )
            )
    for item in manifest_probes:
        if not item.ok:
            if docker_hub_pull_ok and "registry-1.docker.io" in registry_hosts_for_image(item.image):
                warnings.append(
                    Finding(
                        "WARN",
                        f"Docker manifest inspect failed for {item.image}, but Docker pull probes succeeded for Docker Hub images; verify the daemon mirror/cache path before treating this as fatal.",
                        item.source,
                    )
                )
                continue
            blockers.append(
                Finding(
                    "BLOCKER",
                    f"Docker daemon cannot inspect manifest for {item.image}: {item.error}",
                    item.source,
                )
            )
    for item in pull_probes:
        if not item.ok:
            if item.local_only_uncertain:
                warnings.append(
                    Finding(
                        "WARN",
                        f"Docker daemon cannot pull {item.image}, but the unqualified compose image name may refer to a locally built tag: {item.error}",
                        item.source,
                    )
                )
                continue
            blockers.append(
                Finding(
                    "BLOCKER",
                    f"Docker daemon cannot pull {item.image}: {item.error}",
                    item.source,
                )
            )
    for item in package_artifact_probes:
        if not item.ok:
            blockers.append(
                Finding(
                    "BLOCKER",
                    f"{item.ecosystem} index artifact probe failed for {item.package} from {item.base_url}: {item.error}",
                    item.source,
                )
            )

    return {
        "root": str(root),
        "summary": {
            "endpoints_checked": len(probes),
            "manifests_checked": len(manifest_probes),
            "pulls_checked": len(pull_probes),
            "artifacts_checked": len(package_artifact_probes),
            "blockers": len(blockers),
            "warnings": len(warnings),
            "status": "BLOCKED" if blockers else ("WARN" if warnings else "OK"),
        },
        "endpoints": [
            {
                "host": e.host,
                "port": e.port,
                "scheme": e.scheme,
                "reason": e.reason,
                "source": e.source,
                "kind": e.kind,
            }
            for e in endpoints.values()
        ],
        "probes": [
            {
                "host": p.endpoint.host,
                "port": p.endpoint.port,
                "reason": p.endpoint.reason,
                "source": p.endpoint.source,
                "ok": p.ok,
                "dns_ok": p.dns_ok,
                "tcp_ok": p.tcp_ok,
                "https_ok": p.https_ok,
                "status": p.status,
                "error": p.error,
                "elapsed_ms": p.elapsed_ms,
            }
            for p in probes
        ],
        "manifest_probes": [
            {
                "image": p.image,
                "source": p.source,
                "ok": p.ok,
                "error": p.error,
                "elapsed_ms": p.elapsed_ms,
            }
            for p in manifest_probes
        ],
        "pull_probes": [
            {
                "image": p.image,
                "source": p.source,
                "ok": p.ok,
                "error": p.error,
                "elapsed_ms": p.elapsed_ms,
            }
            for p in pull_probes
        ],
        "artifact_probes": [
            {
                "ecosystem": p.ecosystem,
                "base_url": p.base_url,
                "package": p.package,
                "source": p.source,
                "artifact_url": p.artifact_url,
                "ok": p.ok,
                "status": p.status,
                "error": p.error,
                "elapsed_ms": p.elapsed_ms,
            }
            for p in package_artifact_probes
        ],
        "findings": [
            {"severity": f.severity, "message": f.message, "source": f.source}
            for f in blockers + warnings + infos
        ],
    }


def ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def ensure_plain_progress(command: str) -> str:
    stripped = command.strip()
    if "--progress=" in stripped or "--progress " in stripped:
        return stripped
    if re.search(r"\bdocker\s+build\b", stripped):
        return re.sub(r"\bdocker\s+build\b", "docker build --progress=plain", stripped, count=1)
    compose_match = re.search(r"\bdocker\s+compose\b", stripped)
    if compose_match:
        insert_at = compose_match.end()
        return stripped[:insert_at] + " --progress plain" + stripped[insert_at:]
    return stripped


def wrapper_snippets(command: str, tail_lines: int, log_stem: str) -> dict[str, str]:
    command = ensure_plain_progress(command)
    safe_tail = max(20, tail_lines)
    log_name = f"{log_stem}.log"
    powershell = "\n".join(
        [
            f"$log = Join-Path $env:TEMP {ps_single_quote(log_name)}",
            "$env:PYTHONUTF8 = '1'",
            "$env:PYTHONIOENCODING = 'utf-8'",
            f"{command} *> $log",
            "$code = $LASTEXITCODE",
            f"Get-Content $log -Encoding UTF8 -Tail {safe_tail}",
            "exit $code",
        ]
    )
    bash = "\n".join(
        [
            f"log=\"${{TMPDIR:-/tmp}}/{log_name}\"",
            f"{command} >\"$log\" 2>&1",
            "code=$?",
            f"tail -n {safe_tail} \"$log\"",
            "exit \"$code\"",
        ]
    )
    return {"powershell": powershell, "bash": bash, "command": command}


DEFAULT_DOCKERHUB_MIRRORS = [
    "docker.m.daocloud.io",
    "docker.xuanyuan.me",
    "docker.1ms.run",
]


def is_dockerhub_image(image: str) -> bool:
    hosts = registry_hosts_for_image(image)
    return "registry-1.docker.io" in hosts


def dockerhub_mirror_ref(image: str, mirror: str) -> str:
    name, sep, digest = image.partition("@")
    if "/" in name and not name.startswith("library/"):
        path = name
    else:
        path = f"library/{name}"
    return f"{mirror.rstrip('/')}/{path}{sep}{digest}"


def is_probably_local_image(image: str) -> bool:
    if image.startswith("${") or "{" in image or "}" in image:
        return False
    if "/" in image:
        first = image.split("/", 1)[0]
        return not ("." in first or ":" in first or first == "localhost")
    return ":" not in image and "@" not in image


def image_prep_snippets(images: dict[str, str], mirrors: list[str]) -> dict[str, str]:
    selected = sorted(
        image
        for image in images
        if image and image != "scratch" and not is_probably_local_image(image)
    )
    ps_lines = [
        "$ErrorActionPreference = 'Continue'",
        "$mirrors = @(" + ", ".join(ps_single_quote(mirror) for mirror in mirrors) + ")",
        "$images = @(" + ", ".join(ps_single_quote(image) for image in selected) + ")",
        "$pullTimeoutSeconds = 90",
        "foreach ($image in $images) {",
        "  docker image inspect $image *> $null",
        "  if ($LASTEXITCODE -eq 0) { Write-Host \"ready $image\"; continue }",
        "  $pulled = $false",
        "  $candidates = @()",
        "  $name = ($image -split '@', 2)[0]",
        "  $digest = if ($image.Contains('@')) { '@' + ($image -split '@', 2)[1] } else { '' }",
        "  if ($name -notmatch '^[^/]+\\.[^/]+/') {",
        "    foreach ($mirror in $mirrors) {",
        "      if ($name -match '/') { $candidates += \"$mirror/$name$digest\" } else { $candidates += \"$mirror/library/$name$digest\" }",
        "    }",
        "  }",
        "  $candidates += $image",
        "  foreach ($candidate in $candidates) {",
        "    Write-Host \"pull $candidate\"",
        "    $job = Start-Job -ScriptBlock { param($ref) docker pull $ref; if ($LASTEXITCODE -ne 0) { throw \"docker pull exited $LASTEXITCODE\" } } -ArgumentList $candidate",
        "    if (-not (Wait-Job $job -Timeout $pullTimeoutSeconds)) {",
        "      Stop-Job $job | Out-Null",
        "      Receive-Job $job | Out-String | Write-Host",
        "      Remove-Job $job -Force",
        "      Write-Warning \"timed out pulling $candidate\"",
        "      continue",
        "    }",
        "    Receive-Job $job",
        "    $pullCode = if ($job.State -eq 'Completed') { 0 } else { 1 }",
        "    Remove-Job $job -Force",
        "    if ($pullCode -eq 0) {",
        "      if ($candidate -ne $image) { docker tag $candidate $image }",
        "      $pulled = $true",
        "      break",
        "    }",
        "  }",
        "  if (-not $pulled) { throw \"failed to pull $image\" }",
        "}",
    ]
    sh_lines = [
        "set -e",
        "mirrors=(" + " ".join(sh_single_quote(mirror) for mirror in mirrors) + ")",
        "images=(" + " ".join(sh_single_quote(image) for image in selected) + ")",
        "pull_timeout_seconds=90",
        "for image in \"${images[@]}\"; do",
        "  if docker image inspect \"$image\" >/dev/null 2>&1; then echo \"ready $image\"; continue; fi",
        "  candidates=()",
        "  name=\"${image%@*}\"",
        "  if [ \"$name\" = \"$image\" ]; then digest=''; else digest=\"@${image#*@}\"; fi",
        "  if ! printf '%s' \"$name\" | grep -Eq '^[^/]+\\.[^/]+/'; then",
        "    for mirror in \"${mirrors[@]}\"; do",
        "      if printf '%s' \"$name\" | grep -q '/'; then candidates+=(\"$mirror/$name$digest\"); else candidates+=(\"$mirror/library/$name$digest\"); fi",
        "    done",
        "  fi",
        "  candidates+=(\"$image\")",
        "  pulled=0",
        "  for candidate in \"${candidates[@]}\"; do",
        "    echo \"pull $candidate\"",
        "    if timeout \"$pull_timeout_seconds\" docker pull \"$candidate\"; then",
        "      if [ \"$candidate\" != \"$image\" ]; then docker tag \"$candidate\" \"$image\"; fi",
        "      pulled=1",
        "      break",
        "    fi",
        "  done",
        "  if [ \"$pulled\" -ne 1 ]; then echo \"failed to pull $image\" >&2; exit 1; fi",
        "done",
    ]
    return {"powershell": "\n".join(ps_lines), "bash": "\n".join(sh_lines)}


def print_text_report(report: dict, build_command: str | None = None, tail_lines: int = 160, log_stem: str = "container-build") -> None:
    summary = report["summary"]
    print("Container build guard")
    print(f"Root: {report['root']}")
    print(
        f"Status: {summary['status']} "
        f"({summary['blockers']} blockers, {summary['warnings']} warnings, "
        f"{summary['endpoints_checked']} endpoints checked, {summary.get('manifests_checked', 0)} manifests checked, "
        f"{summary.get('pulls_checked', 0)} pulls checked, {summary.get('artifacts_checked', 0)} artifacts checked)"
    )
    print()

    findings = report["findings"]
    for severity in ("BLOCKER", "WARN", "OK", "INFO"):
        group = [f for f in findings if f["severity"] == severity]
        if not group:
            continue
        print(f"{severity}:")
        for item in group:
            source = f" [{item['source']}]" if item.get("source") else ""
            print(f"  - {item['message']}{source}")
    print()

    if report["endpoints"]:
        print("Discovered endpoints:")
        for e in report["endpoints"]:
            source = f" [{e['source']}]" if e.get("source") else ""
            print(f"  - {e['host']}:{e['port']} - {e['reason']}{source}")
        print()

    if report["probes"]:
        print("Endpoint probes:")
        for p in report["probes"]:
            mark = "OK" if p["ok"] else "FAIL"
            detail = f"HTTP {p['status']}" if p.get("status") else p.get("error", "")
            print(f"  - {mark} {p['host']}:{p['port']} - {p['reason']} {detail}".rstrip())
        print()

    if report.get("manifest_probes"):
        print("Docker daemon manifest probes:")
        for p in report["manifest_probes"]:
            mark = "OK" if p["ok"] else "FAIL"
            detail = "" if p["ok"] else p.get("error", "")
            source = f" [{p['source']}]" if p.get("source") else ""
            print(f"  - {mark} {p['image']} {detail}{source}".rstrip())
        print()

    if report.get("pull_probes"):
        print("Docker daemon pull probes:")
        for p in report["pull_probes"]:
            mark = "OK" if p["ok"] else "FAIL"
            detail = "" if p["ok"] else p.get("error", "")
            if p.get("local_only_uncertain"):
                detail = f"{detail} (may be a local compose image tag)".strip()
            source = f" [{p['source']}]" if p.get("source") else ""
            print(f"  - {mark} {p['image']} {detail}{source}".rstrip())
        print()

    if report.get("artifact_probes"):
        print("Package artifact probes:")
        for p in report["artifact_probes"]:
            mark = "OK" if p["ok"] else "FAIL"
            detail = f"HTTP {p['status']}" if p.get("status") else p.get("error", "")
            source = f" [{p['source']}]" if p.get("source") else ""
            print(f"  - {mark} {p['ecosystem']} {p['package']} via {p['base_url']} {detail}{source}".rstrip())
        print()

    if report.get("images"):
        print("Discovered container images:")
        for image in report["images"]:
            source = f" [{image['source']}]" if image.get("source") else ""
            print(f"  - {image['image']}{source}")
        print()

    if summary["status"] == "BLOCKED":
        print("Recommended next steps:")
        print("  - Configure proxy variables and Docker daemon proxy if the network requires a proxy.")
        print("  - Configure registry/package mirrors such as Docker Hub mirror, .npmrc, pip.conf/UV_INDEX_URL, apt/apk mirrors, GOPROXY, or PLAYWRIGHT_DOWNLOAD_HOST.")
        print("  - Fix static blockers such as CRLF shebangs before rebuilding; they usually fail only after image build time has already been spent.")
        print("  - For offline targets, build on a connected machine and transfer images with docker save/load.")
    elif summary["warnings"]:
        print("Recommended next steps:")
        print("  - Review warnings before building; dynamic installers may still fail even when the visible endpoints are reachable.")
    else:
        print("No obvious network blockers found. This guardrail check is not a guarantee that the build will pass.")

    if build_command:
        snippets = wrapper_snippets(build_command, tail_lines, log_stem)
        print()
        print("Foreground build wrapper:")
        print("  Use this after resolving blockers. It waits for the build to exit, writes full logs to a temp file, returns only the tail, and preserves the exit code.")
        print()
        print("PowerShell:")
        print("```powershell")
        print(snippets["powershell"])
        print("```")
        print()
        print("Bash:")
        print("```bash")
        print(snippets["bash"])
        print("```")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check likely network prerequisites and generate safe long-build wrappers.")
    parser.add_argument("path", nargs="?", default=".", help="Repository root or build context to scan.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-endpoint timeout in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum endpoints to probe; 0 means no limit.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--no-network", action="store_true", help="Only scan files; skip DNS/TCP/HTTPS probes.")
    parser.add_argument("--docker-probe", action="store_true", help="Ask the Docker daemon to inspect discovered image manifests without pulling layers.")
    parser.add_argument("--docker-probe-limit", type=int, default=20, help="Maximum image manifests to inspect when --docker-probe is used; 0 means no limit.")
    parser.add_argument("--docker-pull-probe", action="store_true", help="Ask the Docker daemon to pull a small sample of discovered Docker Hub images; useful when registry mirrors make host probes misleading.")
    parser.add_argument("--docker-pull-probe-limit", type=int, default=3, help="Maximum Docker Hub images to pull when --docker-pull-probe is used; 0 means no limit.")
    parser.add_argument("--artifact-probe", action="store_true", help="Probe package index artifact URLs for a generic sample of discovered dependencies.")
    parser.add_argument("--artifact-probe-limit", type=int, default=6, help="Maximum package artifact probes when --artifact-probe is used.")
    parser.add_argument("--build-command", help="Optional build command to wrap with foreground logging guidance.")
    parser.add_argument("--tail-lines", type=int, default=160, help="Log tail lines for generated build wrappers.")
    parser.add_argument("--image-prep", action="store_true", help="Emit pre-pull/tag scripts for discovered container images.")
    parser.add_argument("--dockerhub-mirror", action="append", default=[], help="Docker Hub mirror host for --image-prep; may be repeated.")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Path does not exist: {root}", file=sys.stderr)
        return 2
    if root.is_file():
        root = root.parent

    endpoints: dict[str, Endpoint] = {}
    findings: list[Finding] = []
    images: dict[str, str] = {}
    warned_indexes: set[tuple[str, str]] = set()
    python_indexes: dict[str, set[str]] = {}
    python_packages: dict[str, set[str]] = {}

    container_files = discover_container_files(root)
    package_files = discover_package_manifests(root)

    if not container_files:
        findings.append(Finding("WARN", "No Dockerfile, Containerfile, or compose file found. Scan will rely on package manifests only."))

    for path in container_files + package_files:
        analyze_text(
            path,
            root,
            read_text(path),
            endpoints,
            findings,
            images,
            warned_indexes,
            python_indexes,
            python_packages,
        )
    scan_crlf_shebangs(root, container_files, findings)
    scan_missing_copy_sources(root, container_files, findings)

    findings.extend(env_findings())
    findings.extend(docker_findings(args.timeout))

    probes = []
    if not args.no_network:
        selected = sorted(endpoints.values(), key=lambda e: (e.host, e.port))
        if args.limit > 0:
            selected = selected[: args.limit]
            if len(endpoints) > args.limit:
                findings.append(Finding("WARN", f"Probe limit applied: checked {args.limit} of {len(endpoints)} discovered endpoints."))
        for endpoint in selected:
            probes.append(probe(endpoint, args.timeout))

    manifest_probes = []
    if args.docker_probe:
        manifest_probes = docker_manifest_probes(images, args.timeout, args.docker_probe_limit)
        if args.docker_probe_limit > 0 and len(images) > args.docker_probe_limit:
            findings.append(Finding("WARN", f"Docker manifest probe limit applied: checked {args.docker_probe_limit} of {len(images)} discovered images."))

    pull_probes = []
    if args.docker_pull_probe:
        pull_probes = docker_pull_probes(images, max(args.timeout, 30.0), args.docker_pull_probe_limit)
        docker_hub_count = sum(1 for image in images if "registry-1.docker.io" in registry_hosts_for_image(image))
        if args.docker_pull_probe_limit > 0 and docker_hub_count > args.docker_pull_probe_limit:
            findings.append(Finding("WARN", f"Docker pull probe limit applied: checked {args.docker_pull_probe_limit} of {docker_hub_count} discovered Docker Hub images."))

    package_artifacts = []
    if args.artifact_probe and not args.no_network:
        targets = choose_artifact_targets(python_indexes, python_packages, args.artifact_probe_limit)
        package_artifacts = artifact_probes(targets, args.timeout)
        if not targets and python_indexes:
            findings.append(Finding("WARN", "Python indexes were discovered, but no package names were available for artifact probes."))

    report = build_report(root, endpoints, findings, probes, manifest_probes, pull_probes, package_artifacts)
    report["images"] = [{"image": image, "source": source} for image, source in sorted(images.items())]
    log_stem = "container-build-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.build_command:
        report["build_wrapper"] = wrapper_snippets(args.build_command, args.tail_lines, log_stem)
    if args.image_prep:
        mirrors = args.dockerhub_mirror or DEFAULT_DOCKERHUB_MIRRORS
        report["image_prep"] = image_prep_snippets(images, mirrors)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text_report(report, args.build_command, args.tail_lines, log_stem)
        if args.image_prep:
            snippets = report["image_prep"]
            print()
            print("Image pre-pull/tag script:")
            print("PowerShell:")
            print("```powershell")
            print(snippets["powershell"])
            print("```")
            print()
            print("Bash:")
            print("```bash")
            print(snippets["bash"])
            print("```")

    return 1 if report["summary"]["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
