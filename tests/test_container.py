"""Tests for container management & maintenance endpoints.

Covers:
- GET  /api/openclaw/container/info
- POST /api/openclaw/container/doctor-fix
- GET  /api/openclaw/filemanager/download   (file proxy)
- GET  /api/openclaw/filemanager/serve      (file proxy)
"""

from conftest import admin_token, api_url, auth_headers, json_request


def _token() -> str:
    return admin_token()


# ---------------------------------------------------------------------------
# Container info
# ---------------------------------------------------------------------------

def test_container_info_structure():
    """Container info should return expected fields."""
    result = json_request(
        api_url("/api/openclaw/container/info"),
        headers=auth_headers(_token()),
    )
    assert "container_name" in result
    assert "status" in result
    assert "docker_id" in result


# ---------------------------------------------------------------------------
# Doctor fix
# ---------------------------------------------------------------------------

def test_doctor_fix_requires_container():
    """Doctor fix should 404 if no container exists."""
    try:
        result = json_request(
            api_url("/api/openclaw/container/doctor-fix"),
            method="POST",
            headers=auth_headers(_token()),
        )
        assert "exit_code" in result
    except RuntimeError as exc:
        # 404 = no container exists (expected for users without containers)
        assert "404" in str(exc)


# ---------------------------------------------------------------------------
# File proxy
# ---------------------------------------------------------------------------

def test_file_download_missing_auth():
    """File download without auth should return 401."""
    try:
        json_request(
            api_url("/api/openclaw/filemanager/download?path=/foo.txt"),
        )
        assert False, "Expected 401"
    except RuntimeError as exc:
        assert "401" in str(exc)


def test_file_serve_missing_auth():
    """File serve without auth should return 401."""
    try:
        json_request(
            api_url("/api/openclaw/filemanager/serve?path=/foo.txt"),
        )
        assert False, "Expected 401"
    except RuntimeError as exc:
        assert "401" in str(exc)
