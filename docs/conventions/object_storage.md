# Object Storage

Where job files live, which S3 server stands in for production locally and in CI,
and the places an app has to wire it up. Read this before you add an app or swap
the server.

## The setup

| | Server | Who runs it |
|---|---|---|
| Production, stage | UFZ S3 (`https://vip.s3.ufz.de`) | UFZ IT |
| Local runs, CI | RustFS, `rustfs/rustfs:1.0.0` | us, as a throwaway container without a volume |

The framework speaks plain S3 and nothing else. rclone does the transfers
(`provider=Other`, path style, region `us-east-1`), and boto3 signs the download
URLs. Nothing in `cosmo_ecosystem/` knows which server sits behind
`OBJECT_STORAGE_HOST`.

## Rules

- **Name things after the role, not the product.** The compose service and the CI
  alias are `object-storage`, the container is `object_storage_<app>`, and the host
  ports are `OBJECT_STORAGE_HOST_PORT` / `OBJECT_STORAGE_CONSOLE_HOST_PORT`.
  "minio" in exactly these places is what turned the end of MinIO into a rename
  across three repos.
- **CI: include, don't copy.** Include `ci/object-storage.gitlab-ci.yml` at the tag
  your `pyproject.toml` pins, and splice it into the test job with `!reference`
  (see the header of that file). Bump the include `ref` together with the pin.
- **Compose: copy the block below as it is.** Only `container_name` changes.
- **`run_pytest.sh` asks Docker for the health status.** The server-specific probe
  lives in the compose healthcheck, nowhere else.
- **No rclone setup in CI scripts.** The conftest (and `app.py`) already call
  `setup_remote()` and `create_bucket()`, which do it for every server.
- **Pin exact image tags.** Never `latest`.
- **Never sweep the bucket.** Delete a job's remote prefix only through
  `cosmo_ecosystem.job_retention.delete_job`, for a job whose row is being
  deleted. A rowless prefix or local dir proves nothing: COSMOPOLITAN's stage and
  prod databases share the bucket `cosmopolitan-prod`, so a sweep run from stage
  would delete every prod job. Leftovers are reviewed by hand, never swept.
- **The server takes its keys from `OBJECT_STORAGE_ACCESS_KEY` /
  `OBJECT_STORAGE_SECRET_KEY`.** Compose interpolates them from `.env`, and CI takes
  them from the job variables. RustFS refuses to start with an empty key.

## Wiring up a new app

1. Pin `cosmo-ecosystem` in `pyproject.toml` (see the README).
2. CI: add the include and the two `!reference` lines, set
   `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` as job variables, and
   put `OBJECT_STORAGE_HOST="http://object-storage:9000"` in the CI env file.
3. Compose: copy the block below and make the app services depend on it with
   `condition: service_healthy`.
4. Env files: a suite running on the host uses
   `OBJECT_STORAGE_HOST="http://localhost:<host port>"`. An app inside the compose
   network uses `http://object-storage:9000`. Take the host ports from your slot in
   [`local-port-allocation.md`](../plan/local-port-allocation.md).
5. `run_pytest.sh`: start `object-storage`, then wait on its health status:

   ```bash
   check_service "docker inspect -f '{{.State.Health.Status}}' object_storage_<app> 2>/dev/null | grep -qx healthy" "Object storage"
   ```

6. Worker image: `setup_remote` in the `CMD`, chained with `&&`
   ([worker_image.md](worker_image.md)).

## The compose block

```yaml
  object-storage:
    image: rustfs/rustfs:1.0.0
    container_name: object_storage_<app>
    ports:
      - "${OBJECT_STORAGE_HOST_PORT:-9000}:9000"
      - "${OBJECT_STORAGE_CONSOLE_HOST_PORT:-9001}:9001" # Web console at /rustfs/console/
    environment:
      RUSTFS_ACCESS_KEY: ${OBJECT_STORAGE_ACCESS_KEY}
      RUSTFS_SECRET_KEY: ${OBJECT_STORAGE_SECRET_KEY}
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:9000/health/ready"]
      interval: 2s
      timeout: 3s
      retries: 15
```

`examples/csv_profiler/docker-compose.yml` carries the same block, and
`test/test_object_storage_image.py` fails if its image and the CI template's
image differ.

## Swapping the server

1. In this repo, change the CI template, the example's compose block and this
   file. Then run the example suite: the presigned-URL test and the e2e job cover
   both halves.
2. Release the framework.
3. In each app, re-pin (which also moves the include `ref`) and replace the image,
   `environment` and healthcheck lines of its compose block.

## Why RustFS and boto3 (decided 2026-09-16, issue #1)

- **MinIO Community Edition is gone.** It has had no images since October 2025, the
  repo was archived in April 2026, and in September 2026 the image disappeared from
  Docker Hub.
- **RustFS 1.0.0** is Apache-2.0 and built as a MinIO replacement. It starts in
  about a second and answers `/health/ready`. It was checked against everything
  the framework does: rclone sync, copy, delete and purge, and presigned GETs,
  including an expired URL and a wrong signature (both 403).
  - Fallbacks: VersityGW, SeaweedFS.
  - Ruled out: LocalStack (repo archived, now needs an auth token) and Garage (AGPL,
    and it needs a layout set up by CLI after the start, which a CI service can't
    do).
- **boto3 instead of minio-py.** minio-py has had no PyPI release since 7.2.20
  (November 2025), and its development now follows MinIO's commercial product.
  - boto3 signs offline. minio-py sent one GetBucketLocation request per URL,
    because the client was built without a region, and a network error in that
    request slipped past the `ObjectStorageError` wrapper.
  - The cost is about 30 MB of installed size (botocore), against 0.4 MB for
    minio-py. Only presigning uses boto3; transfers stay on rclone.
- **Region `us-east-1` for both clients.** rclone has always signed with it against
  UFZ S3.

## Gotchas

- **`extends:` replaces lists**, so `services` and `before_script` have to come in
  through `!reference`. GitLab documents `!reference` only for the script keywords.
  For `services` it works on codebase.helmholtz.cloud (GitLab 19.2): the CI lint
  API flattens nested entries and validates each one.
- **`HEALTHCHECK_TCP_PORT: "9000"`** is set in the template because the image also
  exposes 9001. Without it the runner waits on the console port as well.
- **The console is at `/rustfs/console/`**, not `/`, which returns 403.
- **The container runs as UID 10001.** A data bind mount, if you ever add one, has
  to be writable by that user.
- **Presigned URLs expire after at most seven days.** `get_presigned_download_url`
  raises `ValueError` beyond that. boto3 would sign the URL anyway, and it would
  fail only when someone uses it.
- **botocore must stay out of the logs.** At DEBUG it writes about 60 records per
  signed URL, the signature among them — enough to rebuild a working link from the
  logs page. `cosmo_ecosystem.logger` mutes `boto3`, `botocore` and `s3transfer` for
  every consumer; v0.8.0 shipped without that.
- **URLs signed in a local run point at `localhost`**, so a phone scanning the QR
  code cannot reach them. That is expected.
- **The include `ref` and the pyproject pin can drift apart.** The only effect is a
  different server version in CI, so no test guards it.
- **Deleting a prefix that does not exist succeeds.** Job deletion relies on this to
  treat a job that never uploaded anything as already deleted. Measured 2026-10-21
  against RustFS with rclone 1.75.2 (the `rclone-current` download in the
  COSMOPOLITAN and csv_profiler images) and 1.60.1 (Debian's apt package, used by
  COSMONAUT and CI): `rclone purge` on a missing prefix in an existing bucket exits 0
  with empty stderr. A missing *bucket* exits 3 (`directory not found`) and raises
  `ObjectStorageError` after the retries, because that is a configuration error,
  not an absent job. The example suite pins the first half; re-measure if an image
  moves to a different rclone major version.
