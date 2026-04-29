from app.config import Settings


def test_settings_expose_dedicated_runtime_selector_fields():
    settings = Settings()

    assert settings.openclaw_image == "openclaw:latest"
    assert settings.hermes_image == "nanobot-hermes-agent:latest"
    assert settings.dedicated_runtime_backend == "hermes"
    assert settings.dedicated_hermes_url == ""
    assert settings.dedicated_runtime_container_name_prefix == "hermes-user"
    assert settings.dedicated_runtime_data_volume_prefix == "hermes-data"
    assert settings.hermes_connect_retries == 60
    assert settings.hermes_retry_delay_seconds == 0.5


def test_settings_expose_shared_runtime_selector_fields():
    settings = Settings()

    assert settings.shared_openclaw_url == "http://shared-openclaw:18080"
    assert settings.shared_runtime_backend == "hermes"
    assert settings.shared_hermes_url == "http://shared-openclaw:8080"
    assert settings.shared_hermes_api_key == "dev-hermes-bridge-key"
