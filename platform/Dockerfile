FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install system dependencies (git + ssh needed for skills marketplace)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system --no-cache -r pyproject.toml --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# Copy application code
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY deploy_copy/ deploy_copy/

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
