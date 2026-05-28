FROM debian:13.4

# Disable Python stdout buffering to ensure logs are printed immediately
ENV PYTHONUNBUFFERED=1

# Store Playwright browsers outside the volume mount so the build-time
# install survives the /opt/data volume overlay at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
ARG APT_DEBIAN_MIRROR=http://mirrors.ustc.edu.cn/debian
ARG APT_SECURITY_MIRROR=http://mirrors.ustc.edu.cn/debian-security
ENV PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST}

# Install system dependencies in one layer, clear APT cache
# tini reaps orphaned zombie processes (MCP stdio subprocesses, git, bun, etc.)
# that would otherwise accumulate when hermes runs as PID 1. See #15012.
RUN sed -i \
        -e "s|http://deb.debian.org/debian|${APT_DEBIAN_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --fix-missing --no-install-recommends \
    build-essential curl nodejs npm python3 python3-pip ripgrep ffmpeg gcc python3-dev libffi-dev procps git tini chromium pandoc gosu && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --no-cache-dir -i ${PIP_INDEX_URL} uv

# Non-root user for runtime; UID can be overridden via HERMES_UID at runtime
RUN useradd -u 10000 -m -d /opt/data hermes

WORKDIR /opt/hermes

# ---------- Layer-cached dependency install ----------
# Copy only package manifests first so npm install + Playwright are cached
# unless the lockfiles themselves change.
#
# ui-tui/packages/hermes-ink/ is copied IN FULL (not just its manifests)
# because it is referenced as a `file:` workspace dependency from
# ui-tui/package.json.  Copying the tree up front lets npm resolve the
# workspace to real content instead of stopping at a bare package.json.
COPY package.json package-lock.json ./
COPY web/package.json web/package-lock.json web/
COPY ui-tui/package.json ui-tui/package-lock.json ui-tui/
COPY ui-tui/packages/hermes-ink/ ui-tui/packages/hermes-ink/

# `npm_config_install_links=false` forces npm to install `file:` deps as
# symlinks (the npm 10+ default) even on Debian's older bundled npm 9.x,
# which defaults to `install-links=true` and installs file deps as *copies*.
# The host-side package-lock.json is generated with a newer npm that uses
# symlinks, so an install-as-copy produces a hidden node_modules/.package-lock.json
# that permanently disagrees with the root lock on the @hermes/ink entry.
# That disagreement trips the TUI launcher's `_tui_need_npm_install()`
# check on every startup and triggers a runtime `npm install` that then
# fails with EACCES (node_modules/ is root-owned from build time).
ENV npm_config_install_links=false
RUN npm config set registry ${NPM_REGISTRY} && \
    npm config set fetch-retries 5 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retry-maxtimeout 120000

RUN npm install --prefer-offline --no-audit && \
    (cd web && npm install --prefer-offline --no-audit) && \
    (cd ui-tui && npm install --prefer-offline --no-audit) && \
    npm cache clean --force

# ---------- Layer-cached Python dependency install ----------
# README.md is referenced by pyproject.toml's `readme =` field, but it's
# excluded from the build context by .dockerignore's `*.md`.  uv's build
# frontend stats the readme path during dep resolution, so we `touch` an
# empty placeholder.
COPY pyproject.toml uv.lock ./
RUN touch ./README.md
RUN uv sync --no-install-project --extra all

COPY . /opt/hermes

# Build frontend assets (web dashboard + terminal UI)
RUN cd web && npm run build && \
    cd ../ui-tui && npm run build

# Permissions: make .venv and node_modules writable by hermes user
# (needed for lazy runtime installs and for TUI dependency checks).
RUN chmod -R a+rX /opt/hermes && \
    chown -R hermes:hermes /opt/hermes/.venv /opt/hermes/ui-tui /opt/hermes/node_modules && \
    chmod +x /opt/hermes/docker/entrypoint.sh

ENV HERMES_WEB_DIST=/opt/hermes/hermes_cli/web_dist
ENV HERMES_HOME=/opt/data
ENV PATH="/opt/data/.local/bin:${PATH}"
VOLUME [ "/opt/data" ]
ENTRYPOINT [ "/opt/hermes/docker/entrypoint.sh" ]

ENV API_SERVER_ENABLED=true
ENV API_SERVER_HOST=0.0.0.0
ENV API_SERVER_PORT=18080
ENV API_SERVER_KEY=dev-hermes-bridge-key
ENV GATEWAY_ALLOW_ALL_USERS=true

EXPOSE 18080

CMD ["gateway", "run"]
