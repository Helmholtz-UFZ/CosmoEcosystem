# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm

ENV PATH=$PATH:/home/appuser/rclone-binaries/
ENV TZ=Europe/Berlin

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

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /python_docker/cosmo_ecosystem

# Build context is the repo root (see dev.Dockerfile): copy the repo, then install
# the EXAMPLE project (framework editable from ../..) as appuser, without dev deps.
COPY --chown=appuser:appuser . .

RUN chown appuser:appuser /python_docker/cosmo_ecosystem
WORKDIR /python_docker/cosmo_ecosystem/examples/csv_profiler
USER appuser
RUN uv sync --no-dev --frozen

# Setup rclone config and start gunicorn
CMD uv run gunicorn -w 4 -b 0.0.0.0:$FLASK_PORT csv_profiler.app:server
