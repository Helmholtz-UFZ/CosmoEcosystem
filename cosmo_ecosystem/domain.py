"""Discovery of the app's domain module, named by ``COSMO_DOMAIN``.

Celery assembly, the framework cleanup and the ``job_retention`` CLI all reach
the domain this way. The contract of the module is documented in
docs/conventions/domain_module.md.
"""

import importlib
import os

from cosmo_ecosystem.error_handling import DomainNotConfigured


def load_domain():
    """Import and return the module ``COSMO_DOMAIN`` names.

    Raises:
        DomainNotConfigured: If ``COSMO_DOMAIN`` is unset.
    """
    # Read here, at call time, not as a constant in config.py: config.py reads every
    # variable at import, and importing the framework must not need a domain (the
    # test and CLI processes import it without one). It is in config.env_vars all
    # the same, so that test_env.py checks every env file sets it.
    try:
        domain_path = os.environ["COSMO_DOMAIN"]
    except KeyError as e:
        raise DomainNotConfigured() from e
    # A dynamic import, against the top-level-only rule on purpose: only the
    # deployment knows which app the framework runs.
    return importlib.import_module(domain_path)
