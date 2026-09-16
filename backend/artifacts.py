"""``/artifacts`` — the file tree one run produced, grouped the way the desk reads.

Groups are ordered CEO brief → macro → pods (sectors.yaml order) → risk → desk,
and every file carries both a deskRoot-relative ``path`` and the absolute
``abs_path`` the gateway's ``/api/file-read`` needs.

``/file`` serves a file's text directly with the same containment rule the rest of
the backend uses: anything resolving outside deskRoot is refused, symlinks
included.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import deskdata
from .paths import rel, resolve_in_root

#: Rollup label per non-pod team.
_TEAM_LABELS = {
    "macro": "宏观简报",
    "risk-pod": "风控复核",
    "desk": "桌面观点",
}

_MAX_FILE_BYTES = 2_000_000


def _entry(root: Path, path: Path, label: str) -> dict[str, Any]:
    return {"label": label, "path": rel(root, path), "abs_path": str(path)}


def _variant_label(base: str, name: str) -> str:
    """Label a dated variant like ``2026-08-04-macro-risk.md`` as ``macro-risk``."""
    stem = name[:-3] if name.endswith(".md") else name
    suffix = stem[11:].strip("-") if len(stem) > 11 else ""
    return f"{base} · {suffix}" if suffix else base


def _team_group(root: Path, team: str, date: str, rollup_label: str) -> dict[str, Any] | None:
    """One group: the team's rollup files plus any per-ticker leaf reports."""
    files: list[dict[str, Any]] = []

    for path in deskdata.team_reports(root, team, date):
        label = (
            rollup_label
            if path.name == f"{date}.md"
            else _variant_label(rollup_label, path.name)
        )
        files.append(_entry(root, path, label))

    for ticker, paths in deskdata.leaf_files(root, team, date).items():
        for path in paths:
            stem = path.name[:-3] if path.name.endswith(".md") else path.name
            files.append(_entry(root, path, f"{ticker} · {stem}"))

    return {"group": team, "files": files} if files else None


def _group_order(root: Path) -> list[tuple[str, str]]:
    """``(team, rollup_label)`` in reading order."""
    order: list[tuple[str, str]] = [("macro", _TEAM_LABELS["macro"])]
    pods = deskdata.pods(root)
    order += [(pod, "组报告") for pod in pods]
    order += [("risk-pod", _TEAM_LABELS["risk-pod"]), ("desk", _TEAM_LABELS["desk"])]
    # Any team directory the config does not mention still shows its output.
    known = {name for name, _ in order}
    order += [(team, "组报告") for team in deskdata.teams_present(root) if team not in known]
    return order


def build(root: Path, date: str | None) -> dict[str, Any]:
    """Assemble the ``/artifacts`` payload.

    With no date, today is used; when today produced nothing the newest date that
    did is shown instead, so the page never opens empty on a quiet morning. The
    date actually rendered is reported back as ``date``.
    """
    dates = deskdata.available_dates(root)
    target = date or deskdata.today()
    if target not in dates and dates and not date:
        target = dates[0]

    tree: list[dict[str, Any]] = []

    briefs = deskdata.brief_files(root, target)
    if briefs:
        tree.append(
            {
                "group": "CEO 汇报",
                "files": [
                    _entry(root, path, "brief" if path.name == f"{target}.md" else _variant_label("brief", path.name))
                    for path in briefs
                ],
            }
        )

    for team, label in _group_order(root):
        group = _team_group(root, team, target, label)
        if group is not None:
            tree.append(group)

    events = deskdata.events_path(root, target)
    if events.is_file():
        tree.append({"group": "运行事件", "files": [_entry(root, events, "events.jsonl")]})

    return {"dates": dates, "date": target, "tree": tree, "deskRoot": str(root)}


def read_file(root: Path, raw_path: str | None) -> tuple[str, str]:
    """Return ``(text, relative_path)`` for a file inside deskRoot.

    Raises :class:`~backend.paths.OutOfRoot` (403) for a path outside the tree and
    ``FileNotFoundError`` (404) when it does not exist.
    """
    path = resolve_in_root(root, raw_path or "")
    if not path.is_file():
        raise FileNotFoundError(rel(root, path))
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(f"file is larger than {_MAX_FILE_BYTES} bytes")
    return path.read_text(encoding="utf-8", errors="replace"), rel(root, path)
