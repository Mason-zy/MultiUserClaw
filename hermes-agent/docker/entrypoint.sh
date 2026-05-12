#!/bin/bash
# Docker entrypoint: bootstrap config files into the mounted volume, then run hermes.
set -e

HERMES_HOME="/opt/data"
INSTALL_DIR="/opt/hermes"

sync_nanobot_packaged_skills() {
    if [ "${NANOBOT_PACKAGED_SKILLS_SYNCED:-}" = "1" ]; then
        return 0
    fi

    local src_skills="$INSTALL_DIR/deploy_copy/skills"
    local dst_skills="$HERMES_HOME/skills"
    if [ ! -d "$src_skills" ]; then
        return 0
    fi

    mkdir -p "$dst_skills"
    echo "Syncing Nanobot packaged skills into $dst_skills"
    while IFS= read -r -d '' skill_src; do
        local skill_name
        local skill_dst
        skill_name="$(basename "$skill_src")"
        skill_dst="$dst_skills/$skill_name"
        rm -rf -- "$skill_dst"
        cp -a -- "$skill_src" "$dst_skills/"
        if [ "$(id -u)" = "0" ]; then
            chown -R hermes:hermes "$skill_dst"
        fi
    done < <(find "$src_skills" -mindepth 1 -maxdepth 1 -type d -print0)
    export NANOBOT_PACKAGED_SKILLS_SYNCED=1
}

# --- Privilege dropping via gosu ---
# When started as root (the default), optionally remap the hermes user/group
# to match host-side ownership, fix volume permissions, then re-exec as hermes.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "$(id -u hermes)" ]; then
        echo "Changing hermes UID to $HERMES_UID"
        usermod -u "$HERMES_UID" hermes
    fi

    if [ -n "$HERMES_GID" ] && [ "$HERMES_GID" != "$(id -g hermes)" ]; then
        echo "Changing hermes GID to $HERMES_GID"
        groupmod -g "$HERMES_GID" hermes
    fi

    mkdir -p "$HERMES_HOME"
    if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
        ln -sf /usr/bin/python3 /usr/local/bin/python
    fi
    sync_nanobot_packaged_skills

    actual_hermes_uid=$(id -u hermes)
    actual_hermes_gid=$(id -g hermes)
    if [ "$(stat -c %u "$HERMES_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
        echo "$HERMES_HOME is not owned by $actual_hermes_uid, fixing"
        chown hermes:hermes "$HERMES_HOME"
    fi

    for managed_file in "$HERMES_HOME/.env" "$HERMES_HOME/config.yaml" "$HERMES_HOME/SOUL.md"; do
        if [ -e "$managed_file" ] && [ "$(stat -c %u "$managed_file" 2>/dev/null)" != "$actual_hermes_uid" ]; then
            echo "$managed_file is not owned by $actual_hermes_uid:$actual_hermes_gid, fixing"
            chown hermes:hermes "$managed_file"
        fi
    done

    echo "Dropping root privileges"
    exec gosu hermes "$0" "$@"
fi

# --- Running as hermes from here ---
source "${INSTALL_DIR}/.venv/bin/activate"
cd "$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_hermes_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}
sync_nanobot_packaged_skills

# .env
if [ ! -f "$HERMES_HOME/.env" ]; then
    if [ -f "$INSTALL_DIR/.env.example" ]; then
        cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
    else
        touch "$HERMES_HOME/.env"
    fi
fi
chmod 600 "$HERMES_HOME/.env"

# config.yaml
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
fi
chmod 600 "$HERMES_HOME/config.yaml"

# NANOBOT Platform Integration: If NANOBOT_PROXY__URL is set, configure custom provider
# This allows the container to use the platform's LLM gateway as a proxy.
if [ -n "$NANOBOT_PROXY__URL" ] && [ -n "$NANOBOT_PROXY__TOKEN" ]; then
    echo "Configuring NANOBOT platform LLM proxy: $NANOBOT_PROXY__URL"

    # Inject platform proxy configuration into config.yaml using Python
    # Uses hermes-agent's native custom_providers format which accepts api_key.
    "$INSTALL_DIR/.venv/bin/python" << 'PYTHON_EOF'
import os
import sys
from pathlib import Path
import yaml

hermes_home = Path(os.environ.get('HERMES_HOME', '/opt/data'))
config_path = hermes_home / 'config.yaml'

# Read current config
try:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}
except Exception as e:
    print(f"Error reading config.yaml: {e}", file=sys.stderr)
    sys.exit(1)

# Get platform proxy settings from environment
proxy_url = os.environ.get('NANOBOT_PROXY__URL', '').strip()
proxy_token = os.environ.get('NANOBOT_PROXY__TOKEN', '').strip()
default_model = os.environ.get('NANOBOT_AGENTS__DEFAULTS__MODEL', '').strip()
api_toolsets_raw = os.environ.get('HERMES_API_TOOLSETS', '').strip()
reasoning_effort_raw = os.environ.get('HERMES_REASONING_EFFORT', '').strip()
service_tier_raw = os.environ.get('HERMES_SERVICE_TIER', '').strip()

if not proxy_url or not proxy_token:
    sys.exit(0)

# Create custom_providers entry using hermes-agent's native format
# This will be picked up by the model provider resolution logic
custom_provider_entry = {
    'name': 'platform-gateway',
    'base_url': proxy_url,
    'api_key': proxy_token,
}

# Initialize custom_providers list if it doesn't exist
if 'custom_providers' not in config:
    config['custom_providers'] = []
elif not isinstance(config['custom_providers'], list):
    print(f"Error: custom_providers must be a list, got {type(config['custom_providers'])}", file=sys.stderr)
    sys.exit(1)

# Remove any existing 'platform-gateway' entry to avoid duplicates
config['custom_providers'] = [
    p for p in config['custom_providers']
    if not (isinstance(p, dict) and p.get('name') == 'platform-gateway')
]

# Add the new entry
config['custom_providers'].append(custom_provider_entry)

# Ensure model section exists and set provider
if 'model' not in config:
    config['model'] = {}

config['model']['provider'] = 'platform-gateway'

# Set default model if specified
if default_model:
    config['model']['default'] = default_model

def parse_api_toolsets(raw):
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {'none', 'off', 'false', '0'}:
        return []
    if lowered in {'full', 'default', 'hermes-api-server'}:
        return ['hermes-api-server']
    return [part.strip() for part in raw.replace(';', ',').split(',') if part.strip()]

api_toolsets = parse_api_toolsets(api_toolsets_raw)
if api_toolsets is not None:
    config.setdefault('platform_toolsets', {})['api_server'] = api_toolsets

if reasoning_effort_raw:
    config.setdefault('agent', {})['reasoning_effort'] = reasoning_effort_raw

if service_tier_raw:
    config.setdefault('agent', {})['service_tier'] = service_tier_raw

# Save updated config
try:
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"✓ Updated config.yaml with platform-gateway provider")
except Exception as e:
    print(f"Error writing config.yaml: {e}", file=sys.stderr)
    sys.exit(1)

PYTHON_EOF
fi

# SOUL.md
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
fi
chmod 644 "$HERMES_HOME/SOUL.md"

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/tools/skills_sync.py"
fi

# Avoid relying on editable-install console-script metadata at runtime.
# Launch through the Nanobot wrapper so compatibility overlays are installed
# before Hermes dispatches subcommands such as "gateway run".
exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/nanobot_hermes.py" "$@"
