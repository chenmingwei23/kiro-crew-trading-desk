"""``/config`` — read the desk's capital and pod configuration, validate, write back.

Validation runs the desk's OWN validator (``engine/validate_config.py``) rather
than a second copy of its rules. That script resolves its inputs from its own
location (``DESK = <script>/../``), so a candidate is checked by copying the
script into a throwaway directory next to the candidate YAML: the real validator,
real rules, nothing written inside deskRoot until apply.

Apply preserves comments when ``ruamel.yaml`` is importable — books.yaml and
sectors.yaml carry the rationale for nearly every number, and a plain dict dump
would delete all of it. Without ruamel it falls back to a plain dump, and the
previous file is always backed up into the app's data dir first.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import deskdata, yamledit
from .paths import atomic_write_text

log = logging.getLogger("kirocrew.app.trading-desk")

_VALIDATE_TIMEOUT = 30.0
_FILES = ("books", "sectors")


class ConfigError(Exception):
    """A caller-supplied config body is unusable. Handlers turn this into 400."""


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def read(root: Path) -> dict[str, Any]:
    """``/config`` payload — parsed books and sectors plus the constraints block.

    Coerced through :func:`deskdata.jsonable` because YAML types an unquoted date
    (``hard_expiry_date: 2026-06-01``) as ``datetime.date``, which JSON cannot
    encode.
    """
    books = deskdata.books(root)
    sectors = deskdata.load_yaml(root / "sectors.yaml")
    return {
        "books": deskdata.jsonable(books),
        "sectors": deskdata.jsonable(sectors),
        "constraints": deskdata.jsonable(books.get("account_constraints") or {}),
        "deskRoot": str(root),
    }


# ---------------------------------------------------------------------------
# body normalisation
# ---------------------------------------------------------------------------


def _as_yaml_text(value: Any, name: str) -> tuple[str, dict[str, Any]]:
    """Return ``(yaml_text, parsed)`` for one config value.

    A string is taken verbatim (so a UI that round-trips raw YAML keeps its
    comments); a mapping is dumped. Either way the text is parsed back, so a
    broken YAML string is rejected here instead of reaching the desk.
    """
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        text = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)
    else:
        raise ConfigError(f"{name} must be a mapping or a YAML string")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{name}: YAML parse error — {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"{name}: expected a YAML mapping at the top level")
    return text, parsed


def normalize(body: Any) -> dict[str, tuple[str, dict[str, Any]]]:
    """Validate the request body shape and normalise both files."""
    if not isinstance(body, dict):
        raise ConfigError("body must be a JSON object with books and sectors")
    missing = [name for name in _FILES if body.get(name) is None]
    if missing:
        raise ConfigError(f"body is missing: {', '.join(missing)}")
    return {name: _as_yaml_text(body[name], name) for name in _FILES}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def _parse_report(stderr: str) -> tuple[list[str], list[str]]:
    """Split the validator's bullet output into (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    bucket: list[str] | None = None
    for line in stderr.splitlines():
        stripped = line.strip()
        if "ERROR(S)" in stripped:
            bucket = errors
            continue
        if "WARNING(S)" in stripped:
            bucket = warnings
            continue
        if stripped.startswith("•") and bucket is not None:
            bucket.append(stripped.lstrip("• ").strip())
    return errors, warnings


def _diff(root: Path, candidates: dict[str, tuple[str, dict[str, Any]]]) -> str:
    """Unified diff of the on-disk YAML against the candidate, both files."""
    chunks: list[str] = []
    for name, (text, _) in candidates.items():
        path = root / f"{name}.yaml"
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = ""
        chunks.extend(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{name}.yaml",
                tofile=f"b/{name}.yaml",
            )
        )
    return "".join(chunks)


def _validator(root: Path) -> Path:
    return root / "engine" / "validate_config.py"


async def validate(root: Path, body: Any) -> dict[str, Any]:
    """Run the desk's validator against a candidate config. Writes nothing."""
    candidates = normalize(body)
    diff = await asyncio.to_thread(_diff, root, candidates)

    script = _validator(root)
    if not script.is_file():
        return {
            "ok": False,
            "errors": [f"validator not found at {script}"],
            "warnings": [],
            "diff": diff,
        }

    with tempfile.TemporaryDirectory(prefix="trading-desk-validate-") as tmp:
        sandbox = Path(tmp)
        (sandbox / "engine").mkdir()
        # A COPY, not a symlink: the validator resolves its desk root from
        # __file__, and resolve() would follow a symlink straight back to the
        # real desk — validating the live files instead of the candidate.
        await asyncio.to_thread(shutil.copy2, script, sandbox / "engine" / "validate_config.py")
        for name, (text, _) in candidates.items():
            await asyncio.to_thread(
                (sandbox / f"{name}.yaml").write_text, text, encoding="utf-8"
            )

        python = sys.executable or "python3"
        proc = await asyncio.create_subprocess_exec(
            python,
            str(sandbox / "engine" / "validate_config.py"),
            cwd=str(sandbox),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, raw_err = await asyncio.wait_for(proc.communicate(), timeout=_VALIDATE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "errors": ["validator timed out"], "warnings": [], "diff": diff}

    errors, warnings = _parse_report(raw_err.decode("utf-8", "replace"))
    if proc.returncode == 1 and not errors:
        errors = ["validator reported failure without detail"]
    return {"ok": not errors, "errors": errors, "warnings": warnings, "diff": diff}


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    """Replace ``path`` in one step (shared writer — see ``paths``)."""
    atomic_write_text(path, text)


def _render(
    path: Path, parsed: dict[str, Any], fallback_text: str, verbatim: bool
) -> tuple[str, bool]:
    """Text to write for one file, and whether its comments were preserved.

    Three paths, best first: a body that arrived as raw YAML text is written
    verbatim; a mapping is spliced into the existing file so comments survive; and
    if the change is structural (a key added or removed, a reshaped value) it falls
    back to a plain dump, reported as ``comments_preserved: false`` so the caller
    can say so instead of losing the rationale silently.
    """
    if verbatim:
        return fallback_text, True
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return fallback_text, False
    try:
        old = deskdata.jsonable(yaml.safe_load(current) or {})
        return yamledit.patch(current, old, deskdata.jsonable(parsed)), True
    except (yamledit.Unsupported, yaml.YAMLError) as exc:
        log.info("trading-desk config splice fell back to a dump: %s", exc)
        return fallback_text, False


def _backup(data_dir: Path | None, root: Path) -> str | None:
    """Copy both YAMLs into the app's data dir before they are replaced.

    Returned to the caller so a save that could not keep its comments still has a
    named way back.
    """
    if data_dir is None:
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = Path(data_dir) / "config-backups" / stamp
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in _FILES:
            source = root / f"{name}.yaml"
            if source.is_file():
                shutil.copy2(source, target / f"{name}.yaml")
    except OSError:
        return None  # a missing backup must not block a validated write
    return str(target)


async def apply(root: Path, body: Any, data_dir: Path | None) -> tuple[dict[str, Any], int]:
    """Validate then write both YAMLs. Returns ``(payload, http_status)``."""
    report = await validate(root, body)
    if not report["ok"]:
        return {
            "ok": False,
            "errors": report["errors"],
            "warnings": report["warnings"],
            "diff": report["diff"],
        }, 400

    candidates = normalize(body)
    backup = await asyncio.to_thread(_backup, data_dir, root)

    written: list[str] = []
    preserved = True
    for name, (text, parsed) in candidates.items():
        path = root / f"{name}.yaml"
        verbatim = isinstance((body or {}).get(name), str)
        rendered, kept = await asyncio.to_thread(_render, path, parsed, text, verbatim)
        await asyncio.to_thread(_atomic_write, path, rendered)
        written.append(f"{name}.yaml")
        preserved = preserved and kept

    return {
        "ok": True,
        "written": written,
        "warnings": report["warnings"],
        "comments_preserved": preserved,
        "backup": backup,
    }, 200
