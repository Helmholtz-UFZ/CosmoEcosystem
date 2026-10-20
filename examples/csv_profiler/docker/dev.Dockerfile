# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm

ENV PATH=$PATH:/home/appuser/rclone-binaries/

# Create non-root user early
RUN useradd -m -u 1000 appuser

# Install system dependencies
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get -y install --no-install-recommends \
        git \
        libpq-dev \
        gcc \
        python3-dev \
        libc-dev \
        curl \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# Install rclone
RUN curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
    unzip rclone-current-linux-amd64.zip && \
    mkdir -p /home/appuser/rclone-binaries && \
    cp rclone-*-linux-amd64/rclone /home/appuser/rclone-binaries/ && \
    chmod +x /home/appuser/rclone-binaries/rclone && \
    chown -R appuser:appuser /home/appuser/rclone-binaries && \
    rm -rf rclone-*

RUN rclone --version

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /python_docker/cosmo_ecosystem

# Build context is the repo root, so cosmo-ecosystem (a local-path dependency of the
# example) is present. Copy the repo, then install the EXAMPLE project — which pulls
# cosmo-ecosystem editable from ../.. — into the example's own venv.
COPY --chown=appuser:appuser . .

WORKDIR /python_docker/cosmo_ecosystem/examples/csv_profiler
ENV PATH="/python_docker/cosmo_ecosystem/examples/csv_profiler/.venv/bin:$PATH"
RUN uv sync --frozen

# Switch to non-root user
USER appuser

CMD if [ "$GUNICORN" = 1 ] ; then \
        exec gunicorn --preload -w 4 -b 0.0.0.0:$FLASK_PORT csv_profiler.app:server; \
    else \
        exec python3 csv_profiler/app.py; \
    fi
