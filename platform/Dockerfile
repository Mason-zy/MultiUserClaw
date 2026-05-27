FROM python:3.13-slim-bookworm

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} uv

# Copy dependency files first for better layer caching
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
