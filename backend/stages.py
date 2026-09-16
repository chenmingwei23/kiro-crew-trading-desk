"""Pod stage progress — one stage vocabulary for the whole app.

``scripts/desk_events.py`` owns the pipeline's stage names, the filename globs
that mark each stage done, and the denominator formula (``n_tickers × 4 roles ×
analyst_copies`` for the analyst stage). Restating that table here would drift
from the derive the Run page actually shows, so it is LOADED from that module by
file path — which works the same under the gateway's app loader and under pytest,
where relative imports cannot reach a sibling top-level package.

A local copy of the same table stands in when the scripts module is absent, so
the inline fallback still produces real denominators.
"""
from __future__ import annotations

import importlib.util
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from . import deskdata
from .paths import app_root

#: Mirrors ``desk_events.STAGES`` — (name, globs, per-ticker count or None for
#: "4 analyst roles × analyst_copies"). Used only when that module is missing.
_FALLBACK_STAGES: tuple[tuple[str, tuple[str, ...], int | None], ...] = (
    (
        "Analysis",
        ("technicals-copy-*.md", "fundamentals-copy-*.md",
         "sentiment-copy-*.md", "news-copy-*.md"),
        None,
    ),
    ("Debate", ("bull-thesis.md", "bear-thesis.md"), 2),
    ("Proposal", ("trade-proposal-initial.md",), 1),
    ("Risk", ("risk-aggressive.md", "risk-conservative.md", "risk-neutral.md"), 3),
)

_ANALYST_ROLES = 4
_cached: tuple[tuple[str, tuple[str, ...], int | None], ...] | None = None


def _load_stages() -> tuple[tuple[str, tuple[str, ...], int | None], ...]:
    """``desk_events.STAGES``, or the local mirror when that module is unavailable."""
    global _cached
    if _cached is not None:
        return _cached

    _cached = _FALLBACK_STAGES
    script = app_root() / "scripts" / "desk_events.py"
    if not script.is_file():
        return _cached
    try:
        spec = importlib.util.spec_from_file_location(
            "_trading_desk_stage_table", str(script)
        )
        if spec is None or spec.loader is None:
            return _cached
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stages = getattr(module, "STAGES", None)
        if isinstance(stages, tuple) and stages:
            _cached = stages
    except Exception:  # noqa: BLE001 — a sibling's import must not break the page
        pass
    return _cached


def _analyst_copies(root: Path, pod: str) -> int:
    raw = deskdata.pods(root).get(pod, {}).get("analyst_copies")
    return raw if isinstance(raw, int) and raw > 0 else 1


def _total(per_ticker: int | None, n_tickers: int, copies: int) -> int:
    return n_tickers * (_ANALYST_ROLES * copies if per_ticker is None else per_ticker)


def lane_stages(root: Path, pod: str, date: str) -> list[dict[str, Any]]:
    """Stage progress for one pod on one date — real denominators, file-counted ``done``.

    Counts leaf FILES the way the derive does, so a pod's numbers read the same
    whether the events log answered or this fallback did. A pod that has produced
    nothing still gets every stage at ``0/total``, which is what makes an idle
    lane legible instead of blank.
    """
    stages = _load_stages()
    tickers = deskdata.tickers_for(root, pod)
    n_tickers = len(tickers)
    copies = _analyst_copies(root, pod)
    files = [p.name for paths in deskdata.leaf_files(root, pod, date).values() for p in paths]

    out: list[dict[str, Any]] = []
    for name, globs, per_ticker in stages:
        done = sum(1 for filename in files if any(fnmatch(filename, g) for g in globs))
        out.append({"name": name, "done": done, "total": _total(per_ticker, n_tickers, copies)})
    return out


def zero_stages(root: Path, pod: str) -> list[dict[str, Any]]:
    """Every stage at ``0/total`` — a pod that has not started the day."""
    stages = _load_stages()
    n_tickers = len(deskdata.tickers_for(root, pod))
    copies = _analyst_copies(root, pod)
    return [
        {"name": name, "done": 0, "total": _total(per_ticker, n_tickers, copies)}
        for name, _, per_ticker in stages
    ]
