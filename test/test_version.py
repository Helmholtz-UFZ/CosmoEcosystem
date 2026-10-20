"""The four hand-maintained places the version is written, checked against each other.

Between v0.6.0 and v0.6.2 the tag, ``pyproject.toml`` and ``CITATION.cff`` drifted
three ways and had to be reconciled by hand. This repo has no release job that
writes the version before tagging — the apps do, which is why they do not have the
problem — so the cheap substitute is a test.

**Against each other, not against a tag.** Two of the four are documentation
examples showing a consumer how to pin, and they name the version that is *about
to* be released. Checking them against an existing tag would fail exactly when
someone is preparing a release, which is the one moment this test has to be green.

**Only the hand-maintained places.** Both ``uv.lock`` files record the version too,
but ``uv lock`` writes them. They are derived, not a place anyone edits, and
``uv lock --check`` in the lint jobs already covers them.
"""

import re
import tomllib
from pathlib import Path

from cosmo_ecosystem.job import FRAMEWORK_VERSION

REPO_ROOT = Path(__file__).parent.parent

PYPROJECT = REPO_ROOT / "pyproject.toml"
CITATION = REPO_ROOT / "CITATION.cff"

# The files carrying a `cosmo-ecosystem@vX.Y.Z` pin example for a consumer. Every
# occurrence in them has to name the current version — scanned rather than
# addressed by line number, so a second example added later is covered too.
PIN_EXAMPLE_FILES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "examples" / "csv_profiler" / "pyproject.toml",
)
PIN_PATTERN = re.compile(r"cosmo-ecosystem@v(\d+\.\d+\.\d+)")

# CITATION.cff is YAML, but pyyaml is not a dependency of this project and one
# top-level key is not worth making it one.
CITATION_VERSION_PATTERN = re.compile(r'^version:\s*"?(\d+\.\d+\.\d+)"?\s*$', re.M)


def project_version():
    """The authoritative version: what the package actually builds as."""
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def test_citation_matches_pyproject():
    """``CITATION.cff`` is the half that got forgotten twice."""
    match = CITATION_VERSION_PATTERN.search(CITATION.read_text())

    assert match is not None, f"no top-level `version:` in {CITATION.name}"
    assert match.group(1) == project_version()


def test_pin_examples_match_pyproject():
    """The documented pin must name the version being released.

    A consumer copies these lines. Leaving them on the previous tag hands out a
    pin that silently installs the version before the one the reader is reading
    about — which is how COSMOPOLITAN and COSMONAUT ended up on v0.6.1 while
    v0.6.2 existed.
    """
    version = project_version()

    stale = []
    for path in PIN_EXAMPLE_FILES:
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            for found in PIN_PATTERN.findall(line):
                if found != version:
                    rel = path.relative_to(REPO_ROOT)
                    stale.append(f"{rel}:{line_number} pins v{found}")

    assert not stale, f"pyproject.toml says {version}, but:\n  " + "\n  ".join(stale)


def test_every_pin_example_file_actually_carries_one():
    """Guard the guard.

    The check above passes trivially if a pin example is reworded out of
    existence or moved to a file this list does not name. Then the version can
    drift again with a green suite, which is the failure mode this whole module
    exists for.
    """
    for path in PIN_EXAMPLE_FILES:
        assert PIN_PATTERN.search(path.read_text()), (
            f"{path.relative_to(REPO_ROOT)} carries no `cosmo-ecosystem@vX.Y.Z` pin "
            "example any more — drop it from PIN_EXAMPLE_FILES or restore the "
            "example, but do not leave this test checking nothing."
        )


def test_job_records_the_installed_framework_version():
    """``job.FRAMEWORK_VERSION`` looks the distribution up by its *name*.

    A missing distribution falls back to ``"unknown"`` on purpose (provenance,
    never control flow), so a name that no longer matches ``pyproject.toml`` —
    exactly what a rename leaves behind — would stamp every new job ``"unknown"``
    with a green suite. Comparing against ``pyproject.toml`` makes it loud.
    """
    assert FRAMEWORK_VERSION == project_version()
