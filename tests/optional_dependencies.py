"""Skip a test when what it needs is optional and absent, rather than failing it.

niess imports without `tof`, `build123d` or `chopcal`, so a checkout that installed
none of them should still run the suite green. `pytest.importorskip` covers a module
that imports its extras at the top, but the docs examples do not: `tof_model.py` imports
`niess.tof`, which reaches the real `tof` only when a model is built, several frames
inside `main()`. The failure arrives as an ImportError from the middle of a run.

So the rule here is on the *error*, not on the source text: an ImportError naming a module
niess declares optional is a missing extra and skips; anything else is a broken example and
fails. Deriving the list from `pyproject.toml` rather than repeating it means a new extra is
covered by declaring it, and, more to the point, a package that stops being optional stops
being skippable in the same commit.
"""
from __future__ import annotations

import re
import tomllib
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# `ModuleNotFoundError: No module named 'tof'`, including the chained original behind a
# helper that re-raises with friendlier advice.
NO_MODULE = re.compile(r"No module named '([\w.]+)'")


def optional_modules() -> frozenset[str]:
    """Top-level import names niess declares under `[project.optional-dependencies]`.

    Distribution names, near enough: the ones niess uses match their import name once
    dashes become underscores. A distribution that does not would simply never match, and
    the test would fail as it does today rather than skip wrongly.
    """
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    names = set()
    for requirements in project.get('optional-dependencies', {}).values():
        for requirement in requirements:
            name = re.match(r'[A-Za-z0-9._-]+', requirement)
            if name:
                names.add(name.group(0).lower().replace('-', '_'))
    return frozenset(names)


OPTIONAL_MODULES = optional_modules()


def missing_optional(error: BaseException) -> str | None:
    """The optional module an ImportError blames, following the chain that raised it."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        candidates = []
        if isinstance(error, ImportError) and error.name:
            candidates.append(error.name)
        candidates.extend(NO_MODULE.findall(str(error)))
        for candidate in candidates:
            root = candidate.split('.')[0].lower()
            if root in OPTIONAL_MODULES:
                return root
        error = error.__cause__ or error.__context__
    return None


def skip_if_optional_is_missing(error: BaseException) -> None:
    """Turn a missing extra into a skip; leave every other failure alone."""
    module = missing_optional(error)
    if module is not None:
        pytest.skip(f"needs the optional '{module}': pip install 'niess[examples]'")


@contextmanager
def skipping_missing_optionals():
    try:
        yield
    except Exception as error:
        skip_if_optional_is_missing(error)
        raise
