"""``/run`` — one morning run as a dispatch chain plus one lane per pod.

Data comes from the best source available, in this order:

1. ``runs/{date}/events.jsonl`` — the structured events a run writes (M1).
2. ``scripts/desk_events.py derive --date`` (scripts track) — derives events from
   artifact mtimes and writes/prints them.
3. Inline synthesis from the artifact tree — the same idea as (2), done here, so
   the Run page still renders before the scripts track lands.

Which one answered is reported as ``source`` so the page never has to guess.
Wording is outward-facing: delivered / in progress / stuck, never a protocol sentinel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from . import deskdata, stages
from .paths import app_root, rel

log = logging.getLogger("kirocrew.app.trading-desk")

_DERIVE_TIMEOUT = 25.0

#: Chain order for members that are not pod line-managers.
_CHAIN_ORDER = ("fund", "macro", "desk", "risk", "trader", "scrum")

_KIND_LABELS = {
    "dispatched": "dispatched",
    "delivered": "delivered",
    "failed": "stuck",
    "note": "progress",
}


# ---------------------------------------------------------------------------
# derive script (source 2)
# ---------------------------------------------------------------------------


def _derive_script() -> Path:
    return app_root() / "scripts" / "desk_events.py"


async def _exec(cmd: list[str], cwd: Path, root: Path) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["TRADING_DESK_ROOT"] = str(root)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DERIVE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "derive timed out"
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


def _events_from_stdout(stdout: str) -> list[dict[str, Any]]:
    """Accept either a JSON array/object of events or one JSON object per line."""
    text = stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        out: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out
    if isinstance(parsed, dict):
        inner = parsed.get("events")
        return [e for e in inner if isinstance(e, dict)] if isinstance(inner, list) else []
    if isinstance(parsed, list):
        return [e for e in parsed if isinstance(e, dict)]
    return []


async def _derive(root: Path, date: str) -> list[dict[str, Any]]:
    """Run the scripts track's derive. Any failure returns no events, never raises."""
    script = _derive_script()
    if not script.is_file():
        return []
    python = sys.executable or "python3"
    base = [python, str(script), "derive", "--date", date]

    code, stdout, stderr = await _exec(base + ["--desk-root", str(root)], script.parent, root)
    if code == 2 and "unrecognized arguments" in stderr:
        # Older signature without --desk-root: it reads the desk root itself.
        code, stdout, stderr = await _exec(base, script.parent, root)
    if code != 0:
        log.info("trading-desk derive exited %s: %s", code, stderr.strip()[:400])

    events = _events_from_stdout(stdout)
    if events:
        return events
    # The script may append to runs/{date}/events.jsonl instead of printing.
    return deskdata.read_events(root, date)


# ---------------------------------------------------------------------------
# folding events into the page shape (sources 1 and 2)
# ---------------------------------------------------------------------------


def _normalize_who(who: str, pods: dict[str, Any]) -> tuple[str | None, str | None]:
    """Split an event's ``who`` into ``(pod, member_id)``."""
    if who in pods:
        return who, f"lm-{who}"
    if who.startswith("lm-") and who[3:] in pods:
        return who[3:], who
    return None, who or None


def _fold(root: Path, date: str, events: list[dict[str, Any]], source: str) -> dict[str, Any]:
    pods = deskdata.pods(root)
    lanes: dict[str, dict[str, Any]] = {}
    chain: dict[str, list[dict[str, Any]]] = {}
    stream: list[dict[str, Any]] = []

    for event in events:
        who = str(event.get("who") or "")
        kind = str(event.get("kind") or "note")
        msg = str(event.get("msg") or "")
        at = deskdata.hhmm(event.get("at"))
        pod, member = _normalize_who(who, pods)

        stream.append(
            {"at": at, "who": who, "msg": msg, "hot": kind in ("failed", "delivered")}
        )

        if pod is not None:
            lane = lanes.setdefault(
                pod,
                {"pod": pod, "state": "work", "stages": [], "delivered_at": None, "fail_reason": None},
            )
            stage = event.get("stage")
            if isinstance(stage, dict) and stage.get("name"):
                name = str(stage["name"])
                existing = next((s for s in lane["stages"] if s["name"] == name), None)
                entry = {
                    "name": name,
                    "done": int(stage.get("done") or 0),
                    "total": int(stage.get("total") or 0),
                }
                if existing is None:
                    lane["stages"].append(entry)
                else:
                    existing.update(entry)
            if kind == "delivered":
                lane["state"] = "done"
                lane["delivered_at"] = at
            elif kind == "failed":
                lane["state"] = "fail"
                lane["fail_reason"] = msg or "no reason given"

        if member:
            steps = chain.setdefault(member, [])
            label = msg or _KIND_LABELS.get(kind, kind)
            if kind == "stage" and isinstance(event.get("stage"), dict):
                stage = event["stage"]
                done = int(stage.get("done") or 0)
                total = int(stage.get("total") or 0)
                label = f"{stage.get('name') or 'progress'} {done}/{total}"
                state = "done" if total and done >= total else "work"
            elif kind == "failed":
                state = "fail"
            else:
                state = "done"
            steps.append({"label": label, "state": state, "at": at})

    ordered_chain = [
        {"member": member, "steps": chain[member]}
        for member in list(_CHAIN_ORDER) + [f"lm-{p}" for p in pods]
        if member in chain
    ]
    ordered_chain += [
        {"member": member, "steps": steps}
        for member, steps in chain.items()
        if member not in {c["member"] for c in ordered_chain}
    ]

    return {
        "date": date,
        "live": date == deskdata.today(),
        "chain": ordered_chain,
        "pods": [
            lanes.get(pod)
            or {
                "pod": pod,
                "state": "not_started",
                "stages": stages.zero_stages(root, pod),
                "delivered_at": None,
                "fail_reason": None,
            }
            for pod in pods
        ]
        + [lane for pod, lane in lanes.items() if pod not in pods],
        "events": stream,
        "source": source,
        "deskRoot": str(root),
    }


# ---------------------------------------------------------------------------
# inline synthesis (source 3)
# ---------------------------------------------------------------------------


def _synth_lane(root: Path, pod: str, date: str, live: bool) -> dict[str, Any]:
    """One pod lane from the artifact tree.

    Every pod gets a lane (CONTRACT §2, cycle1/3). A pod with nothing on disk for
    the date is ``not_started`` and still carries its real denominators at zero
    progress, so the swimlane shows what did NOT happen rather than a blank row.
    """
    leaves = deskdata.leaf_files(root, pod, date)
    rollup = deskdata.rollup_file(root, pod, date)
    if not leaves and rollup is None:
        return {
            "pod": pod,
            "state": "not_started",
            "stages": stages.zero_stages(root, pod),
            "delivered_at": None,
            "fail_reason": None,
        }

    lane_stages = stages.lane_stages(root, pod, date)
    if rollup is not None:
        return {
            "pod": pod,
            "state": "done",
            "stages": lane_stages + [{"name": "pod report", "done": 1, "total": 1}],
            "delivered_at": deskdata.mtime_hhmm(rollup),
            "fail_reason": None,
        }
    return {
        "pod": pod,
        "state": "work" if live else "fail",
        "stages": lane_stages,
        "delivered_at": None,
        "fail_reason": None if live else "pod report not written",
    }


def _synth_step(label: str, path: Path | None, live: bool) -> dict[str, Any]:
    if path is not None:
        return {"label": label, "state": "done", "at": deskdata.mtime_hhmm(path)}
    return {"label": label, "state": "work" if live else "todo", "at": None}


def _synthesize(root: Path, date: str) -> dict[str, Any]:
    live = date == deskdata.today()
    pods = deskdata.pods(root)

    lanes = [_synth_lane(root, pod, date, live) for pod in pods]
    active = [lane for lane in lanes if lane["state"] != "not_started"]

    briefs = deskdata.brief_files(root, date)
    brief = briefs[-1] if briefs else None
    macro = deskdata.rollup_file(root, "macro", date)
    desk = deskdata.rollup_file(root, "desk", date)
    risk = deskdata.rollup_file(root, "risk-pod", date)
    dispatched = bool(active) or macro is not None

    chain: list[dict[str, Any]] = [
        {
            "member": "fund",
            "steps": [
                {
                    "label": "started",
                    "state": "done" if dispatched else ("work" if live else "todo"),
                    "at": None,
                },
                _synth_step("brief received", brief, live),
            ],
        }
    ]
    if macro is not None or live:
        chain.append({"member": "macro", "steps": [_synth_step("macro brief", macro, live)]})
    for lane in active:
        pod = lane["pod"]
        steps = [
            {
                "label": f"{s['name']} {s['done']}/{s['total']}",
                "state": "done" if s["total"] and s["done"] >= s["total"] else "work",
                "at": None,
            }
            for s in lane["stages"]
            if s["name"] != "pod report"
        ]
        steps.append(
            {
                "label": "pod report",
                "state": "done" if lane["state"] == "done" else ("work" if live else "fail"),
                "at": lane["delivered_at"],
            }
        )
        chain.append({"member": f"lm-{pod}", "steps": steps})
    if risk is not None:
        chain.append({"member": "risk", "steps": [_synth_step("risk review", risk, live)]})
    if desk is not None or brief is not None:
        chain.append({"member": "desk", "steps": [_synth_step("desk view", desk or brief, live)]})

    stream: list[dict[str, Any]] = []
    for lane in active:
        if lane["delivered_at"]:
            stream.append(
                {"at": lane["delivered_at"], "who": lane["pod"], "msg": "pod report delivered", "hot": True}
            )
        elif lane["state"] == "fail":
            stream.append(
                {"at": None, "who": lane["pod"], "msg": "pod report not written", "hot": True}
            )
    for label, path in (("macro brief delivered", macro), ("risk review delivered", risk), ("desk view delivered", desk)):
        if path is not None:
            stream.append(
                {"at": deskdata.mtime_hhmm(path), "who": "desk", "msg": label, "hot": False}
            )
    if brief is not None:
        stream.append(
            {
                "at": deskdata.mtime_hhmm(brief),
                "who": "fund",
                "msg": f"brief delivered ({rel(root, brief)})",
                "hot": True,
            }
        )
    stream.sort(key=lambda e: e["at"] or "99:99")

    return {
        "date": date,
        "live": live,
        "chain": chain,
        "pods": lanes,
        "events": stream,
        "source": "synthesized",
        "deskRoot": str(root),
    }


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


async def build(root: Path, date: str) -> dict[str, Any]:
    """Assemble the ``/run`` payload for one date."""
    events = await asyncio.to_thread(deskdata.read_events, root, date)
    if events:
        return await asyncio.to_thread(_fold, root, date, events, "events.jsonl")

    derived = await _derive(root, date)
    if derived:
        return await asyncio.to_thread(_fold, root, date, derived, "desk_events.py")

    return await asyncio.to_thread(_synthesize, root, date)
