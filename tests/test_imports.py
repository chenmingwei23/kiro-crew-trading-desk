"""Every module in this repository imports.

A missing import is invisible to the rest of the suite: nothing here exercised
``dev/harness.py``, so it shipped reading ``os.environ`` without importing ``os``
and failed at line 31 for anyone who ran it. This walks the tree instead of naming
files, so a module added later is covered without touching this test.

Each import runs in a subprocess, for two reasons: a module with import-time side
effects cannot leak state into the rest of the suite, and a module that mutates
``sys.path`` cannot change what a later test sees. The subprocess is given the same
path ``conftest`` builds — the repository root, then any ``KIROCREW_SRC`` checkout —
so "the gateway is importable" means the same thing on both sides.

Two exclusions, both because the failure would be about the environment rather
than the code:

* ``backend/routes.py`` and ``backend/selftest_routes.py`` import the gateway's
  ``kiro_crew``. Skipped only when that is the whole reason the import failed, so
  a real defect in either file is still reported.
* ``fixtures/gen_fixtures.py`` reads the desk config at import time, so importing
  it is running it. It is covered by ``test_fixtures.py`` instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Directories holding importable modules. ``tests/`` is excluded because pytest
#: has already imported it by the time this runs.
PACKAGES = ("backend", "crews", "scripts", "dev", "config/engine")

#: Needs the gateway on the path. Skipped only on a missing ``kiro_crew``.
NEEDS_GATEWAY = frozenset({"backend.routes", "backend.selftest_routes"})

#: Importing it runs it. Covered by test_fixtures.py.
RUNS_ON_IMPORT = frozenset({"fixtures.gen_fixtures"})

#: The marker a missing gateway leaves in the subprocess's stderr.
_NO_GATEWAY = "No module named 'kiro_crew'"


def _modules() -> list[str]:
    """Dotted names for every ``.py`` file under PACKAGES, sorted."""
    found: list[str] = []
    for package in PACKAGES:
        base = REPO / package
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name.startswith("_"):
                continue
            rel = path.relative_to(REPO).with_suffix("")
            found.append(".".join(rel.parts))
    return found


def _gateway_dirs() -> list[str]:
    """``KIROCREW_SRC`` entries that exist, in order — what conftest appends."""
    raw = os.environ.get("KIROCREW_SRC", "")
    return [p for p in (q.strip() for q in raw.split(":")) if p and Path(p).is_dir()]


def _import_in_subprocess(module: str) -> subprocess.CompletedProcess[str]:
    """Import ``module`` on conftest's path, in a fresh interpreter."""
    prelude = "; ".join(
        [
            "import sys",
            f"sys.path.insert(0, {str(REPO)!r})",
            *(f"sys.path.append({d!r})" for d in _gateway_dirs()),
            f"import {module}",
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", prelude],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_walk_finds_the_modules() -> None:
    """The walk is not vacuously empty, and it reaches every package.

    Without this, deleting a directory or breaking the glob would make every
    assertion below pass over an empty list.
    """
    modules = _modules()
    assert len(modules) >= 20, f"suspiciously few modules found: {modules}"
    for package in PACKAGES:
        prefix = package.replace("/", ".") + "."
        assert any(m.startswith(prefix) for m in modules), f"nothing found under {package}"


@pytest.mark.parametrize("module", _modules())
def test_module_imports(module: str) -> None:
    """``import <module>`` succeeds."""
    if module in RUNS_ON_IMPORT:
        pytest.skip("importing this module runs it; covered by test_fixtures.py")

    result = _import_in_subprocess(module)
    if result.returncode == 0:
        return

    stderr = result.stderr.strip()
    if module in NEEDS_GATEWAY and _NO_GATEWAY in stderr:
        pytest.skip("needs the gateway's kiro_crew on the path")

    pytest.fail(f"import {module} failed:\n{stderr[-2000:]}")
