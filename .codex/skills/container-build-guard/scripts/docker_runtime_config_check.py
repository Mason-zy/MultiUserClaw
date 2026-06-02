#!/usr/bin/env python3
"""Check Docker runtime config before build preflight.

This script inspects the three runtime-level knobs that usually decide whether
container pulls and build-time downloads will work:

1. Docker registry mirrors
2. Docker daemon proxy settings
3. Docker CLI default proxy settings for new containers/builds

It is intentionally read-only. If any item is missing or incomplete, the
report explains what is absent and leaves the actual change to the user after
explicit confirmation.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ARTICLE_URL = "https://cloud.tencent.com/developer/article/2647943"
ARTICLE_MIRRORS = [
    "https://docker.xuanyuan.me",
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
]
RETIRED_OR_UNSTABLE_MIRRORS = [
    "https://dockerhub.icu",
    "https://dockerproxy.cn",
    "https://dockerpull.com",
    "https://lynn520.xyz",
    "https://docker.mrxn.net",
    "https://hub-mirror.c.163.com",
    "https://docker.mirrors.ustc.edu.cn",
    "https://registry.docker-cn.com",
]
DEFAULT_MIRRORS = [
    "https://docker.xuanyuan.me/",
    "https://docker.1ms.run/",
    "https://docker.m.daocloud.io/",
]
DEFAULT_DOCKER_PULL_PROBE_IMAGE = "hello-world:latest"
DEFAULT_DOCKER_MANIFEST_PROBE_IMAGE = "library/hello-world:latest"
DEFAULT_CONTAINER_PROBE_IMAGE = "busybox:1.36"
DEFAULT_CONTAINER_PROBE_URL = "https://registry.npmmirror.com/"


@dataclass
class Check:
    name: str
    status: str
    source: str
    summary: str
    details: dict[str, Any]


@dataclass
class Probe:
    name: str
    status: str
    summary: str
    details: dict[str, Any]


def load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"error: {exc}"


def load_first_json(paths: list[Path]) -> tuple[dict[str, Any] | None, str, str]:
    missing: list[str] = []
    for path in paths:
        data, state = load_json(path)
        if state == "ok":
            return data, state, str(path)
        if state == "missing":
            missing.append(str(path))
            continue
        return data, state, str(path)
    return None, "missing", ", ".join(missing)


def run_docker_info() -> tuple[dict[str, Any] | None, str]:
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None, "docker-not-found"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return None, err or f"exit-{proc.returncode}"

    raw = (proc.stdout or "").strip()
    if not raw:
        return None, "empty-output"

    try:
        return json.loads(raw), "ok"
    except json.JSONDecodeError as exc:
        return None, f"json-error: {exc}"


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_url(url: str) -> str:
    return str(url).strip().rstrip("/").lower()


def mirror_probe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}/v2/"


def probe_http_url(url: str, timeout: float) -> dict[str, Any]:
    target = mirror_probe_url(url)
    started = time.monotonic()
    try:
        req = Request(target, method="HEAD", headers={"User-Agent": "container-build-guard/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
        ok = status is not None and status < 500
        return {"url": target, "ok": ok, "status": status, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    except HTTPError as exc:
        ok = exc.code in {200, 301, 302, 307, 308, 401, 403, 404}
        return {"url": target, "ok": ok, "status": exc.code, "elapsed_ms": int((time.monotonic() - started) * 1000)}
    except (URLError, TimeoutError, socket.timeout, OSError) as exc:
        return {
            "url": target,
            "ok": False,
            "error": str(exc),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


def run_command(command: list[str], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        output = "\n".join(part.strip() for part in [proc.stdout, proc.stderr] if part and part.strip())
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output_tail": output[-1200:],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "elapsed_ms": int((time.monotonic() - started) * 1000)}
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part.strip() for part in [exc.stdout, exc.stderr] if part)
        return {
            "ok": False,
            "error": f"timeout after {timeout}s",
            "output_tail": output[-1200:],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


def check_registry_mirrors(
    info: dict[str, Any] | None,
    daemon_json: dict[str, Any] | None,
    *,
    probe: bool,
    timeout: float,
) -> Check:
    live_mirrors: list[str] = []
    source = "docker info"
    if info:
        registry = info.get("RegistryConfig") or {}
        live_mirrors = normalize_list(registry.get("Mirrors"))
        if not live_mirrors:
            index_cfg = registry.get("IndexConfigs") or {}
            docker_io = index_cfg.get("docker.io") or {}
            live_mirrors = normalize_list(docker_io.get("Mirrors"))

    file_mirrors = []
    if daemon_json:
        file_mirrors = normalize_list(daemon_json.get("registry-mirrors"))
        if not live_mirrors and file_mirrors:
            source = "~/.docker/daemon.json"

    mirrors = live_mirrors or file_mirrors
    normalized = {normalize_url(item) for item in mirrors}
    required = {normalize_url(item) for item in ARTICLE_MIRRORS}
    retired = {normalize_url(item) for item in RETIRED_OR_UNSTABLE_MIRRORS}
    missing_required = [item for item in ARTICLE_MIRRORS if normalize_url(item) not in normalized]
    retired_present = [item for item in mirrors if normalize_url(item) in retired]
    extra = [item for item in mirrors if normalize_url(item) not in required and normalize_url(item) not in retired]
    probe_results = [probe_http_url(item, timeout) for item in ARTICLE_MIRRORS] if probe else []
    failed_article_probe = [item for item in probe_results if not item.get("ok")]

    details: dict[str, Any] = {
        "mirrors": mirrors,
        "requiredFromArticle": ARTICLE_MIRRORS,
        "article": ARTICLE_URL,
    }
    if missing_required:
        details["missingRequired"] = missing_required
    if retired_present:
        details["retiredOrUnstablePresent"] = retired_present
    if extra:
        details["extraMirrors"] = extra
    if probe_results:
        details["articleMirrorProbes"] = probe_results

    if not mirrors:
        return Check(
            name="registry_mirrors",
            status="missing",
            source=source,
            summary="No registry mirrors are configured",
            details={"recommended": DEFAULT_MIRRORS, "article": ARTICLE_URL},
        )

    if missing_required or retired_present:
        return Check(
            name="registry_mirrors",
            status="mismatch",
            source=source,
            summary="Registry mirrors do not match the Tencent Cloud article's recommended fallback set",
            details=details,
        )

    if failed_article_probe:
        return Check(
            name="registry_mirrors",
            status="probe-failed",
            source=source,
            summary="Registry mirrors are configured from the article, but one or more mirror endpoints failed a connectivity probe",
            details=details,
        )

    if not probe:
        return Check(
            name="registry_mirrors",
            status="configured-unverified",
            source=source,
            summary="Registry mirrors match the Tencent Cloud article, but mirror endpoint probes were skipped",
            details=details,
        )

    if live_mirrors:
        return Check(
            name="registry_mirrors",
            status="ok",
            source=source,
            summary="Registry mirrors match the Tencent Cloud article and passed mirror endpoint probes",
            details=details,
        )

    return Check(
        name="registry_mirrors",
        status="file-only",
        source="~/.docker/daemon.json",
        summary="Article mirrors exist on disk but the live daemon state was not verified",
        details=details,
    )


def check_docker_pull_path(image: str, *, probe: bool, timeout: float) -> Probe:
    if not probe:
        return Probe(
            name="docker_pull_path",
            status="skipped",
            summary="Docker pull probe was skipped",
            details={"image": image},
        )
    result = run_command(["docker", "pull", image], timeout)
    return Probe(
        name="docker_pull_path",
        status="ok" if result.get("ok") else "failed",
        summary=(
            "Docker daemon successfully pulled the probe image through its configured network path"
            if result.get("ok")
            else "Docker daemon could not pull the probe image; mirror/proxy config is not sufficient"
        ),
        details={"image": image, **result},
    )


def check_docker_manifest_path(image: str, *, probe: bool, timeout: float) -> Probe:
    if not probe:
        return Probe(
            name="docker_manifest_path",
            status="skipped",
            summary="Docker manifest probe was skipped",
            details={"image": image},
        )
    result = run_command(["docker", "manifest", "inspect", image], timeout)
    return Probe(
        name="docker_manifest_path",
        status="ok" if result.get("ok") else "failed",
        summary=(
            "Docker client successfully inspected the remote manifest for the probe image"
            if result.get("ok")
            else "Docker client could not inspect the remote manifest; registry/proxy config is not sufficient"
        ),
        details={"image": image, **result},
    )


def check_daemon_proxy(
    info: dict[str, Any] | None,
    daemon_json: dict[str, Any] | None,
    docker_pull_probe: Probe,
    docker_manifest_probe: Probe,
) -> Check:
    http_proxy = ""
    https_proxy = ""
    no_proxy = ""
    source = "docker info"

    if info:
        http_proxy = str(info.get("HttpProxy") or "").strip()
        https_proxy = str(info.get("HttpsProxy") or "").strip()
        no_proxy = str(info.get("NoProxy") or "").strip()

    if not (http_proxy or https_proxy or no_proxy) and daemon_json:
        proxies = daemon_json.get("proxies") or {}
        http_proxy = str(proxies.get("http-proxy") or "").strip()
        https_proxy = str(proxies.get("https-proxy") or "").strip()
        no_proxy = str(proxies.get("no-proxy") or "").strip()
        if http_proxy or https_proxy or no_proxy:
            source = "~/.docker/daemon.json"

    configured = bool(http_proxy or https_proxy or no_proxy)
    complete = bool(http_proxy and https_proxy and no_proxy)

    docker_path_verified = docker_pull_probe.status == "ok" and docker_manifest_probe.status == "ok"

    if complete and docker_path_verified:
        return Check(
            name="daemon_proxy",
            status="ok",
            source=source,
            summary="Docker daemon proxy is configured and Docker registry paths were verified",
            details={"httpProxy": http_proxy, "httpsProxy": https_proxy, "noProxy": no_proxy},
        )

    if complete:
        return Check(
            name="daemon_proxy",
            status="configured-unverified",
            source=source,
            summary="Docker daemon proxy is configured, but the daemon pull path did not verify successfully",
            details={
                "httpProxy": http_proxy,
                "httpsProxy": https_proxy,
                "noProxy": no_proxy,
                "dockerPullProbe": docker_pull_probe.status,
                "dockerManifestProbe": docker_manifest_probe.status,
            },
        )

    if configured:
        return Check(
            name="daemon_proxy",
            status="partial",
            source=source,
            summary="Docker daemon proxy is only partially configured",
            details={"httpProxy": http_proxy, "httpsProxy": https_proxy, "noProxy": no_proxy},
        )

    return Check(
        name="daemon_proxy",
        status="missing",
        source=source,
        summary="Docker daemon proxy is not configured",
        details={
            "recommended": {
                "http-proxy": "http://PROXY_HOST:PORT",
                "https-proxy": "http://PROXY_HOST:PORT",
                "no-proxy": "localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal",
            }
        },
    )


def check_cli_proxy(
    config_json: dict[str, Any] | None,
    *,
    probe: bool,
    timeout: float,
    probe_image: str,
    probe_url: str,
) -> Check:
    proxies = {}
    if config_json:
        proxies = (config_json.get("proxies") or {}).get("default") or {}

    http_proxy = str(proxies.get("httpProxy") or "").strip()
    https_proxy = str(proxies.get("httpsProxy") or "").strip()
    no_proxy = str(proxies.get("noProxy") or "").strip()

    configured = bool(http_proxy or https_proxy or no_proxy)
    complete = bool(http_proxy and https_proxy and no_proxy)

    container_probe: dict[str, Any] | None = None
    if complete and probe:
        command = [
            "docker",
            "run",
            "--rm",
            probe_image,
            "sh",
            "-c",
            (
                "test -n \"$HTTP_PROXY$http_proxy\" && "
                "test -n \"$HTTPS_PROXY$https_proxy\" && "
                f"wget -T 10 -q --spider {probe_url}"
            ),
        ]
        container_probe = run_command(command, timeout)

    if complete and not probe:
        return Check(
            name="cli_default_proxy",
            status="configured-unverified",
            source="~/.docker/config.json",
            summary="Docker CLI default proxy is configured, but the new-container network path was not verified",
            details={
                "httpProxy": http_proxy,
                "httpsProxy": https_proxy,
                "noProxy": no_proxy,
                "containerProbe": "skipped",
            },
        )

    if complete and container_probe and container_probe.get("ok"):
        return Check(
            name="cli_default_proxy",
            status="ok",
            source="~/.docker/config.json",
            summary="Docker CLI default proxy is configured and verified for a new container",
            details={
                "httpProxy": http_proxy,
                "httpsProxy": https_proxy,
                "noProxy": no_proxy,
                "containerProbe": container_probe or "skipped",
            },
        )

    if complete:
        return Check(
            name="cli_default_proxy",
            status="probe-failed",
            source="~/.docker/config.json",
            summary="Docker CLI default proxy is configured, but a new container could not use it successfully",
            details={
                "httpProxy": http_proxy,
                "httpsProxy": https_proxy,
                "noProxy": no_proxy,
                "containerProbe": container_probe,
            },
        )

    if configured:
        return Check(
            name="cli_default_proxy",
            status="partial",
            source="~/.docker/config.json",
            summary="Docker CLI default proxy is only partially configured",
            details={"httpProxy": http_proxy, "httpsProxy": https_proxy, "noProxy": no_proxy},
        )

    return Check(
        name="cli_default_proxy",
        status="missing",
        source="~/.docker/config.json",
        summary="Docker CLI default proxy is not configured",
        details={
            "recommended": {
                "httpProxy": "http://PROXY_HOST:PORT",
                "httpsProxy": "http://PROXY_HOST:PORT",
                "noProxy": "localhost,127.0.0.1,::1,host.docker.internal,gateway.docker.internal,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local,.internal",
            }
        },
    )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    home = Path.home()
    docker_dir = home / ".docker"
    daemon_json_paths = [docker_dir / "daemon.json", Path("/etc/docker/daemon.json")]
    config_json_path = docker_dir / "config.json"

    docker_info, info_state = run_docker_info()
    daemon_json, daemon_state, daemon_source = load_first_json(daemon_json_paths)
    config_json, config_state = load_json(config_json_path)

    docker_pull_probe = check_docker_pull_path(
        args.pull_image,
        probe=not args.skip_probes,
        timeout=args.probe_timeout,
    )
    docker_manifest_probe = check_docker_manifest_path(
        args.manifest_image,
        probe=not args.skip_probes,
        timeout=args.probe_timeout,
    )

    checks = [
        check_registry_mirrors(
            docker_info,
            daemon_json,
            probe=not args.skip_probes,
            timeout=args.probe_timeout,
        ),
        check_daemon_proxy(docker_info, daemon_json, docker_pull_probe, docker_manifest_probe),
        check_cli_proxy(
            config_json,
            probe=not args.skip_probes,
            timeout=args.probe_timeout,
            probe_image=args.container_probe_image,
            probe_url=args.container_probe_url,
        ),
    ]

    blocking_statuses = {"missing", "partial", "mismatch", "probe-failed", "configured-unverified"}
    blocking = (
        docker_pull_probe.status == "failed"
        or docker_manifest_probe.status == "failed"
        or any(check.status in blocking_statuses for check in checks)
    )
    overall = "warn" if blocking else "ok"

    return {
        "overall": overall,
        "sources": {
            "docker_info": info_state,
            "daemon_json": {"state": daemon_state, "path": daemon_source},
            "config_json": {"state": config_state, "path": str(config_json_path)},
        },
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "source": check.source,
                "summary": check.summary,
                "details": check.details,
            }
            for check in checks
        ],
        "probes": [
            {
                "name": docker_pull_probe.name,
                "status": docker_pull_probe.status,
                "summary": docker_pull_probe.summary,
                "details": docker_pull_probe.details,
            },
            {
                "name": docker_manifest_probe.name,
                "status": docker_manifest_probe.status,
                "summary": docker_manifest_probe.summary,
                "details": docker_manifest_probe.details,
            }
        ],
        "next_step": (
            "Ask the user before changing or overwriting any Docker runtime config."
            if blocking
            else "Safe to continue to preflight."
        ),
    }


def format_text(report: dict[str, Any]) -> str:
    lines = ["Docker runtime config check"]
    for idx, check in enumerate(report["checks"], start=1):
        lines.append(f"{idx}. {check['name']}: {check['status']} ({check['source']})")
        lines.append(f"   {check['summary']}")
        details = check.get("details") or {}
        if "mirrors" in details:
            lines.append(f"   mirrors: {', '.join(details['mirrors'])}")
            if details.get("missingRequired"):
                lines.append(f"   missing required: {', '.join(details['missingRequired'])}")
            if details.get("retiredOrUnstablePresent"):
                lines.append(f"   remove: {', '.join(details['retiredOrUnstablePresent'])}")
        elif "httpProxy" in details or "httpsProxy" in details or "noProxy" in details:
            lines.append(
                "   proxy: "
                f"http={details.get('httpProxy', '') or '-'} "
                f"https={details.get('httpsProxy', '') or '-'} "
                f"no={details.get('noProxy', '') or '-'}"
            )
        elif "recommended" in details:
            lines.append(f"   recommended: {json.dumps(details['recommended'], ensure_ascii=False)}")
    for probe_item in report.get("probes", []):
        lines.append(f"probe {probe_item['name']}: {probe_item['status']}")
        lines.append(f"   {probe_item['summary']}")
    lines.append(f"overall: {report['overall']}")
    lines.append(f"next: {report['next_step']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--skip-probes", action="store_true", help="only inspect config files and docker info")
    parser.add_argument("--probe-timeout", type=float, default=90.0, help="timeout in seconds for each Docker/network probe")
    parser.add_argument("--pull-image", default=DEFAULT_DOCKER_PULL_PROBE_IMAGE, help="small Docker Hub image used to verify daemon pull path")
    parser.add_argument("--manifest-image", default=DEFAULT_DOCKER_MANIFEST_PROBE_IMAGE, help="Docker Hub image used to verify remote manifest access")
    parser.add_argument("--container-probe-image", default=DEFAULT_CONTAINER_PROBE_IMAGE, help="small image used to verify Docker CLI default proxy inside a new container")
    parser.add_argument("--container-probe-url", default=DEFAULT_CONTAINER_PROBE_URL, help="URL fetched from the container proxy probe")
    args = parser.parse_args()

    report = build_report(args)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_text(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
