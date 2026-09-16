#!/usr/bin/env python3
"""Regenerate fixtures/ from a desk tree on disk.

Every JSON in this directory is DERIVED, not hand-written: paths, stage counts
and dates are read off the desk rather than asserted, so the fixtures cannot
quietly drift from the shape a real run produces. Edit this script and re-run it;
never hand-edit the JSON.

The desk this reads is the DEMO desk, not anyone's real one. Produce it with the
seeder, then point this script at it:

    python3 scripts/seed_demo_desk.py "$KIROCREW_SCRATCH/demo-desk"
    DESK_ROOT="$KIROCREW_SCRATCH/demo-desk" python3 fixtures/gen_fixtures.py

The seeder writes an entirely fictional desk (shipped example config, placeholder
artifacts), which is what keeps these committed fixtures free of real positions,
research, paths and session keys. ``DESK_ROOT`` selects the desk; there is no
default worth relying on for a public checkout, so always set it.

Output is deterministic: timestamps are derived from ``RUN_DATE`` rather than file
mtimes, so a re-run on an unchanged desk produces byte-identical files and a clean
``git status`` is the check that a change was intentional. The schemas are the
ones ``tests/schema.py`` enforces; this script reads the desk read-only and writes
only into this directory.
"""
from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import json
import os
from pathlib import Path

import yaml


def _json_default(o: object):
    # books.yaml may carry a `hard_expiry_date`, which PyYAML parses to a
    # datetime.date. Render it as an ISO string -- GET /config must do the same.
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


DESK = Path(os.environ.get("DESK_ROOT") or str(Path.home() / "trading-desk"))
OUT = Path(__file__).resolve().parent
RUN_DATE = "2026-09-07"

OUT.mkdir(parents=True, exist_ok=True)


def _iso(clock: str) -> str:
    """A deterministic ISO-8601 UTC instant on RUN_DATE at ``HH:MM``.

    Derived from RUN_DATE, never from a file mtime, so re-seeding the demo desk
    does not change a byte of the fixtures.
    """
    return f"{RUN_DATE}T{clock}:00Z"


def dump(name: str, obj: object) -> None:
    path = OUT / name
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path.name} ({path.stat().st_size} bytes)")


# ---------------------------------------------------------------- config.json
books = yaml.safe_load((DESK / "books.yaml").read_text(encoding="utf-8"))
sectors = yaml.safe_load((DESK / "sectors.yaml").read_text(encoding="utf-8"))

# A desk-root sectors.yaml carries a line_manager per pod (the schema for GET
# /config requires it). The seeder writes one; default it defensively so this
# script also works against a hand-made desk that left it out.
for _cfg in sectors["sectors"].values():
    if isinstance(_cfg, dict):
        _cfg.setdefault("line_manager", "line-manager")

dump(
    "config.json",
    {
        "books": books,
        "sectors": sectors,
        "constraints": books["account_constraints"],
    },
)

POD_TICKERS = {pod: cfg.get("tickers", []) for pod, cfg in sectors["sectors"].items()}
PODS = list(POD_TICKERS)


# ------------------------------------------------------------------- org.json
def rel_exists(rel: str) -> bool:
    return (DESK / rel).exists()


def outputs(*pairs: tuple[str, str]) -> list[dict]:
    """Keep only recent_outputs whose file actually exists under deskRoot."""
    return [{"label": label, "path": rel} for label, rel in pairs if rel_exists(rel)]


#: Synthetic session keys, out of the live key space on purpose: the ``chat-9xxx``
#: prefix exists in no real session, so a fixture key can never open somebody's
#: actual conversation. Every committed key follows this shape.
STAFF = [
    {
        "id": "fund",
        "name": "fund-manager",
        "title": "Fund Manager",
        "duty": (
            "Runs the desk day to day: takes an instruction, arranges the macro "
            "brief and each pod's research, follows it to completion, and returns "
            "one short report plus anything that needs a decision."
        ),
        "parent": None,
        "state": "working",
        "state_msg": "Folding the pods' conclusions into today's report",
        "slot_key": "chat-9101-1000000001",
        "recent_outputs": outputs(("Latest brief", f"memory/briefs/{RUN_DATE}.md")),
    },
    {
        "id": "macro",
        "name": "macro-strategist",
        "title": "Macro Strategist",
        "duty": (
            "Calls the market environment before the open and suggests each pod's "
            "posture across index, volatility, rates, gold and oil -- never a "
            "single name."
        ),
        "parent": "fund",
        "state": "idle",
        "state_msg": "Today's macro brief is in",
        "slot_key": "chat-9102-1000000002",
        "recent_outputs": outputs(("Today's macro brief", f"teams/macro/reports/{RUN_DATE}.md")),
    },
    {
        "id": "desk",
        "name": "desk-manager",
        "title": "Desk Manager",
        "duty": (
            "Runs research across the sector pods, tracks their progress, and folds "
            "their conclusions into a one-page brief ranked by conviction and payoff."
        ),
        "parent": "fund",
        "state": "working",
        "state_msg": "Both pods in; writing the one-page brief",
        "slot_key": "chat-9103-1000000003",
        "recent_outputs": outputs(("Latest brief", f"memory/briefs/{RUN_DATE}.md")),
    },
    {
        "id": "risk",
        "name": "risk-pod",
        "title": "Portfolio Risk",
        "duty": (
            "Portfolio-level risk: measures exposure, concentration and tail risk "
            "from the pods' conclusions and the live book, and flags what needs a "
            "hedge. Flags risk; never recommends a trade."
        ),
        "parent": "fund",
        "state": "idle",
        "state_msg": "Waiting on the pods before starting",
        "slot_key": None,
        "recent_outputs": outputs(("Positions", "portfolio/positions.md")),
    },
    {
        "id": "trader",
        "name": "trader",
        "title": "Trader",
        "duty": "Places the orders once they are approved.",
        "parent": "fund",
        "state": "idle",
        "state_msg": "No orders to place",
        "slot_key": None,
        "recent_outputs": outputs(("Fills", "portfolio/trades.jsonl")),
    },
    {
        "id": "scrum",
        "name": "scrum-master",
        "title": "Scrum Master",
        "duty": (
            "Runs the standup and the post-close review, and keeps the team's "
            "delivery cadence honest."
        ),
        "parent": "fund",
        "state": "idle",
        "state_msg": "Standup notes are out",
        "slot_key": None,
        "recent_outputs": [],
    },
]

for m in STAFF:
    m.setdefault("group", None)
    m.setdefault("pod", None)
    m.setdefault("tickers", [])

members = list(STAFF)
for pod, tickers in POD_TICKERS.items():
    rollup = f"teams/{pod}/reports/{RUN_DATE}.md"
    members.append(
        {
            "id": f"lm-{pod}",
            "name": f"line-manager · {pod}",
            "title": "Line Manager",
            "duty": (
                f"Owns the {pod} pod ({' '.join(tickers)}): has the analysts "
                "research each name, chairs the bull and bear debate and the risk "
                "review, and delivers the pod's conclusion on every ticker."
            ),
            "parent": "desk",
            "group": f"Core · {pod}",
            "pod": pod,
            "tickers": tickers,
            "state": "idle",
            "state_msg": "Pod conclusion delivered",
            "slot_key": None,
            "recent_outputs": outputs(("Latest pod report", rollup)),
        }
    )

# `slot_live` (OPTIONAL, §2): whether the bound session is currently running.
# Derived, never asserted: a member is live exactly when it has a bound slot AND
# is working at the snapshot moment.
for m in members:
    m["slot_live"] = bool(m["slot_key"]) and m["state"] == "working"

dump("org.json", {"members": members})


# --------------------------------------------------------- run-<date>.json
# Stage counts are COUNTED off the artifact tree, not asserted.
ANALYST_ROLES = ("technicals", "fundamentals", "sentiment", "news")
N_ROLES = len(ANALYST_ROLES)
N_RISK_DEBATERS = 3


def _pod_dir(pod: str) -> Path:
    return DESK / "teams" / pod / "reports" / RUN_DATE


def count(pod: str, prefixes: tuple[str, ...]) -> int:
    n = 0
    pdir = _pod_dir(pod)
    if pdir.is_dir():
        for tdir in sorted(p for p in pdir.iterdir() if p.is_dir()):
            for f in tdir.glob("*.md"):
                if f.stem.startswith(prefixes):
                    n += 1
    return n


def pod_counts(pod: str) -> dict[str, int]:
    return {
        "analyst": count(pod, ANALYST_ROLES),
        "debate": count(pod, ("bull-thesis", "bear-thesis")),
        "proposal": count(pod, ("trade-proposal",)),
        "risk": count(pod, ("risk-",)),
    }


def planned_stages(pod: str, done: dict[str, int] | None = None) -> list[dict]:
    """Stage rows for a pod. Totals come from sectors.yaml, so a pod that never
    started still carries the denominators a progress bar needs."""
    cfg = sectors["sectors"][pod]
    n_t = len(cfg.get("tickers", []))
    copies = int(cfg.get("analyst_copies", 1) or 1)
    d = done or {}
    return [
        {"name": "analysis", "done": d.get("analyst", 0), "total": n_t * N_ROLES * copies},
        {"name": "debate", "done": d.get("debate", 0), "total": n_t * 2},
        {"name": "proposal", "done": d.get("proposal", 0), "total": n_t},
        {"name": "risk review", "done": d.get("risk", 0), "total": n_t * N_RISK_DEBATERS},
        {"name": "pod report", "done": 1 if done else 0, "total": 1},
    ]


# Self-check: the stage-total formula must reproduce each pod's COUNTED artifacts,
# otherwise a not-started pod would carry denominators no real run agrees with.
for _pod in PODS:
    _counted = pod_counts(_pod)
    _totals = [s["total"] for s in planned_stages(_pod)]
    _expected = [_counted["analyst"], _counted["debate"], _counted["proposal"], _counted["risk"], 1]
    if _totals != _expected:
        raise SystemExit(
            f"stage-total formula disagrees with counted artifacts for {_pod}: "
            f"formula={_totals} counted={_expected}"
        )

lead_pod = PODS[0]
run = {
    "date": RUN_DATE,
    "live": False,
    "chain": [
        {
            "member": "fund",
            "steps": [
                {"label": "Instruction received", "state": "done", "at": "09:00"},
                {"label": "Macro brief ordered", "state": "done", "at": "09:02"},
                {"label": "Pods dispatched", "state": "done", "at": "09:05"},
                {"label": "Desk report folded", "state": "work", "at": None},
            ],
        },
        {
            "member": "macro",
            "steps": [
                {"label": "Instruction received", "state": "done", "at": "09:00"},
                {"label": "Macro brief delivered", "state": "done", "at": "09:02"},
            ],
        },
        {
            "member": "desk",
            "steps": [
                {"label": "Research instruction received", "state": "done", "at": "09:04"},
                {"label": "Pods started", "state": "done", "at": "09:05"},
                {"label": "Pod reports collected", "state": "done", "at": "09:40"},
                {"label": "One-page brief", "state": "work", "at": None},
            ],
        },
        {
            "member": f"lm-{lead_pod}",
            "steps": [
                {"label": "Analysts researched", "state": "done", "at": "09:20"},
                {"label": "Bull and bear debate", "state": "done", "at": "09:28"},
                {"label": "Trade proposals", "state": "done", "at": "09:32"},
                {"label": "Risk review", "state": "done", "at": "09:38"},
                {"label": "Pod conclusion", "state": "done", "at": "09:40"},
            ],
        },
        {
            "member": "risk",
            "steps": [
                {"label": "Awaiting pod conclusions", "state": "todo", "at": None},
            ],
        },
    ],
    "pods": [
        {
            "pod": pod,
            "state": "done",
            "stages": planned_stages(pod, pod_counts(pod)),
            "delivered_at": "09:40",
            "fail_reason": None,
        }
        for pod in PODS
    ],
    "events": [
        {"at": "09:00", "who": "fund", "msg": "Instruction received; scheduling today's research", "hot": False},
        {"at": "09:02", "who": "macro", "msg": "Macro brief delivered: neutral environment, no posture change", "hot": True},
        {"at": "09:05", "who": "desk", "msg": f"Pods dispatched: {', '.join(PODS)}", "hot": False},
        {"at": "09:40", "who": "desk", "msg": "All pods delivered their conclusions", "hot": False},
    ],
}
dump(f"run-{RUN_DATE}.json", run)
# Date-agnostic fallback. ui/index.mjs probes ['run-<date>.json', 'run.json'], so
# a Run page asking for any other date lands here instead of empty-handed. Written
# from the SAME dict, not copied, so the two cannot drift apart on a re-run.
dump("run.json", run)


# ------------------------------------------------------------- artifacts.json
TICKER_LABELS = [
    ("technicals-copy-1", "Technicals"),
    ("technicals-copy-2", "Technicals 2"),
    ("fundamentals-copy-1", "Fundamentals"),
    ("fundamentals-copy-2", "Fundamentals 2"),
    ("sentiment-copy-1", "Sentiment"),
    ("sentiment-copy-2", "Sentiment 2"),
    ("news-copy-1", "News"),
    ("news-copy-2", "News 2"),
    ("bull-thesis", "Bull thesis"),
    ("bear-thesis", "Bear thesis"),
    ("trade-proposal-initial", "Trade proposal"),
    ("risk-aggressive", "Risk review · aggressive"),
    ("risk-conservative", "Risk review · conservative"),
    ("risk-neutral", "Risk review · neutral"),
]
LABEL_BY_STEM = dict(TICKER_LABELS)
ORDER = {stem: i for i, (stem, _) in enumerate(TICKER_LABELS)}

tree: list[dict] = []

ceo_files = outputs(("Desk brief", f"memory/briefs/{RUN_DATE}.md"))
if ceo_files:
    tree.append({"group": "Desk brief", "files": ceo_files})

macro_files = outputs(("Today's macro brief", f"teams/macro/reports/{RUN_DATE}.md"))
if macro_files:
    tree.append({"group": "Macro", "files": macro_files})

for pod in PODS:
    pod_files = outputs(("Pod report", f"teams/{pod}/reports/{RUN_DATE}.md"))
    pdir = _pod_dir(pod)
    if pdir.is_dir():
        for tdir in sorted(p for p in pdir.iterdir() if p.is_dir()):
            for f in sorted(tdir.glob("*.md"), key=lambda p: ORDER.get(p.stem, 99)):
                label = LABEL_BY_STEM.get(f.stem, f.stem)
                pod_files.append(
                    {
                        "label": f"{tdir.name} · {label}",
                        "path": str(f.relative_to(DESK)),
                    }
                )
    if pod_files:
        tree.append({"group": pod, "files": pod_files})

# Dates that actually carry a dated daily artifact (brief or team report).
dates: set[str] = set()
for base in [DESK / "memory/briefs"] + sorted((DESK / "teams").glob("*/reports")):
    for f in base.glob("*.md"):
        stem = f.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            dates.add(stem)
for base in sorted((DESK / "teams").glob("*/reports")):
    for d in base.iterdir():
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-":
            dates.add(d.name)

dump("artifacts.json", {"dates": sorted(dates, reverse=True), "tree": tree})


# --------------------------------------------------------------- threads.json
# §11: a thread is a SESSION the conductor opened, carried by `kind`, `member`,
# `slot_key` and `agent`. The panel renders the session's own live transcript via
# /api/chat/slots/{slot_key}; the contents are not in these files.
#
# `slot_key` is DELIBERATELY out of the live key space (`chat-900x-*`), so a ui dev
# clicking a stub thread cannot open a real session. Two kinds ship, because the UI
# labels them differently:
#   th-fund-<date>-1  kind=thread    fund's own clone (agent tada-fund-manager)
#   th-fund-<date>-2  kind=dispatch  desk-manager's session (agent tada-desk-manager)
#   th-fund-<date>-3  kind=thread    a folder-only thread the conversation never mentions
FIXTURE_SLOTS = {
    "clone": "chat-9001-1757260800",
    "dispatch": "chat-9002-1757260800",
    "folder_only": "chat-9003-1757264400",
}

# §13.2: a thread hangs under the USER message that triggered the turn it was
# opened in. `main_msg` is that message's id (deterministic, derived from its
# text), `ts` is what the UI matches a rendered row on, and `preview` is its first
# 60 characters. All three are stubs -- the demo run leaves no main-conversation
# transcript to read -- and the ts sits five minutes before the first artifact.
CEO_INSTRUCTION = "Research the megacap pod, focus on demand and supply"
ANCHOR = {
    "main_msg": "m-" + _hashlib.md5(CEO_INSTRUCTION.encode()).hexdigest()[:16],
    "ts": _iso("08:55"),
    "preview": CEO_INSTRUCTION[:60],
}

clone_thread = {
    "id": f"th-fund-{RUN_DATE}-1",
    "kind": "thread",
    "title": "Megacap deep dive",
    "member": "fund",
    "state": "running",
    "opened_at": _iso("09:06"),
    "participants": ["fund"],
    "last_msg": "One more pass with macro on the supply question",
    "entry_count": 6,
    "last_ts": _iso("09:38"),
    "anchor": dict(ANCHOR),
    "slot_key": FIXTURE_SLOTS["clone"],
    "agent": "tada-fund-manager",
    "refs": {"run_date": RUN_DATE, "artifacts": []},
}

dispatch_thread = {
    "id": f"th-fund-{RUN_DATE}-2",
    "kind": "dispatch",
    "title": "desk-manager",
    "member": "desk",
    "state": "done",
    "opened_at": _iso("09:05"),
    "participants": ["fund", "desk"],
    "last_msg": "Both pods' conclusions are in; desk view written",
    "entry_count": 4,
    "last_ts": _iso("09:40"),
    "anchor": dict(ANCHOR),
    "slot_key": FIXTURE_SLOTS["dispatch"],
    "agent": "tada-desk-manager",
    "refs": {"run_date": RUN_DATE, "artifacts": []},
}

# §11.6: a thread the conversation does NOT mention -- found in the member's
# `threads` folder instead, so it has no message to hang under (anchor is null).
folder_thread = {
    "id": f"th-fund-{RUN_DATE}-3",
    "kind": "thread",
    "title": "Prior-round position review",
    "member": "fund",
    "state": "done",
    "opened_at": _iso("09:07"),
    "participants": ["fund"],
    "last_msg": "Review notes saved to memory",
    "entry_count": 9,
    "last_ts": _iso("09:10"),
    "anchor": None,
    "slot_key": FIXTURE_SLOTS["folder_only"],
    "agent": "tada-fund-manager",
    "refs": {"run_date": RUN_DATE, "artifacts": []},
}

dump("threads.json", {"threads": [clone_thread, dispatch_thread, folder_thread]})


# ---------------------------------------------------------- thread-detail.json
# §11.2: the detail is the listing's first entry, re-derived and picked by id, so
# it is byte-for-byte that object -- list and detail cannot drift.
dump("thread-detail.json", dict(clone_thread))

_totals_by_pod = {pod: pod_counts(pod) for pod in PODS}
print("\ncounts per pod:")
for _pod, _c in _totals_by_pod.items():
    total_md = _c["analyst"] + _c["debate"] + _c["proposal"] + _c["risk"]
    print(f"  {_pod}: analyst={_c['analyst']} debate={_c['debate']} "
          f"proposal={_c['proposal']} risk={_c['risk']} total_md={total_md}")
