"""Framework-scope test setup.

``cosmo_ecosystem.config`` reads its environment at import time and raises for any
variable that is missing, so every value has to exist before a test module
imports anything from the framework. pytest loads this file before it collects
the test modules, which makes it the only place that can set them without an
inline import.

The framework suite talks to no service — no postgres, no object storage, no redis — so
these are placeholders that only need to be present and syntactically valid. A
variable already exported in the environment wins, which is what lets the same
suite run inside the example's docker stack.
"""

import os

FRAMEWORK_TEST_ENV = {
    "WEB_WORK_DIR": "./work_dir",
    "WEB_OUTSIDE_URL": "http://localhost:8080",
    "FLASK_PORT": "8080",
    "FLASK_DEBUG": "0",
    "POSTGRES_DB": "cosmo_ecosystem",
    "POSTGRES_HOST_NAME": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "cosmo_ecosystem_user",
    "POSTGRES_PASSWORD": "test",
    "OBJECT_STORAGE_HOST": "http://localhost:9000",
    "OBJECT_STORAGE_ACCESS_KEY": "accesskey",
    "OBJECT_STORAGE_SECRET_KEY": "secretkey",
    "OBJECT_STORAGE_BUCKET": "cosmo-ecosystem-jobs",
    "OBJECT_STORAGE_REMOTE_NAME": "cosmo-ecosystem-remote",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_DB": "0",
    "REDIS_PASSWORD": "",
}

for _name, _value in FRAMEWORK_TEST_ENV.items():
    os.environ.setdefault(_name, _value)
