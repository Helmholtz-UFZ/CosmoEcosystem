"""``lost_run_domain`` with a 5 s visibility timeout, for the pod-kill test.

Redis redelivers an unacked message after the visibility timeout (default 1 h);
5 s brings the redelivery of a killed worker's message into the test's window.
kombu restores such messages when a worker starts and then only every tenth
10 s cycle (``QoS.restore_visible(interval=10)``), so the test restarts the
worker after the timeout has passed, as a pod restart does.
"""

from cosmo_ecosystem.celery_config import BaseCeleryConfig

from lost_run_domain import (  # noqa: F401  (domain module attributes)
    CeleryConfig,
    excluded_log_packages,
    log_retention_days,
    task_specs,
)

VISIBILITY_TIMEOUT_SECONDS = 5


class RedeliveryCeleryConfig(CeleryConfig):
    """Redeliver after 5 s; keep the base config's socket timeouts."""

    broker_transport_options = {
        **BaseCeleryConfig.broker_transport_options,
        "visibility_timeout": VISIBILITY_TIMEOUT_SECONDS,
    }


celery_config = RedeliveryCeleryConfig
