#!/usr/bin/env python3
"""Run-event synthesis and append for the Trading Desk app (ARCHITECTURE.md §2 /run, §4).

Two subcommands:

  derive --date YYYY-MM-DD [--desk-root PATH] [--write]
      Fold the desk's on-disk artifacts for one run date into the §4 event
      schema. Evidence is file mtime + file count only:
        teams/<pod>/reports/<date>/<TICKER>/*.md   -> per-stage progress
        teams/<pod>/reports/<date>*.md             -> pod report delivered
        teams/macro|desk|risk-pod/reports/<date>*.md -> that member delivered
        memory/briefs/<date>*.md                   -> desk manager's CEO brief
      Writes jsonl to stdout; --write also appends to runs/<date>/events.jsonl.

  append --run-date --who --kind --msg [--stage-name --stage-done --stage-total]
      Append ONE event to runs/<run-date>/events.jsonl as a single O_APPEND
      write under an exclusive lock.

Nothing here guesses agent or gateway internal state: an artifact that is not
on disk produces no event. Stage totals come from sectors.yaml
(n_tickers x 4 roles x analyst_copies for the analyst stage).

--write is idempotent. An event already in the file -- same run_date, who,
kind, stage name, stage counts and msg -- is skipped, so re-deriving an
unchanged run appends nothing. A stage whose counts advanced is a NEW event
and is appended, which is how progress history accumulates.

Requires PyYAML. No other third-party package.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import date as _date
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

import yaml

def _default_desk_root() -> str:
    """``$DESK_ROOT``, else ``~/trading-desk`` — the desk tree is DATA, not code."""
    env = os.environ.get("DESK_ROOT", "").strip()
    return env or str(Path.home() / "trading-desk")


DEFAULT_DESK_ROOT = _default_desk_root()

#: §4 event kinds. Anything else is refused.
KINDS = ("dispatched", "stage", "delivered", "failed", "note")

#: Pipeline stages inside one pod, in run order.
#: (stage name, filename globs, per-ticker count or None = 4 roles x analyst_copies)
STAGES: tuple[tuple[str, tuple[str, ...], int | None], ...] = (
    ("分析", ("technicals-copy-*.md", "fundamentals-copy-*.md",
              "sentiment-copy-*.md", "news-copy-*.md"), None),
    ("多空", ("bull-thesis.md", "bear-thesis.md"), 2),
    ("提案", ("trade-proposal-initial.md",), 1),
    ("风控", ("risk-aggressive.md", "risk-conservative.md", "risk-neutral.md"), 3),
)

#: Non-pod members that own a reports/ directory, and how their delivery reads.
STANDING_MEMBERS: tuple[tuple[str, str, str], ...] = (
    ("macro", "teams/macro/reports", "宏观简报已交"),
    ("desk", "teams/desk/reports", "全桌汇总已交"),
    ("risk", "teams/risk-pod/reports", "风控报告已交"),
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def resolve_desk_root(explicit: str | None) -> Path:
    """CLI flag wins, then $TRADING_DESK_ROOT / $DESK_ROOT, then the contract default."""
    raw = explicit or os.environ.get("TRADING_DESK_ROOT") or os.environ.get(
        "DESK_ROOT") or DEFAULT_DESK_ROOT
    return Path(raw).expanduser()


def _iso(ts: float) -> str:
    """mtime -> local-offset ISO 8601, second precision."""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _event(run_date: str, who: str, kind: str, msg: str, at: str,
           stage: dict[str, Any] | None = None) -> dict[str, Any]:
    ev: dict[str, Any] = {"at": at, "run_date": run_date, "who": who,
                          "kind": kind, "msg": msg}
    if stage is not None:
        ev["stage"] = stage
    return ev


def event_identity(ev: dict[str, Any]) -> tuple:
    """Dedupe key: everything the contract carries except the timestamp.

    Excluding `at` means a touched-but-unchanged artifact does not append a
    duplicate; including the stage counts means real progress does.
    """
    stage = ev.get("stage") or {}
    return (ev.get("run_date"), ev.get("who"), ev.get("kind"),
            stage.get("name"), stage.get("done"), stage.get("total"),
            ev.get("msg"))


def load_sectors(desk_root: Path) -> dict[str, dict[str, Any]]:
    """sectors.yaml -> {pod: pod_cfg}. Missing or malformed file yields {}."""
    path = desk_root / "sectors.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        print(f"warning: sectors.yaml unreadable ({exc}); stage totals unknown",
              file=sys.stderr)
        return {}
    sectors = data.get("sectors") if isinstance(data, dict) else None
    return sectors if isinstance(sectors, dict) else {}


def _dated_files(directory: Path, run_date: str) -> list[Path]:
    """Files directly in `directory` whose name starts with the run date."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob(f"{run_date}*")
                  if p.is_file() and p.suffix == ".md")


def _stage_of(filename: str) -> str | None:
    for name, globs, _ in STAGES:
        if any(fnmatch(filename, g) for g in globs):
            return name
    return None


def _stage_total(stage_name: str, n_tickers: int, analyst_copies: int) -> int:
    for name, _, per_ticker in STAGES:
        if name == stage_name:
            return n_tickers * (4 * analyst_copies if per_ticker is None
                                else per_ticker)
    return 0


# --------------------------------------------------------------------------- #
# derive
# --------------------------------------------------------------------------- #
def derive_pod_events(desk_root: Path, run_date: str, pod: str,
                      pod_cfg: dict[str, Any], is_past: bool) -> list[dict[str, Any]]:
    reports_dir = desk_root / "teams" / pod / "reports"
    day_dir = reports_dir / run_date

    tickers = pod_cfg.get("tickers") or []
    n_tickers = len(tickers) if isinstance(tickers, list) else 0
    copies = pod_cfg.get("analyst_copies")
    copies = copies if isinstance(copies, int) and copies > 0 else 1

    # bucket leaf artifacts by stage
    buckets: dict[str, list[float]] = {name: [] for name, _, _ in STAGES}
    if day_dir.is_dir():
        for leaf in day_dir.rglob("*.md"):
            if not leaf.is_file():
                continue
            stage = _stage_of(leaf.name)
            if stage is not None:
                buckets[stage].append(leaf.stat().st_mtime)

    events: list[dict[str, Any]] = []
    all_mtimes = [m for times in buckets.values() for m in times]
    if all_mtimes:
        events.append(_event(
            run_date, pod, "dispatched",
            f"开工，{n_tickers} 只票分下去了" if n_tickers else "开工",
            _iso(min(all_mtimes))))

    for name, _, _ in STAGES:
        times = buckets[name]
        if not times:
            continue
        done = len(times)
        total = _stage_total(name, n_tickers, copies) or done
        events.append(_event(
            run_date, pod, "stage", f"{name} {done}/{total} 份已回",
            _iso(max(times)),
            stage={"name": name, "done": done, "total": total}))

    rollups = _dated_files(reports_dir, run_date)
    if rollups:
        events.append(_event(run_date, pod, "delivered", "组报告已交",
                             _iso(max(p.stat().st_mtime for p in rollups))))
    elif all_mtimes and is_past:
        # Settled fact only for a finished day: work landed, no pod report did.
        events.append(_event(run_date, pod, "note", "当天没有出组报告",
                             _iso(max(all_mtimes))))
    return events


def derive_events(desk_root: Path, run_date: str,
                  today: str | None = None) -> list[dict[str, Any]]:
    """Fold one run date's artifacts into §4 events, sorted by time."""
    today = today or _date.today().isoformat()
    is_past = run_date < today

    events: list[dict[str, Any]] = []
    for pod, pod_cfg in load_sectors(desk_root).items():
        if isinstance(pod_cfg, dict):
            events.extend(derive_pod_events(desk_root, run_date, pod, pod_cfg,
                                            is_past))

    for who, rel_dir, msg in STANDING_MEMBERS:
        files = _dated_files(desk_root / rel_dir, run_date)
        if files:
            events.append(_event(run_date, who, "delivered", msg,
                                 _iso(max(p.stat().st_mtime for p in files))))

    briefs = _dated_files(desk_root / "memory" / "briefs", run_date)
    if briefs:
        events.append(_event(run_date, "desk", "delivered", "CEO 汇报已写好",
                             _iso(max(p.stat().st_mtime for p in briefs))))

    events.sort(key=lambda e: (e["at"], e["who"], e["kind"], e["msg"]))
    return events


# --------------------------------------------------------------------------- #
# jsonl store
# --------------------------------------------------------------------------- #
def events_path(desk_root: Path, run_date: str) -> Path:
    return desk_root / "runs" / run_date / "events.jsonl"


def read_events(desk_root: Path, run_date: str) -> list[dict[str, Any]]:
    """Existing events for a run date; unparsable lines are skipped."""
    path = events_path(desk_root, run_date)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
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


def _open_locked(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _existing_identities(fd: int) -> set[tuple]:
    with os.fdopen(os.dup(fd), "r", encoding="utf-8") as handle:
        handle.seek(0)
        seen = set()
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                seen.add(event_identity(parsed))
        return seen


def append_events(desk_root: Path, run_date: str,
                  events: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """Append events that are not already present. Returns (appended, skipped)."""
    path = events_path(desk_root, run_date)
    fd = _open_locked(path)
    appended = skipped = 0
    try:
        seen = _existing_identities(fd)
        for ev in events:
            identity = event_identity(ev)
            if identity in seen:
                skipped += 1
                continue
            payload = json.dumps(ev, ensure_ascii=False) + "\n"
            os.write(fd, payload.encode("utf-8"))
            seen.add(identity)
            appended += 1
        if appended:
            os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return appended, skipped


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _valid_date(text: str) -> str:
    try:
        return _date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a YYYY-MM-DD date") from None


def cmd_derive(args: argparse.Namespace) -> int:
    desk_root = resolve_desk_root(args.desk_root)
    if not desk_root.is_dir():
        print(f"error: desk root not found: {desk_root}", file=sys.stderr)
        return 2

    events = derive_events(desk_root, args.date)
    if not args.quiet:
        for ev in events:
            print(json.dumps(ev, ensure_ascii=False))

    if args.write:
        appended, skipped = append_events(desk_root, args.date, events)
        print(f"{events_path(desk_root, args.date)}: "
              f"{appended} appended, {skipped} already present", file=sys.stderr)
    elif not events:
        print(f"no artifacts found for {args.date} under {desk_root}",
              file=sys.stderr)
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    desk_root = resolve_desk_root(args.desk_root)
    stage = None
    if args.stage_name is not None:
        if args.stage_done is None or args.stage_total is None:
            print("error: --stage-name requires --stage-done and --stage-total",
                  file=sys.stderr)
            return 2
        stage = {"name": args.stage_name, "done": args.stage_done,
                 "total": args.stage_total}

    ev = _event(args.run_date, args.who, args.kind, args.msg,
                args.at or datetime.now().astimezone().isoformat(timespec="seconds"),
                stage=stage)
    appended, skipped = append_events(desk_root, args.run_date, [ev])
    print(json.dumps(ev, ensure_ascii=False))
    if not appended:
        print("identical event already present; nothing appended",
              file=sys.stderr)
        return 0
    print(f"appended to {events_path(desk_root, args.run_date)}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desk_events.py",
        description="Derive and append trading-desk run events "
                    "(runs/<date>/events.jsonl).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  desk_events.py derive --date 2026-09-07\n"
               "  desk_events.py derive --date 2026-09-07 --write --quiet\n"
               "  desk_events.py append --run-date 2026-09-07 --who example-megacap "
               "--kind delivered --msg '组报告已交'\n")
    sub = parser.add_subparsers(dest="command", required=True)

    root_help = ("desk data root (default: $TRADING_DESK_ROOT, else "
                 f"{DEFAULT_DESK_ROOT})")

    derive = sub.add_parser("derive", help="synthesize events from artifacts")
    derive.add_argument("--date", required=True, type=_valid_date,
                        help="run date, YYYY-MM-DD")
    derive.add_argument("--desk-root", metavar="PATH", help=root_help)
    derive.add_argument("--write", action="store_true",
                        help="also append to runs/<date>/events.jsonl (idempotent)")
    derive.add_argument("--quiet", action="store_true",
                        help="suppress the jsonl on stdout")
    derive.set_defaults(func=cmd_derive)

    append = sub.add_parser("append", help="append one event atomically")
    append.add_argument("--run-date", required=True, type=_valid_date,
                        help="run date the event belongs to")
    append.add_argument("--who", required=True,
                        help="member id or pod name")
    append.add_argument("--kind", required=True, choices=KINDS)
    append.add_argument("--msg", required=True, help="one plain-language line")
    append.add_argument("--stage-name", help="stage label, e.g. 分析")
    append.add_argument("--stage-done", type=int, help="stage items finished")
    append.add_argument("--stage-total", type=int, help="stage items expected")
    append.add_argument("--at", help="ISO timestamp (default: now)")
    append.add_argument("--desk-root", metavar="PATH", help=root_help)
    append.set_defaults(func=cmd_append)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
