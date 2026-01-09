# Use a slim Python 3.12 image
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/root/.local/bin:$PATH" \
    MCP_ARGS="--config /app/config/config.yaml --transport http --host 0.0.0.0 --port 8000"

# Install system dependencies including supervisor
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install uv for package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first to leverage cache
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the application
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose MCP server port
EXPOSE 8000

# Run both engine and MCP server via supervisor
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
