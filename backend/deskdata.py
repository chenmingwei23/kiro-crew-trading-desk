"""Reads of the desk tree itself — config YAML, run events, artifact files.

Everything here is pure reading, takes an already-resolved deskRoot, and returns
plain data. It is the only place that knows the desk's on-disk layout:

    sectors.yaml                                  pod definitions
    books.yaml                                    capital + account constraints
    runs/{date}/events.jsonl                      structured run events (M1)
    memory/briefs/{date}*.md                      CEO brief
    teams/{team}/reports/{date}*.md               pod / macro / risk rollup
    teams/{pod}/reports/{date}/{TICKER}/*.md      leaf analyst output
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import yaml

#: A leading ``YYYY-MM-DD`` in a file or directory name.
_LEADING_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

#: Non-pod teams that own a rollup file under ``teams/<name>/reports``.
DESK_TEAMS = {"macro": "macro", "desk": "desk", "risk-pod": "risk-pod"}

_MAX_DATES = 90


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML mapping. A missing or unparseable file is an empty mapping."""
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def jsonable(node: Any) -> Any:
    """Make YAML-parsed data JSON-serializable.

    YAML types an unquoted ``2026-06-01`` as a ``datetime.date``, which
    ``json_response`` cannot encode — one such value in books.yaml would 500 the
    whole ``/config`` route. Dates become ISO strings; anything else JSON cannot
    represent becomes its string form rather than an error.
    """
    if isinstance(node, dict):
        return {str(k): jsonable(v) for k, v in node.items()}
    if isinstance(node, (list, tuple, set)):
        return [jsonable(v) for v in node]
    if isinstance(node, (datetime, date, time)):
        return node.isoformat()
    if isinstance(node, (str, int, float, bool)) or node is None:
        return node
    return str(node)


def pods(root: Path) -> dict[str, dict[str, Any]]:
    """Pod definitions from ``sectors.yaml`` (the ``sectors:`` key is the pod map)."""
    data = load_yaml(root / "sectors.yaml").get("sectors")
    if not isinstance(data, dict):
        return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}


def books(root: Path) -> dict[str, Any]:
    return load_yaml(root / "books.yaml")


def tickers_for(root: Path, pod: str) -> list[str]:
    raw = pods(root).get(pod, {}).get("tickers")
    return [str(t) for t in raw] if isinstance(raw, list) else []


def books_holding(root: Path, pod: str) -> list[str]:
    """Book ids whose ``pod_weights`` give this pod a non-zero target."""
    out: list[str] = []
    book_map = books(root).get("books")
    if not isinstance(book_map, dict):
        return out
    for book_id, book in book_map.items():
        weights = book.get("pod_weights") if isinstance(book, dict) else None
        if isinstance(weights, dict):
            try:
                if float(weights.get(pod) or 0) > 0:
                    out.append(str(book_id))
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Run events (M1 structured source)
# ---------------------------------------------------------------------------


def events_path(root: Path, date: str) -> Path:
    return root / "runs" / date / "events.jsonl"


def read_events(root: Path, date: str) -> list[dict[str, Any]]:
    """Parse ``runs/{date}/events.jsonl``. A malformed line is skipped, not fatal.

    Append-only jsonl written by a live run: a torn final line is expected, so a
    parse failure drops that line and keeps every event before it.
    """
    path = events_path(root, date)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def hhmm(value: Any) -> str | None:
    """Render an event timestamp as local ``HH:MM``. Returns None when unusable."""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).strftime("%H:%M")
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text[11:16] if len(text) >= 16 and text[10] in " T" else None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%H:%M")


def mtime_hhmm(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")
    except OSError:
        return None


def mtime_epoch(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def brief_files(root: Path, date: str) -> list[Path]:
    """CEO brief files for a date (``memory/briefs/{date}.md`` and dated variants)."""
    briefs = root / "memory" / "briefs"
    if not briefs.is_dir():
        return []
    try:
        return sorted(p for p in briefs.iterdir() if p.is_file() and p.name.startswith(date))
    except OSError:
        return []


def team_reports(root: Path, team: str, date: str) -> list[Path]:
    """Rollup files for one team on a date — ``{date}.md`` plus dated variants."""
    reports = root / "teams" / team / "reports"
    if not reports.is_dir():
        return []
    try:
        return sorted(
            p for p in reports.iterdir() if p.is_file() and p.name.startswith(date)
        )
    except OSError:
        return []


def rollup_file(root: Path, team: str, date: str) -> Path | None:
    """The canonical ``teams/{team}/reports/{date}.md`` when it exists."""
    candidate = root / "teams" / team / "reports" / f"{date}.md"
    return candidate if candidate.is_file() else None


def leaf_dir(root: Path, pod: str, date: str) -> Path | None:
    candidate = root / "teams" / pod / "reports" / date
    return candidate if candidate.is_dir() else None


def leaf_files(root: Path, pod: str, date: str) -> dict[str, list[Path]]:
    """Per-ticker leaf report files: ``{"AAPL": [bull-thesis.md, ...]}``."""
    base = leaf_dir(root, pod, date)
    if base is None:
        return {}
    out: dict[str, list[Path]] = {}
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return {}
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            files = sorted(p for p in entry.iterdir() if p.is_file())
        except OSError:
            files = []
        out[entry.name] = files
    return out


def teams_present(root: Path) -> list[str]:
    teams = root / "teams"
    if not teams.is_dir():
        return []
    try:
        return sorted(p.name for p in teams.iterdir() if p.is_dir())
    except OSError:
        return []


def available_dates(root: Path) -> list[str]:
    """Dates that have any artifact, newest first (briefs, rollups, leaf dirs, runs)."""
    found: set[str] = set()

    def harvest(directory: Path) -> None:
        try:
            entries = list(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            match = _LEADING_DATE.match(entry.name)
            if match:
                found.add(match.group(1))

    harvest(root / "memory" / "briefs")
    harvest(root / "runs")
    for team in teams_present(root):
        harvest(root / "teams" / team / "reports")

    return sorted(found, reverse=True)[:_MAX_DATES]
