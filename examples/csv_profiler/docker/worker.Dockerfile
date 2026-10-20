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

RUN rclone --version

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /python_docker/cosmo_ecosystem

# Build context is the repo root (see dev.Dockerfile): copy the repo, then install
# the EXAMPLE project (which pulls cosmo-ecosystem editable from ../..) into its venv.
COPY --chown=appuser:appuser . .

WORKDIR /python_docker/cosmo_ecosystem/examples/csv_profiler
ENV PATH="/python_docker/cosmo_ecosystem/examples/csv_profiler/.venv/bin:$PATH"
RUN uv sync --frozen

# Switch to non-root user
USER appuser

# Worker command.
#
# `&&`, not `;`. With `;` a failing storage setup — a moved module, a bad path —
# still let Celery start, just without a configured rclone remote, and the first
# symptom was a job failing three layers away from the cause. The import path
# below is a string no linter reads, and no suite starts the worker through this
# image — both use `uv run celery`. The `exec celery` marker is what lets a build
# job run the setup step on its own; see docs/conventions/worker_image.md.
# --beat embeds the Celery Beat scheduler. It belongs here and not in the web
# process (see app.py), and it relies on there being exactly one worker container:
# a second replica would run every scheduled task twice.
CMD echo "Starting Celery worker..." && \
    python3 /python_docker/cosmo_ecosystem/cosmo_ecosystem/object_storage_manager.py setup_remote && \
    exec celery -A csv_profiler.celery_app.celery worker \
        --loglevel=debug \
        --concurrency=4 \
        --queues=default,computation,maintenance \
        --beat \
        --hostname=worker@%h \
        --without-gossip \
        --without-mingle;
