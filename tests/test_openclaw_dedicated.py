"""Tests for dedicated OpenClaw runtime endpoints.

Covers:
- GET  /api/openclaw/agents
- GET  /api/openclaw/skills
- POST /api/openclaw/marketplaces/skills/search
- POST /api/openclaw/runtime/prewarm
- GET  /api/openclaw/sessions
- GET  /api/openclaw/commands
- GET  /api/openclaw/container/info
- GET  /api/openclaw/ping

Note: /api/openclaw/sessions/{key}/messages requires a running dedicated
container, which may not be available in all test environments.
"""

from conftest import admin_token, api_url, auth_headers, json_request


def _token() -> str:
    return admin_token()


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def test_list_agents():
    result = json_request(
        api_url("/api/openclaw/agents"),
        headers=auth_headers(_token()),
    )
    # Response may vary by runtime; should be a dict or list
    assert result is not None


def test_list_agents_unauthorized():
    try:
        json_request(api_url("/api/openclaw/agents"))
        assert False, "Expected 401/403"
    except RuntimeError as exc:
        assert any(str(code) in str(exc) for code in ("401", "403"))


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def test_list_skills():
    try:
        result = json_request(
            api_url("/api/openclaw/skills"),
            headers=auth_headers(_token()),
        )
        assert isinstance(result, (list, dict))
    except RuntimeError as exc:
        # May fail with 503 if no dedicated container is running
        assert "503" in str(exc) or "Hermes runtime is unavailable" in str(exc)


def test_search_skills():
    try:
        result = json_request(
            api_url("/api/openclaw/marketplaces/skills/search"),
            method="POST",
            payload={"query": "", "limit": 5},
            headers=auth_headers(_token()),
        )
        assert "results" in result
        assert result["runtime"] == "hermes"
        assert isinstance(result["results"], list)
    except RuntimeError as exc:
        assert "503" in str(exc)


def test_search_skills_with_query():
    try:
        result = json_request(
            api_url("/api/openclaw/marketplaces/skills/search"),
            method="POST",
            payload={"query": "code", "limit": 3},
            headers=auth_headers(_token()),
        )
        assert "results" in result
    except RuntimeError as exc:
        assert "503" in str(exc)


# ---------------------------------------------------------------------------
# Prewarm
# ---------------------------------------------------------------------------

def test_prewarm_runtime():
    result = json_request(
        api_url("/api/openclaw/runtime/prewarm"),
        method="POST",
        headers=auth_headers(_token()),
    )
    assert "ok" in result


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_list_sessions():
    result = json_request(
        api_url("/api/openclaw/sessions"),
        headers=auth_headers(_token()),
    )
    # Should return a list (may be empty if no sessions exist)
    assert isinstance(result, (list, dict))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def test_list_commands():
    result = json_request(
        api_url("/api/openclaw/commands"),
        headers=auth_headers(_token()),
    )
    # Hermes returns empty commands list; should be a dict
    assert isinstance(result, dict)
    assert "commands" in result


def test_list_commands_with_agent_id():
    result = json_request(
        api_url("/api/openclaw/commands?agentId=main"),
        headers=auth_headers(_token()),
    )
    assert "commands" in result


# ---------------------------------------------------------------------------
# Container info
# ---------------------------------------------------------------------------

def test_container_info():
    result = json_request(
        api_url("/api/openclaw/container/info"),
        headers=auth_headers(_token()),
    )
    # May return no container if not yet created
    assert "status" in result
    assert result["status"] in ("running", "none", "stopped", "paused", None)


# ---------------------------------------------------------------------------
# Proxy ping
# ---------------------------------------------------------------------------

def test_proxy_ping():
    result = json_request(
        api_url("/api/openclaw/ping"),
        headers=auth_headers(_token()),
    )
    assert result["message"] == "pong"
    assert result["service"] == "openclaw-proxy"
