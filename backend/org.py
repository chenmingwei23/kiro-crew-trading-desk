"""``/org`` — who is on the desk, what they do, what they are doing right now.

Three sources are merged, in this precedence:

1. ``crews/members.json`` — identity, the outward-facing duty text, and per-member
   pointers: ``output_sources`` (which desk directories hold this member's output)
   and ``slot_hint`` (WHERE its session lives in the sidebar, not its key). If the
   file is missing or unreadable a minimal built-in table stands in, so the page
   still renders instead of the app looking broken.
2. ``sectors.yaml`` — the live pod list, tickers and book membership, read fresh:
   a ticker moved between pods shows up here without regenerating the roster,
   which is why a line-manager's duty is rendered from ``duty_template``.
3. The gateway's live slots plus today's run events — state, one-line status, and
   the session key the Chat page binds to.

An IC (``ic-<pod>-<role>``) is the exception to source 3: it is spawned per ticker
per round and never holds a session, so its state is counted from the artifacts it
wrote today and its ``slot_key`` stays null.

Duty text is an outward-facing job description; orchestration internals never
belong in it.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from . import deskdata
from .paths import app_config, app_root, rel
from .slots import SlotView

#: Non-pod members, in the org chart's reading order. Fallback only — the roster
#: file owns this copy when it is present.
_CORE_MEMBERS: tuple[dict[str, Any], ...] = (
    {
        "id": "fund",
        "name": "fund-manager",
        "title": "Fund Manager",
        "parent": None,
        "duty": "Runs the desk's day-to-day operations, breaking the day's intent into research and allocation actions, and owns the final conclusion.",
        "output_sources": [{"label": "Yesterday's brief", "dir": "memory/briefs"}],
    },
    {
        "id": "macro",
        "name": "macro-strategist",
        "title": "Macro Strategist",
        "parent": "fund",
        "duty": "Each day, calls the macro and market-environment view first, framing the risk appetite and main themes for each pod's stock picking.",
        "output_sources": [{"label": "Latest macro brief", "dir": "teams/macro/reports"}],
    },
    {
        "id": "desk",
        "name": "desk-manager",
        "title": "Desk Manager",
        "parent": "fund",
        "duty_template": "Coordinates research across {pod_count} pods, rolling each pod's conclusions into one executable desk view.",
        "duty": "Rolls each pod's conclusions into one executable desk view, resolving conflicts and priorities across pods.",
        "output_sources": [{"label": "Latest desk view", "dir": "teams/desk/reports"}],
    },
    {
        "id": "risk",
        "name": "risk-pod",
        "title": "Risk Pod",
        "parent": "fund",
        "duty": "Independently reviews every proposal's exposure, sizing and stops — the last gate before an order goes out.",
        "output_sources": [{"label": "Latest risk review", "dir": "teams/risk-pod/reports"}],
    },
    {
        "id": "trader",
        "name": "trader",
        "title": "Trader",
        "parent": "fund",
        "duty": "Turns reviewed views into concrete plans: ticker, direction, size, timing.",
    },
    {
        "id": "scrum",
        "name": "scrum-master",
        "title": "Scrum Master",
        "parent": "fund",
        "duty": "Keeps the desk's rhythm, watching the day's progress and blockers so what is due gets delivered on time.",
    },
)

#: Roster fields beyond CONTRACT §2 that the Desk page's hero card needs
#: (§4 cycle1). §2 fixes the MEMBER shape, so these ship as a sibling map keyed by
#: member id rather than inline — members.json is their only source and the UI has
#: no other way to reach it.
_PROFILE_FIELDS = ("alias", "avatar_letter", "reports_label", "agent")

_MAX_OUTPUTS = 3


def _members_file() -> Path:
    return app_root() / "crews" / "members.json"


def _declared_members() -> list[dict[str, Any]]:
    """``crews/members.json`` as a list. Absent or malformed reads as empty."""
    parsed = deskdata.read_json(_members_file())
    if isinstance(parsed, dict):
        parsed = parsed.get("members")
    if not isinstance(parsed, list):
        return []
    return [m for m in parsed if isinstance(m, dict) and m.get("id")]


def _fallback_members(root: Path) -> list[dict[str, Any]]:
    """Built-in minimum: the six core roles plus one line-manager per pod."""
    out = [dict(m) for m in _CORE_MEMBERS]
    for pod in deskdata.pods(root):
        out.append(
            {
                "id": f"lm-{pod}",
                "name": f"line-manager · {pod}",
                "title": "Line Manager",
                "parent": "desk",
                "pod": pod,
                "duty_template": "Runs the {pod} pod ({tickers}): converges the pod's conclusions into one pod report.",
                "output_sources": [{"label": "Latest pod report", "dir": f"teams/{pod}/reports"}],
            }
        )
    return out


def _group_label(root: Path, pod: str) -> str:
    """A pod row's group label: its book, then the pod.

    Carries NO word for "pod". `crews/gen_members.py` builds the same label the
    same way for a stored roster, and the UI appends the reader's own noun
    (`groupLabel` in `ui/i18n.mjs`); a noun baked in here would survive the
    language switch and strand an English word inside a Chinese row.
    """
    held = deskdata.books_holding(root, pod)
    if not held:
        return str(pod)
    return "+".join(held) + f" · {pod}"


def _duty(member: dict[str, Any], pod: str | None, tickers: list[str], pod_count: int) -> str:
    """Render ``duty_template`` against live config; fall back to the snapshot.

    The template exists because a line-manager's duty text names its pod and
    tickers — a ticker moved in sectors.yaml would leave the stored ``duty``
    silently wrong.
    """
    template = member.get("duty_template")
    snapshot = str(member.get("duty") or "")
    if not isinstance(template, str) or not template:
        return snapshot
    try:
        return template.format(
            pod=pod or "", tickers=" ".join(tickers), pod_count=pod_count
        )
    except (KeyError, IndexError, ValueError):
        return snapshot


def _resolve_slot(
    member: dict[str, Any], overrides: dict[str, Any], view: SlotView
) -> tuple[str | None, bool, bool]:
    """``(slot_key, exists, running)`` for this member.

    An explicit key in ``data/config.json``'s ``slots`` map wins; otherwise the
    roster's ``slot_hint`` is looked up by folder + title, then by a title that is
    unique on its own. No match leaves the key null, which CONTRACT §2 defines as
    "session not created yet".
    """
    override = overrides.get(str(member.get("id")))
    if isinstance(override, str) and override.strip():
        key = override.strip()
        found = view.by_key(key)
        # An explicit binding is honoured even before its session exists, so the
        # Chat page can create it on first message.
        return key, found is not None, bool(found and found.get("running"))

    hint = member.get("slot_hint")
    if isinstance(hint, str) and hint.strip():  # tolerate a bare key in the roster
        key = hint.strip()
        found = view.by_key(key)
        return key, found is not None, bool(found and found.get("running"))
    if not isinstance(hint, dict):
        return None, False, False

    title = str(hint.get("title") or "")
    folder = str(hint.get("folder") or "")
    if not title:
        return None, False, False

    found = view.by_folder_and_title(folder, title) if folder else None
    if found is None:
        found = view.by_unique_title(title)
    if found is None:
        return None, False, False
    return str(found.get("key") or "") or None, True, bool(found.get("running"))


def _member_events(
    events: list[dict[str, Any]], member_id: str, pod: str | None
) -> list[dict[str, Any]]:
    """Events addressed to this member, by member id or by the pod it runs."""
    ids = {member_id} | ({str(pod)} if pod else set())
    return [e for e in events if str(e.get("who") or "") in ids]


def _state_from(
    mine: list[dict[str, Any]], running: bool, exists: bool, bound: bool
) -> tuple[str, str]:
    """Resolve ``(state, state_msg)``.

    Three states only (CONTRACT §2, cycle1): a member that has delivered reads as
    ``idle`` with a state_msg that says so, rather than a fourth state.

    The last three lines are three different situations that must not share one
    sentence. A member holding a key whose session the embed has not created yet
    (straight after a reset, or a fresh binding) is NOT "not started" — saying so on
    the Desk page contradicts the chat the user just opened.
    """
    failed = [e for e in mine if e.get("kind") == "failed"]
    if failed:
        return "blocked", str(failed[-1].get("msg") or "stuck, needs a look")
    if running:
        latest = mine[-1].get("msg") if mine else None
        return "working", str(latest or "working on today's tasks")
    delivered = [e for e in mine if e.get("kind") == "delivered"]
    if delivered:
        return "idle", str(delivered[-1].get("msg") or "today's work is delivered")
    if mine:
        return "working", str(mine[-1].get("msg") or "the work in hand isn't wrapped up yet")
    if exists:
        return "idle", "on station"
    if bound:
        return "idle", "a new session is ready, waiting for your first message"
    return "idle", "not started"


#: An IC's ten roles all write into ``teams/<pod>/reports/<date>/<TICKER>/``. The
#: roster says which filenames are that role's (``artifact_globs``) and how many
#: it owes per ticker (``per_ticker``, null = scale with the pod's analyst_copies).
#: Counting files is the only signal an IC has: it is spawned per ticker per round
#: and never holds a session, so slot state cannot answer for it.
def _ic_progress(root: Path, member: dict[str, Any], pod: str, date: str) -> tuple[int, int] | None:
    """``(done, total)`` for one IC on one date, or None when the roster is silent."""
    globs = member.get("artifact_globs")
    if not isinstance(globs, list) or not globs:
        return None
    patterns = [str(g) for g in globs if str(g)]
    if not patterns:
        return None

    tickers = deskdata.tickers_for(root, pod)
    per_ticker = member.get("per_ticker")
    if isinstance(per_ticker, int) and per_ticker > 0:
        each = per_ticker
    else:
        raw = deskdata.pods(root).get(pod, {}).get("analyst_copies")
        each = raw if isinstance(raw, int) and raw > 0 else 1
    total = len(tickers) * each

    names = [
        path.name
        for paths in deskdata.leaf_files(root, pod, date).values()
        for path in paths
    ]
    done = sum(1 for name in names if any(fnmatch(name, p) for p in patterns))
    return done, total


def _ic_state(done: int, total: int) -> tuple[str, str]:
    """Three states, same vocabulary the rest of the page uses.

    A finished IC reads ``idle`` with a state_msg that says it delivered, rather
    than a fourth state -- §2's cycle1 adjudication applies here too.
    """
    if total <= 0:
        return "idle", "no tickers for this pod today"
    if done >= total:
        return "idle", f"{done}/{total} delivered"
    if done > 0:
        return "working", f"{done}/{total} in progress"
    return "idle", f"0/{total} not started"


def _newest_files(directory: Path, limit: int) -> list[Path]:
    """Newest files in one directory, by leading date then mtime."""
    if not directory.is_dir():
        return []
    try:
        files = [p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []
    files.sort(key=lambda p: (p.name[:10], deskdata.mtime_epoch(p)), reverse=True)
    return files[:limit]


def _recent_outputs(root: Path, member: dict[str, Any]) -> list[dict[str, Any]]:
    """Newest files from each declared ``output_sources`` directory.

    The roster declares directories rather than files because every filename
    carries its own date. A directory outside deskRoot is skipped, not followed.
    """
    sources = member.get("output_sources")
    if not isinstance(sources, list):
        return []
    out: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw_dir = str(source.get("dir") or "").strip()
        if not raw_dir:
            continue
        directory = (root / raw_dir).resolve()
        try:
            if not directory.is_relative_to(root):
                continue
        except (OSError, ValueError):
            continue
        label = str(source.get("label") or "output")
        for path in _newest_files(directory, _MAX_OUTPUTS):
            stem_date = path.name[:10] if len(path.name) >= 10 else ""
            out.append(
                {
                    "label": f"{label} {stem_date}".strip(),
                    "path": rel(root, path),
                    "abs_path": str(path),
                }
            )
    return out[:_MAX_OUTPUTS]


def roster(root: Path) -> list[dict[str, Any]]:
    """The member list ``/org`` renders — the roster file, or the built-in fallback.

    Shared with the reset route so "is this a member?" is answered by exactly the
    same source the Desk page draws, and a 404 can never disagree with the page.
    """
    return _declared_members() or _fallback_members(root)


def find_member(root: Path, member_id: str) -> dict[str, Any] | None:
    return next((m for m in roster(root) if str(m.get("id")) == member_id), None)


def current_slot_key(
    root: Path, ctx: Any, view: SlotView, member_id: str
) -> str | None:
    """The key this member is bound to right now, by ``/org``'s own resolution."""
    member = find_member(root, member_id)
    if member is None:
        return None
    overrides = app_config(ctx).get("slots")
    overrides = overrides if isinstance(overrides, dict) else {}
    key, _exists, _running = _resolve_slot(member, overrides, view)
    return key


def build(
    root: Path,
    ctx: Any,
    view: SlotView | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``/org`` payload from the roster, live config and one snapshot."""
    slot_view = view or SlotView()
    run_date = date or deskdata.today()
    events = deskdata.read_events(root, run_date)
    overrides = app_config(ctx).get("slots")
    overrides = overrides if isinstance(overrides, dict) else {}

    declared = _declared_members()
    members_in = declared or _fallback_members(root)
    known_pods = deskdata.pods(root)
    pod_count = len(known_pods)

    out: list[dict[str, Any]] = []
    profiles: dict[str, dict[str, Any]] = {}
    for raw in members_in:
        member_id = str(raw.get("id"))
        pod = raw.get("pod") or (member_id[3:] if member_id.startswith("lm-") else None)
        pod = str(pod) if pod else None
        is_ic = member_id.startswith("ic-")

        # An IC works every ticker in its pod, so the list belongs on the
        # line-manager row above it -- repeating it on ten children says nothing
        # new, and §2 reserves `tickers` for the line-manager.
        if is_ic:
            tickers = []
        elif pod and pod in known_pods:
            tickers = deskdata.tickers_for(root, pod)
        else:
            declared_tickers = raw.get("tickers")
            tickers = [str(t) for t in declared_tickers] if isinstance(declared_tickers, list) else []

        group = raw.get("group") or (_group_label(root, pod) if pod else None)

        # An IC has no session: its progress is folded from the files it wrote,
        # and slot_key stays null so the Chat page never offers a session that
        # cannot exist. Falling through to _resolve_slot would match the pod's
        # line-manager by unique title and bind ten rows to one chat.
        progress = _ic_progress(root, raw, pod, run_date) if (is_ic and pod) else None
        if progress is not None:
            key, running = None, False
            state, state_msg = _ic_state(*progress)
        else:
            key, exists, running = _resolve_slot(raw, overrides, slot_view)
            mine = _member_events(events, member_id, pod)
            state, state_msg = _state_from(mine, running, exists, key is not None)

        entry: dict[str, Any] = {
            "id": member_id,
            "name": str(raw.get("name") or member_id),
            "title": str(raw.get("title") or member_id),
            "duty": _duty(raw, pod, tickers, pod_count),
            "parent": raw.get("parent") or None,
            "group": group or None,
            "pod": pod,
            "tickers": tickers,
            "state": state,
            "state_msg": state_msg,
            "slot_key": key,
            # §2 cycle2: whether the bound session is currently RUNNING. Whether it
            # exists at all is already carried by slot_key (§3 keys the "not started"
            # placeholder off a null key).
            "slot_live": running,
            "recent_outputs": _recent_outputs(root, raw),
        }
        out.append(entry)

        profile = {f: raw[f] for f in _PROFILE_FIELDS if raw.get(f) is not None}
        if profile:
            profiles[member_id] = profile

    return {
        "members": out,
        "profiles": profiles,
        "deskRoot": str(root),
        "source": "crews/members.json" if declared else "fallback",
    }
