#!/bin/bash

# Parse command line arguments
DEBUG_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
    -d | --debug)
        DEBUG_MODE=true
        shift
        ;;
    --local-computation-module)
        echo "Error: computation_module is part of this project."
        echo "This flag only works once you've extracted it into a separate Python package."
        echo "See README for details."
        exit 1
        ;;
    *)
        echo "Unknown option: $1"
        echo "Usage: $0 [-d|--debug]"
        echo "  -d, --debug:  Enable debug mode (FLASK_DEBUG=1)"
        exit 1
        ;;
    esac
done

# Copy env file and optionally override FLASK_DEBUG variable
cp env_dev .env

if [ "$DEBUG_MODE" = true ]; then
    sed -i 's/^FLASK_DEBUG=.*/FLASK_DEBUG=1/' .env
else
    sed -i 's/^FLASK_DEBUG=.*/FLASK_DEBUG=0/' .env
fi

# Build compose command
COMPOSE="docker compose -f docker-compose.yml"

# Rebuild images when uv.lock or Dockerfiles change
CURRENT_HASH="$(sha256sum uv.lock docker/dev.Dockerfile docker/worker.Dockerfile 2>/dev/null)"
if [ ! -e ".docker_build_hash" ] || [ "$CURRENT_HASH" != "$(cat .docker_build_hash)" ]; then
    $COMPOSE build cosmo-ecosystem
    $COMPOSE build cosmo-ecosystem-worker

    echo "$CURRENT_HASH" >.docker_build_hash
fi

cleaning_up() {
    echo "Cleaning up..."
    $COMPOSE down 2>/dev/null || true
}

trap cleaning_up EXIT

$COMPOSE down
docker rm -f postgres_cosmo_ecosystem 2>/dev/null || true

$COMPOSE up --no-log-prefix --attach cosmo-ecosystem
