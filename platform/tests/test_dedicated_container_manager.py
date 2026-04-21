import sys
import types

from app.config import Settings


if "docker" not in sys.modules:
    docker_stub = types.ModuleType("docker")
    docker_stub.DockerClient = object
    docker_stub.from_env = lambda: None
    docker_stub.types = types.SimpleNamespace(Mount=lambda *args, **kwargs: None)
    docker_stub.models = types.SimpleNamespace(containers=types.SimpleNamespace(Container=object))
    sys.modules["docker"] = docker_stub

    errors_module = types.ModuleType("docker.errors")
    errors_module.APIError = RuntimeError
    errors_module.NotFound = RuntimeError
    sys.modules["docker.errors"] = errors_module

from app.container import manager


class DummyContainer:
    def __init__(self, ports=None):
        self.attrs = {"NetworkSettings": {"Ports": ports or {}}}


def test_settings_expose_dedicated_container_prefix_fields():
    settings = Settings()

    assert settings.dedicated_runtime_container_name_prefix == "hermes-user"
    assert settings.dedicated_runtime_data_volume_prefix == "hermes-data"


def test_openclaw_runtime_uses_legacy_defaults(monkeypatch):
    monkeypatch.setattr(manager.settings, "dedicated_runtime_backend", "openclaw")
    monkeypatch.setattr(manager.settings, "dedicated_runtime_container_name_prefix", "openclaw-user")
    monkeypatch.setattr(manager.settings, "dedicated_runtime_data_volume_prefix", "openclaw-data")
    monkeypatch.setattr(manager.settings, "user_container_bind_ip", "0.0.0.0")

    assert manager._container_name("abc12345") == "openclaw-user-abc12345"
    assert manager._data_volume_name("abc12345") == "openclaw-data-abc12345"
    assert manager._runtime_published_ports() == {
        "5900/tcp": ("0.0.0.0", None),
        "30000/tcp": ("0.0.0.0", None),
    }
    assert manager._runtime_preferred_ports(5901, 30001) == {
        "5900/tcp": ("0.0.0.0", 5901),
        "30000/tcp": ("0.0.0.0", 30001),
    }


def test_hermes_runtime_switches_internal_port_publish(monkeypatch):
    monkeypatch.setattr(manager.settings, "dedicated_runtime_backend", "hermes")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_internal_port", 18123)
    monkeypatch.setattr(manager.settings, "user_container_bind_ip", "127.0.0.1")

    assert manager._internal_port() == 18123
    assert manager._runtime_command() == []
    assert manager._runtime_published_ports() == {"18123/tcp": ("127.0.0.1", None)}
    assert manager._runtime_preferred_ports(5901, 30001) is None



def test_hermes_runtime_environment_enables_api_server(monkeypatch):
    monkeypatch.setattr(manager.settings, "dedicated_runtime_backend", "hermes")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_internal_port", 18123)
    monkeypatch.setattr(manager.settings, "dedicated_hermes_api_key", "bridge-key")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_default_api_key", "proxy-key")
    monkeypatch.setattr(manager.settings, "default_model", "claude-sonnet-4-5")
    monkeypatch.setattr(manager.settings, "container_tz", "Asia/Shanghai")

    env = manager._runtime_environment("container-token", "sso-token")

    assert env["NANOBOT_PROXY__URL"] == "http://gateway:8080/llm/v1"
    assert env["NANOBOT_PROXY__TOKEN"] == "container-token"
    assert env["NANOBOT_AGENTS__DEFAULTS__MODEL"] == "claude-sonnet-4-5"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["API_SERVER_ENABLED"] == "true"
    assert env["API_SERVER_HOST"] == "0.0.0.0"
    assert env["API_SERVER_PORT"] == "18123"
    assert env["API_SERVER_KEY"] == "bridge-key"
    assert env["GATEWAY_ALLOW_ALL_USERS"] == "true"
    assert env["OPENAI_API_KEY"] == "proxy-key"
    assert env["INFOX_MED_TOKEN"] == "sso-token"
    assert "BRIDGE_ENABLE_CHANNELS" not in env


def test_build_hermes_runtime_files_support_platform_default_model(monkeypatch):
    monkeypatch.setattr(manager.settings, "default_model", "claude-sonnet-4-5")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_default_provider", "custom")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_default_base_url", "http://gateway:8080/llm/v1")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_api_key", "bridge-key")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_default_api_key", "proxy-key")

    config_yaml = manager._build_hermes_config_yaml()
    env_file = manager._build_hermes_env_file()

    assert 'default: claude-sonnet-4-5' in config_yaml
    assert 'provider: custom' in config_yaml
    assert 'base_url: http://gateway:8080/llm/v1' in config_yaml
    assert 'API_SERVER_KEY=bridge-key' in env_file
    assert 'GATEWAY_ALLOW_ALL_USERS=true' in env_file
    assert 'OPENAI_API_KEY=proxy-key' in env_file


def test_published_port_bindings_follow_runtime_backend(monkeypatch):
    openclaw_container = DummyContainer(
        {
            "5900/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5901"}],
            "30000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "30001"}],
        }
    )
    hermes_container = DummyContainer(
        {
            "18123/tcp": [{"HostIp": "127.0.0.1", "HostPort": "40123"}],
        }
    )

    monkeypatch.setattr(manager.settings, "dedicated_runtime_backend", "openclaw")
    assert manager._published_port_bindings(openclaw_container) == (
        ("0.0.0.0", "5901"),
        ("0.0.0.0", "30001"),
    )

    monkeypatch.setattr(manager.settings, "dedicated_runtime_backend", "hermes")
    monkeypatch.setattr(manager.settings, "dedicated_hermes_internal_port", 18123)
    assert manager._published_port_bindings(hermes_container) == (
        ("", ""),
        ("127.0.0.1", "40123"),
    )
