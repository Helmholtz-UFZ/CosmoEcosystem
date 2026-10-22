# The remote prefix is a job's authoritative copy; the work dir is a cache

A job's files exist twice, in a work dir and under its remote prefix, and the three
apps disagreed about which one wins. We decided the remote prefix wins. Every read
of a work dir pulls changed files first (`--checksum`). Every change to a job's
inputs is written through right away, so no edit exists only on local disk. Uploads
never delete remote files; deleting is an explicit operation applied in both
places. This holds whether or not the pods share a disk, and in production we do
not know whether they do.

## Considered Options

- **The work dir wins, with lazy upload.** This was COSMONAUT's `sync_files=False`
  and the framework's `--ignore-existing`. It is only correct if every request for a
  job lands on the pod that holds its edits. It also produced stale downloads,
  which `ServedJob` patched over.
- **A shared PVC is the truth and S3 only an archive.** Production mounts one work
  dir PVC into both web and worker pods, so this would be fastest. It was rejected
  because nobody can currently confirm the PVC's access mode or the pod placement,
  and the local and CI stacks do not share disks the same way.

## Consequences

- Interactive edits that happen often (COSMONAUT street edits) write only their
  *intent* to the job row. The large files they produce are **derived files**: they
  may run ahead of the remote prefix and are recomputed when they are missing or do
  not match the intent. This is the only sanctioned way for local disk to hold data
  the remote prefix lacks.
- Uploads use `rclone copy`, not `sync`. A web save during a run can therefore no
  longer delete a worker's fresh results.
- Live logs during a run are still read from the local log file, which only works
  because of the shared PVC. Moving job logs to the database belongs to roadmap
  step #3.
- A reused job id (COSMOPOLITAN) can leave stale extra files on another pod's
  local disk, because a pull never deletes local files. With a shared PVC,
  `delete_job` removes them.
