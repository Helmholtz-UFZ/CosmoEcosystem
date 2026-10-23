"""General application constants for Cosmo Ecosystem."""

# Number of days to keep a submitted job entries in the database
DAYS_DELETE_SUBMITTED = 60
# Number of days to keep an unsubmitted job entries in the database
DAYS_DELETE_NOT_SUBMITTED = 2
# Number of days to keep the logs
LOG_RETENTION_DAYS = 60

# The job's log file in the work dir, before the job log moved into the
# job_logs table. Only Job.delete_logs still uses it, to remove a leftover file
# from an old work dir; both go in the next version.
LOG_FILE_NAME = "logs"
