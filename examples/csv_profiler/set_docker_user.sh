# Sourced by the scripts that start the app and worker containers. Exports
# DOCKER_UID/DOCKER_GID for `user:` in docker-compose.yml; values exported in the
# shell take precedence over the ones in .env.
#
# The container writes into the bind-mounted source tree, so it has to run as the
# host user that owns it:
# - rootful Docker: container IDs are host IDs, so the host user's own IDs.
# - rootless Docker: container root maps to the host user, and every other
#   container ID maps to a subordinate ID (/etc/subuid) without write access.
#   A fixed 1000 fails here with "Permission denied" on the first write.
if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
    export DOCKER_UID=0 DOCKER_GID=0
else
    DOCKER_UID="$(id -u)"
    DOCKER_GID="$(id -g)"
    export DOCKER_UID DOCKER_GID
fi
