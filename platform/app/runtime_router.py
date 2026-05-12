from __future__ import annotations

from app.config import Settings, settings
from app.db.models import User
from app.runtime_backend import RuntimeBackend

_dedicated_backends: dict[str, RuntimeBackend] = {}
_shared_backends: dict[str, RuntimeBackend] = {}


def _load_backend(kind: str, backend_name: str) -> RuntimeBackend:
    normalized = (backend_name or "openclaw").strip().lower()

    if kind == "dedicated":
        if normalized not in _dedicated_backends:
            if normalized == "openclaw":
                from app.runtime_backends.dedicated_openclaw import DedicatedOpenClawBackend

                _dedicated_backends[normalized] = DedicatedOpenClawBackend()
            elif normalized == "hermes":
                from app.runtime_backends.dedicated_hermes import DedicatedHermesBackend

                _dedicated_backends[normalized] = DedicatedHermesBackend()
            else:
                raise ValueError(f"Unsupported dedicated runtime backend: {backend_name}")
        return _dedicated_backends[normalized]

    if normalized not in _shared_backends:
        if normalized == "openclaw":
            from app.runtime_backends.shared_openclaw import SharedOpenClawBackend

            _shared_backends[normalized] = SharedOpenClawBackend()
        elif normalized == "hermes":
            from app.runtime_backends.shared_hermes import SharedHermesBackend

            _shared_backends[normalized] = SharedHermesBackend()
        else:
            raise ValueError(f"Unsupported shared runtime backend: {backend_name}")
    return _shared_backends[normalized]


def get_runtime_backend(user: User, runtime_settings: Settings | None = None) -> RuntimeBackend:
    runtime_settings = runtime_settings or settings
    if user.runtime_mode == "shared":
        return _load_backend("shared", runtime_settings.shared_runtime_backend)
    return _load_backend("dedicated", runtime_settings.dedicated_runtime_backend)


async def close_runtime_backends() -> None:
    backends = [*_dedicated_backends.values(), *_shared_backends.values()]
    seen: set[int] = set()
    for backend in backends:
        backend_id = id(backend)
        if backend_id in seen:
            continue
        seen.add(backend_id)
        close = getattr(backend, "aclose", None)
        if close is not None:
            await close()
    _dedicated_backends.clear()
    _shared_backends.clear()
