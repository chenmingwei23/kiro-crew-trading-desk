"""Desk-root resolution and path containment for the Trading Desk backend.

Every filesystem read this backend performs is anchored at ``deskRoot``. It is
resolved in this order, first hit wins:

1. ``deskRoot`` in the app's own ``data/config.json`` (written by the self-heal
   cron, so an installed copy pins the tree it was set up against).
2. the ``DESK_ROOT`` environment variable.
3. ``~/trading-desk``.

Anything resolving outside that tree is refused — both sides are ``resolve()``d
before comparison, so a symlink inside the tree that points out of it is caught
too.

The desk root is DATA, not part of this repository: it holds positions, research
reports and account configuration. Nothing here may hardcode one person's copy of
it.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


def _default_desk_root() -> str:
    """``$DESK_ROOT``, else ``~/trading-desk``.

    Read through a function rather than frozen into a module constant so a test
    (and a caller that sets the variable after import) sees the current value.
    """
    env = os.environ.get("DESK_ROOT", "").strip()
    if env:
        return env
    return str(Path.home() / "trading-desk")


#: Used when ``data/config.json`` is missing or carries no ``deskRoot``. Kept as a
#: module attribute because callers and tests read it by name; it is the resolved
#: default at import time, and ``_default_desk_root()`` is the live answer.
DEFAULT_DESK_ROOT = _default_desk_root()

#: Dates are path segments (``runs/{date}``, ``teams/{pod}/reports/{date}``), so
#: they are validated as data before they ever reach the filesystem.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OutOfRoot(Exception):
    """A requested path resolves outside deskRoot. Handlers turn this into 403."""


class BadInput(Exception):
    """A query parameter is malformed. Handlers turn this into 400."""


def app_root() -> Path:
    """This app's own root — the parent of ``backend/``.

    Works both in the source repo and in the installed copy under
    ``<KIROCREW_HOME>/apps/trading-desk``, so sibling tracks' files
    (``crews/members.json``, ``scripts/desk_events.py``) are found either way.
    """
    return Path(__file__).resolve().parent.parent


def app_config(ctx: Any) -> dict[str, Any]:
    """Read ``data/config.json``. A missing or corrupt file is an empty config."""
    data_dir = getattr(ctx, "data_dir", None)
    if data_dir is None:
        return {}
    try:
        raw = (Path(data_dir) / "config.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def desk_root(ctx: Any) -> Path:
    """Absolute, resolved deskRoot. Resolution does not require the path to exist."""
    configured = app_config(ctx).get("deskRoot")
    raw = str(configured) if configured else _default_desk_root()
    return Path(raw).expanduser().resolve()


def within(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` resolves inside ``root``."""
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def resolve_in_root(root: Path, raw: str) -> Path:
    """Resolve a caller-supplied path against deskRoot, or raise :class:`OutOfRoot`.

    Accepts both an absolute path under deskRoot and a path relative to it, which
    is what the API emits (``path`` relative, ``abs_path`` absolute).
    """
    if not raw or not raw.strip():
        raise OutOfRoot("path is required")
    text = raw.strip()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if not within(root, candidate):
        raise OutOfRoot("path is outside the desk root")
    return candidate.resolve()


def rel(root: Path, path: Path) -> str:
    """deskRoot-relative form of ``path``, falling back to the absolute string."""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path)


def valid_date(value: str | None) -> bool:
    """True for a zero-padded ``YYYY-MM-DD`` literal."""
    return bool(value) and bool(_DATE_RE.match(value or ""))


def atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` in one step, keeping its existing permission bits.

    A reader either sees the whole previous file or the whole new one — never a
    half-written config. The mode is carried over rather than defaulted, so an
    operator's tightened permissions survive the write.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
