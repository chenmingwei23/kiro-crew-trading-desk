#!/usr/bin/env python3
"""Member state aggregation for the Trading Desk app (ARCHITECTURE.md §2 GET /org).

aggregate_state(desk_root, members_json_path) returns the /org `members` array:
identity fields come straight from crews/members.json, and state / state_msg /
recent_outputs are read off the desk's artifacts on disk.

State is inferred from files only -- which artifacts exist for today, how many,
and when they were last written. Nothing here reads gateway or agent internals,
so `working` means "this member's artifacts grew recently", never "its session
is running":

  idle     nothing outstanding: today's deliverable is in, or the day has not
           started for this member
  working  partial artifacts for today, last written inside the stall window
  blocked  partial artifacts for today, nothing new for --stall-minutes

Any date before today is history, so every member reads idle for it.

slot_key is passed through from members.json when the crews track has bound
one, else null -- the contract allows null and this never invents a session key.
Line-manager `tickers` and `pod` are filled from sectors.yaml only when
members.json leaves them empty.

Where a member's artifacts live comes from that member's `output_sources`
([{label, dir}], relative to the desk root) when the roster carries it, so the
crews file stays the one place that answers it. FALLBACK_SOURCES covers a
roster without the field.

Requires PyYAML. No other third-party package.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date as _date
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

def _default_desk_root() -> str:
    """``$DESK_ROOT``, else ``~/trading-desk`` — the desk tree is DATA, not code."""
    env = os.environ.get("DESK_ROOT", "").strip()
    return env or str(Path.home() / "trading-desk")


DEFAULT_DESK_ROOT = _default_desk_root()

DEFAULT_STALL_MINUTES = 45
DEFAULT_MAX_OUTPUTS = 3

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

#: Analyst / debate leaf artifacts inside teams/<pod>/reports/<date>/<TICKER>/.
#: Analyst files are <role>-copy-<n>.md for any n, so they match on the infix.
_LEAF_NAMES = frozenset({"bull-thesis.md", "bear-thesis.md",
                         "trade-proposal-initial.md", "risk-aggressive.md",
                         "risk-conservative.md", "risk-neutral.md"})
_LEAF_INFIX = "-copy-"

#: Fallback artifact sources for a roster that carries no `output_sources`:
#: id -> [(directory relative to desk root, output label, state noun)].
#: crews/members.json `output_sources` wins over this whenever it is present.
FALLBACK_SOURCES: dict[str, list[tuple[str, str, str]]] = {
    "fund": [("memory/briefs", "汇报", "汇报")],
    "macro": [("teams/macro/reports", "宏观简报", "宏观简报")],
    "desk": [("memory/briefs", "CEO 汇报", "给 CEO 的汇报"),
             ("teams/desk/reports", "全桌汇总", "全桌汇总")],
    "risk": [("teams/risk-pod/reports", "风控报告", "风控报告")],
    "trader": [],
    "scrum": [],
}

#: How a member's own daily deliverable reads in state_msg, by member id.
STATE_NOUNS: dict[str, str] = {
    "fund": "汇报",
    "macro": "宏观简报",
    "desk": "给 CEO 的汇报",
    "risk": "风控报告",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def resolve_desk_root(explicit: str | None = None) -> Path:
    """CLI flag wins, then $TRADING_DESK_ROOT / $DESK_ROOT, then the contract default."""
    raw = explicit or os.environ.get("TRADING_DESK_ROOT") or os.environ.get(
        "DESK_ROOT") or DEFAULT_DESK_ROOT
    return Path(raw).expanduser()


def load_members(path: str | Path) -> list[dict[str, Any]]:
    """Read crews/members.json. Accepts a bare array or {"members": [...]}.

    '-' reads stdin.
    """
    if str(path) == "-":
        data = json.loads(sys.stdin.read())
    else:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(
                f"members.json not found at {target} -- it is the crews track's "
                "deliverable (ARCHITECTURE.md §4)")
        data = json.loads(target.read_text())
    if isinstance(data, dict):
        data = data.get("members", [])
    if not isinstance(data, list):
        raise ValueError("members.json must be an array, or an object with "
                         "a `members` array")
    return [m for m in data if isinstance(m, dict)]


def load_pods(desk_root: Path) -> dict[str, dict[str, Any]]:
    """sectors.yaml -> {pod: pod_cfg}. Missing or malformed file yields {}."""
    path = desk_root / "sectors.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        print(f"warning: sectors.yaml unreadable ({exc}); ticker lists left "
              "as members.json has them", file=sys.stderr)
        return {}
    sectors = data.get("sectors") if isinstance(data, dict) else None
    return sectors if isinstance(sectors, dict) else {}


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%H:%M")


def _dated_reports(directory: Path) -> list[tuple[str, Path, float]]:
    """(date, path, mtime) for every YYYY-MM-DD*.md file directly in `directory`."""
    if not directory.is_dir():
        return []
    out: list[tuple[str, Path, float]] = []
    for item in directory.iterdir():
        if not item.is_file() or item.suffix != ".md":
            continue
        match = _DATE_RE.match(item.name)
        if match:
            out.append((match.group(1), item, item.stat().st_mtime))
    out.sort(key=lambda row: (row[0], row[2]), reverse=True)
    return out


def _count_leaves(day_dir: Path) -> tuple[int, float]:
    """(leaf artifact count, newest mtime) under teams/<pod>/reports/<date>/."""
    if not day_dir.is_dir():
        return 0, 0.0
    count = 0
    newest = 0.0
    for leaf in day_dir.rglob("*.md"):
        if not leaf.is_file():
            continue
        if leaf.name in _LEAF_NAMES or _LEAF_INFIX in leaf.name:
            count += 1
            newest = max(newest, leaf.stat().st_mtime)
    return count, newest


def _expected_leaves(pod_cfg: dict[str, Any]) -> int:
    """Full pipeline per pod: (4 roles x copies + bull/bear + proposal + risk) x tickers."""
    tickers = pod_cfg.get("tickers")
    n = len(tickers) if isinstance(tickers, list) else 0
    copies = pod_cfg.get("analyst_copies")
    copies = copies if isinstance(copies, int) and copies > 0 else 1
    return n * (4 * copies + 2 + 1 + 3)


def _relative(path: Path, desk_root: Path) -> str:
    try:
        return str(path.relative_to(desk_root))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# state inference
# --------------------------------------------------------------------------- #
def _pod_state(desk_root: Path, pod: str, pod_cfg: dict[str, Any], today: str,
               stall_secs: float, now: float) -> tuple[str, str]:
    reports = desk_root / "teams" / pod / "reports"
    delivered_today = [row for row in _dated_reports(reports) if row[0] == today]
    if delivered_today:
        return "idle", "今天的组报告已交"

    done, newest = _count_leaves(reports / today)
    if not done:
        return "idle", "今天还没开工"

    total = _expected_leaves(pod_cfg)
    progress = f"{done}/{total}" if total else str(done)
    if now - newest > stall_secs:
        return "blocked", f"{progress} 份产出停在 {_hhmm(newest)}，还没出组报告"
    return "working", f"{progress} 份产出已回，正在往下推"


def _ic_state(desk_root: Path, member: dict[str, Any], pod: str,
              pod_cfg: dict[str, Any], today: str) -> tuple[str, str]:
    """One IC's progress on one date, folded from the files that role writes.

    An IC is spawned per ticker per round and holds no session, so file counts
    are its only signal. The roster says which filenames are this role's
    (``artifact_globs``) and how many it owes per ticker (``per_ticker``, absent
    means scale with the pod's ``analyst_copies``) -- the same table
    ``scripts/desk_events.py`` derives the Run page's stages from.

    Three states, as §2 fixes them: a finished IC reads ``idle`` with a state_msg
    that says it delivered, never a fourth state.
    """
    globs = member.get("artifact_globs")
    patterns = [str(g) for g in globs if str(g)] if isinstance(globs, list) else []
    if not patterns:
        return "idle", "尚未开工"

    tickers = pod_cfg.get("tickers")
    n_tickers = len(tickers) if isinstance(tickers, list) else 0
    per_ticker = member.get("per_ticker")
    if isinstance(per_ticker, int) and per_ticker > 0:
        each = per_ticker
    else:
        copies = pod_cfg.get("analyst_copies")
        each = copies if isinstance(copies, int) and copies > 0 else 1
    total = n_tickers * each
    if total <= 0:
        return "idle", "本组今天没有标的"

    day_dir = desk_root / "teams" / pod / "reports" / today
    done = 0
    if day_dir.is_dir():
        for ticker_dir in day_dir.iterdir():
            if not ticker_dir.is_dir():
                continue
            try:
                names = [p.name for p in ticker_dir.iterdir() if p.is_file()]
            except OSError:
                continue
            done += sum(1 for name in names
                        if any(fnmatch(name, p) for p in patterns))

    if done >= total:
        return "idle", f"{done}/{total} 已交"
    if done > 0:
        return "working", f"{done}/{total} 进行中"
    return "idle", f"0/{total} 尚未开工"


def _member_sources(member: dict[str, Any]) -> list[tuple[str, str]]:
    """[(directory relative to desk root, output label)] for one member.

    crews/members.json `output_sources` is authoritative when present, so the
    roster stays the one place that says where a member's artifacts live.
    """
    raw = member.get("output_sources")
    if isinstance(raw, list):
        given = [(str(entry["dir"]), str(entry.get("label") or "产出"))
                 for entry in raw
                 if isinstance(entry, dict) and entry.get("dir")]
        if given:
            return given
    pod = member.get("pod")
    if pod:
        return [(f"teams/{pod}/reports", "组报告")]
    return [(rel_dir, label)
            for rel_dir, label, _ in FALLBACK_SOURCES.get(str(member.get("id")), [])]


def _standing_state(desk_root: Path, member: dict[str, Any], today: str,
                    pods: dict[str, dict[str, Any]], stall_secs: float,
                    now: float) -> tuple[str, str]:
    member_id = str(member.get("id") or "")
    sources = _member_sources(member)

    for rel_dir, _label in sources:
        if any(row[0] == today for row in _dated_reports(desk_root / rel_dir)):
            noun = STATE_NOUNS.get(member_id)
            return "idle", f"今天的{noun}已交" if noun else "今天的产出已交"

    if member_id in ("desk", "fund") and pods:
        rolled = 0
        newest = 0.0
        started = 0
        for pod in pods:
            reports = desk_root / "teams" / pod / "reports"
            for run_date, _path, mtime in _dated_reports(reports):
                if run_date == today:
                    rolled += 1
                    newest = max(newest, mtime)
                    break
            leaves, leaf_newest = _count_leaves(reports / today)
            if leaves:
                started += 1
                newest = max(newest, leaf_newest)
        stalled = newest and (now - newest > stall_secs)
        if rolled:
            tail = (f"最后一份停在 {_hhmm(newest)}" if stalled
                    else "正在等其余的")
            return ("blocked" if stalled else "working",
                    f"{len(pods)} 个组里 {rolled} 个已交，{tail}")
        if started:
            tail = (f"最后一份停在 {_hhmm(newest)}" if stalled
                    else "还没有组报告回来")
            return ("blocked" if stalled else "working",
                    f"{started} 个组在跑，{tail}")

    noun = STATE_NOUNS.get(member_id)
    return "idle", f"今天还没交{noun}" if noun else "今天还没有产出"


def _output_label(base: str, run_date: str, filename: str) -> str:
    """`宏观简报 2026-08-04`, or `… · macro-risk` when the day has several files."""
    stem = Path(filename).stem
    extra = stem[len(run_date):].lstrip("-_ ")
    return f"{base} {run_date} · {extra}" if extra else f"{base} {run_date}"


def _recent_outputs(desk_root: Path, member: dict[str, Any],
                    max_outputs: int) -> list[dict[str, str]]:
    rows: list[tuple[str, float, str, str]] = []
    for rel_dir, label in _member_sources(member):
        for run_date, path, mtime in _dated_reports(desk_root / rel_dir):
            rows.append((run_date, mtime,
                         _output_label(label, run_date, path.name),
                         _relative(path, desk_root)))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [{"label": label, "path": rel}
            for _, _, label, rel in rows[:max_outputs]]


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
def aggregate_state(desk_root: str | Path | None,
                    members_json_path: str | Path,
                    today: str | None = None,
                    stall_minutes: int = DEFAULT_STALL_MINUTES,
                    max_outputs: int = DEFAULT_MAX_OUTPUTS) -> list[dict[str, Any]]:
    """The §2 GET /org `members` array: crews identity + artifact-derived state."""
    root = resolve_desk_root(str(desk_root) if desk_root else None)
    roster = load_members(members_json_path)
    pods = load_pods(root)
    today = today or _date.today().isoformat()
    is_history = today < _date.today().isoformat()
    stall_secs = max(stall_minutes, 0) * 60
    now = time.time()

    out: list[dict[str, Any]] = []
    for member in roster:
        member_id = str(member.get("id") or "")
        pod = member.get("pod") or None
        if not pod and member_id.startswith("lm-"):
            candidate = member_id[len("lm-"):]
            pod = candidate if candidate in pods else None
        is_ic = member_id.startswith("ic-")

        pod_cfg = pods.get(pod, {}) if pod else {}
        # An IC works the whole pod, so its ticker list lives on the line-manager
        # row above it -- §2 reserves `tickers` for the line-manager, and filling
        # it here would repeat the same four symbols on ten children.
        if is_ic:
            tickers = []
        else:
            tickers = member.get("tickers")
            if not tickers and pod:
                raw = pod_cfg.get("tickers")
                tickers = list(raw) if isinstance(raw, list) else []

        if is_history:
            state, state_msg = "idle", f"{today} 是历史记录"
        elif is_ic and pod:
            state, state_msg = _ic_state(root, member, pod, pod_cfg, today)
        elif pod:
            state, state_msg = _pod_state(root, pod, pod_cfg, today, stall_secs, now)
        else:
            state, state_msg = _standing_state(root, {**member, "pod": pod}, today,
                                               pods, stall_secs, now)

        out.append({
            "id": member_id,
            "name": member.get("name"),
            "title": member.get("title"),
            "duty": member.get("duty"),
            "parent": member.get("parent"),
            "group": member.get("group"),
            "pod": pod,
            "tickers": tickers or [],
            "state": state,
            "state_msg": state_msg,
            # An IC is spawned per ticker per round and holds no session, so a
            # key here would point the Chat page at a slot that cannot exist.
            "slot_key": None if is_ic else member.get("slot_key"),
            "recent_outputs": [] if is_ic else _recent_outputs(
                root, {**member, "pod": pod}, max_outputs),
        })
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _valid_date(text: str) -> str:
    try:
        return _date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a YYYY-MM-DD date") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="members.py",
        description="Aggregate the GET /org members array from crews/members.json "
                    "plus the desk's artifacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  members.py --members ../crews/members.json\n"
               "  members.py --members - --date 2026-09-07 < roster.json\n")
    parser.add_argument("--members", required=True, metavar="PATH",
                        help="crews/members.json; - reads stdin")
    parser.add_argument("--desk-root", metavar="PATH",
                        help="desk data root (default: $TRADING_DESK_ROOT, else "
                             f"{DEFAULT_DESK_ROOT})")
    parser.add_argument("--date", type=_valid_date,
                        help="the day to read state for (default: today)")
    parser.add_argument("--stall-minutes", type=int, default=DEFAULT_STALL_MINUTES,
                        help="no new artifact for this long reads as blocked "
                             f"(default: {DEFAULT_STALL_MINUTES})")
    parser.add_argument("--max-outputs", type=int, default=DEFAULT_MAX_OUTPUTS,
                        help=f"recent_outputs per member (default: {DEFAULT_MAX_OUTPUTS})")
    args = parser.parse_args(argv)

    try:
        members = aggregate_state(args.desk_root, args.members, today=args.date,
                                  stall_minutes=args.stall_minutes,
                                  max_outputs=args.max_outputs)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"members": members}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
