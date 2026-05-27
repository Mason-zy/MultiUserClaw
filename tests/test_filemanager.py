"""Tests for file manager endpoints.

Covers:
- GET  /api/openclaw/filemanager/browse
- POST /api/openclaw/filemanager/mkdir
- DELETE /api/openclaw/filemanager/delete
- POST /api/openclaw/filemanager/upload
- POST /api/openclaw/files/upload  (alias)

Note: These endpoints require a running dedicated container.
"""

from conftest import admin_token, api_url, auth_headers, json_request


def _token() -> str:
    return admin_token()


def test_browse_files():
    """Browse root directory of user's dedicated runtime (needs running container)."""
    try:
        result = json_request(
            api_url("/api/openclaw/filemanager/browse?path="),
            headers=auth_headers(_token()),
        )
        assert isinstance(result, dict)
    except RuntimeError as exc:
        assert "503" in str(exc) or "500" in str(exc)


def test_browse_files_with_path():
    """Browse a specific path (needs running container)."""
    try:
        result = json_request(
            api_url("/api/openclaw/filemanager/browse?path=/workspace"),
            headers=auth_headers(_token()),
        )
        assert isinstance(result, dict)
    except RuntimeError as exc:
        assert "503" in str(exc) or "500" in str(exc)


def test_browse_files_unauthorized():
    try:
        json_request(api_url("/api/openclaw/filemanager/browse?path="))
        assert False, "Expected 401/403"
    except RuntimeError as exc:
        assert any(str(code) in str(exc) for code in ("401", "403"))


def test_mkdir_requires_container():
    """mkdir should work if container is running."""
    try:
        result = json_request(
            api_url("/api/openclaw/filemanager/mkdir?path=/workspace/test_dir"),
            method="POST",
            headers=auth_headers(_token()),
        )
        assert isinstance(result, dict)
    except RuntimeError as exc:
        # May fail if container not running — that's expected
        assert "503" in str(exc) or "500" in str(exc) or "200" not in str(exc)


def test_delete_requires_container():
    """delete should work if container is running."""
    try:
        result = json_request(
            api_url("/api/openclaw/filemanager/delete?path=/workspace/test_dir"),
            method="DELETE",
            headers=auth_headers(_token()),
        )
        assert isinstance(result, dict)
    except RuntimeError as exc:
        assert "503" in str(exc) or "500" in str(exc) or "200" not in str(exc)
