"""This module defines variables, dir structure and includes widely used functions."""

import os

from dotenv import find_dotenv, load_dotenv


def getenv(name):
    """
    Retrieve the value of an environment variable.

    This function is a wrapper around the `os.getenv` function and provides additional
    error handling by raising a `ValueError` if the requested environment variable is
    not set.
    """
    value = os.getenv(name)

    if value is None:
        raise ValueError(f"Enviroment variable {name} not set.")
    return value


# Search from the CWD (the running app's directory), not from this file's location.
# The framework is installed away from the consumer app (site-packages, or the repo
# root in this monorepo), so its `.env` lives with the app, not next to config.py.
load_dotenv(find_dotenv(usecwd=True))

# Needed for the test_env.py. Update!
env_vars = [
    "WEB_WORK_DIR",
    "WEB_OUTSIDE_URL",
    "FLASK_PORT",
    "POSTGRES_DB",
    "POSTGRES_HOST_NAME",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "FLASK_DEBUG",
    "OBJECT_STORAGE_HOST",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "OBJECT_STORAGE_BUCKET",
    "OBJECT_STORAGE_REMOTE_NAME",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_PASSWORD",
]

# s/=.*//g |'<,'> s/^.*$/& = getenv("&")/g | noh
# Resolved against the CWD at import time, on purpose. A relative value (the
# .env files ship "./work_dir") reaches Flask's send_from_directory unresolved,
# and Flask resolves relative paths against app.root_path — the installed app
# package — not the CWD. The result is a silent 404 for every job file, with no
# import error and no failing test (measured in COSMONAUT).
WEB_WORK_DIR = os.path.abspath(getenv("WEB_WORK_DIR"))
WEB_OUTSIDE_URL = getenv("WEB_OUTSIDE_URL")
PORT = getenv("FLASK_PORT")
POSTGRES_DB = getenv("POSTGRES_DB")
POSTGRES_HOST_NAME = getenv("POSTGRES_HOST_NAME")
POSTGRES_PORT = getenv("POSTGRES_PORT")
POSTGRES_USER = getenv("POSTGRES_USER")
POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD")
DEBUG = getenv("FLASK_DEBUG") == "1"
OBJECT_STORAGE_HOST = getenv("OBJECT_STORAGE_HOST")
OBJECT_STORAGE_ACCESS_KEY = getenv("OBJECT_STORAGE_ACCESS_KEY")
OBJECT_STORAGE_SECRET_KEY = getenv("OBJECT_STORAGE_SECRET_KEY")
OBJECT_STORAGE_BUCKET = getenv("OBJECT_STORAGE_BUCKET")
OBJECT_STORAGE_REMOTE_NAME = getenv("OBJECT_STORAGE_REMOTE_NAME")
REDIS_HOST = getenv("REDIS_HOST")
REDIS_PORT = getenv("REDIS_PORT")
REDIS_DB = getenv("REDIS_DB")
REDIS_PASSWORD = getenv("REDIS_PASSWORD")

JOB_WORK_DIR_TEMPLATE = os.path.join(WEB_WORK_DIR, "{job_id}")
