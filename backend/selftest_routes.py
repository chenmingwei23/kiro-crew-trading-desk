"""Dispatch-level checks for the trading-desk backend.

The handler-level self-test cannot see ROUTING: it calls handlers directly, which
is exactly why the gateway shadowing ``/config`` went unnoticed until the ui track
found it. This harness builds a real aiohttp router with the gateway's own static
app routes AND the RouteRegistry catch-all, in the gateway's registration order,
then asks the router which handler actually wins — and drives
``POST /member/{id}/reset`` through the registry so the ``{id}`` path parameter is
matched by the real pattern matcher.

Nothing here is imported by ``backend.routes`` — it is a standalone script, run
with an interpreter that has ``kiro_crew`` and ``aiohttp`` importable (the
gateway's own venv):

    <gateway venv>/bin/python backend/selftest_routes.py

It writes only to a fresh temp dir and reads the desk tree; it never touches the
live gateway, the installed app's config, or the desk's YAML.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

#: This app's root — derived from this file, so the harness runs from the repo or
#: from the installed copy without editing.
APP = Path(__file__).resolve().parent.parent
DESK = str(Path(os.environ.get("DESK_ROOT") or Path.home() / "trading-desk"))

#: The installed shape this harness imitates. Only their SURVIVAL through reset is
#: asserted -- nothing reads them -- so they are synthetic on purpose: a literal
#: home layout would make the assertions hold on one machine and fail elsewhere.
INSTALLED_APP_ROOT = "/opt/kirocrew/apps/trading-desk"
INSTALLED_STATE_PATH = "/opt/kirocrew/workspace/trading-desk/state.json"

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import make_mocked_request  # noqa: E402

from kiro_crew.apps.context import AppContext  # noqa: E402
from kiro_crew.apps.route_registry import AppRoute, RouteRegistry  # noqa: E402
from kiro_crew.apps.routes import register_app_routes  # noqa: E402

sys.path.insert(0, str(APP))
from backend.routes import register_routes  # noqa: E402

FAILURES: list[str] = []
KEY_RE = re.compile(r"^td-([a-z0-9-]+)-(\d{10,})$")


def check(label: str, condition: bool, detail=None) -> None:
    detail = "" if detail is None else str(detail)
    print(f"{'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


class StubSlot:
    """Just enough of a _ChatSlot for the injection path."""

    def __init__(self, key: str, running: bool, sink: list) -> None:
        self.key, self.running, self._sink = key, running, sink

    def enqueue_or_run_prompt(self, prompt, _runner, _state) -> bool:
        # Record instead of starting a real turn; the queue-vs-run decision itself
        # is the gateway's and is not this harness's to re-test.
        self._sink.append((self.key, prompt))
        return True


class StubState:
    """Stands in for DashboardState's reads plus get_slot for delivery."""

    def __init__(self, slots, folders, live_keys=()) -> None:
        self._s, self._f = slots, folders
        self._live = set(live_keys)
        self.delivered: list = []

    def serialize_slots(self, **_kw):
        return list(self._s)

    async def read_folders(self, read):
        return read(list(self._f))

    def get_slot(self, key):
        if key not in self._live:
            return None
        running = next((s.get("running") for s in self._s if s.get("key") == key), False)
        return StubSlot(key, bool(running), self.delivered)

    def push_slots_update(self) -> None:
        return None


async def body_of(response):
    try:
        return json.loads((response.body or b"").decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return (response.body or b"").decode(errors="replace")


def sentinel_payload():
    """An empty request body — what a GET carries."""
    from aiohttp.payload import PAYLOAD_REGISTRY  # noqa: F401,PLC0415 (import guard)
    from aiohttp.streams import EMPTY_PAYLOAD  # noqa: PLC0415

    return EMPTY_PAYLOAD


def _json_payload(obj):
    """A real readable body, so ``await request.json()`` runs the real decode."""
    from unittest import mock  # noqa: PLC0415

    from aiohttp.streams import StreamReader  # noqa: PLC0415

    raw = json.dumps(obj).encode()
    stream = StreamReader(mock.Mock(_reading_paused=False), limit=len(raw) + 1024)
    stream.feed_data(raw)
    stream.feed_eof()
    return stream


async def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="td-dispatch-")) / "data"
    data_dir.mkdir(parents=True)
    config_file = data_dir / "config.json"
    # The live installed shape — reset must carry every one of these forward.
    config_file.write_text(json.dumps({
        "deskRoot": DESK,
        "appRoot": INSTALLED_APP_ROOT,
        "statePath": INSTALLED_STATE_PATH,
    }, indent=2) + "\n")
    config_file.chmod(0o600)  # an operator-tightened mode must survive the write
    ctx = AppContext(name="trading-desk", data_dir=data_dir)

    state = StubState(
        slots=[
            {"key": "chat-1001-fund", "title": "fund-manager",
             "folder_id": "f-td", "running": True},
            {"key": "chat-1196-macro", "title": "macro-strategist",
             "folder_id": "f-td", "running": False},
            {"key": "chat-1197-desk", "title": "desk-manager",
             "folder_id": "f-desk", "running": False},
            {"key": "chat-1198-lm-aic", "title": "line-manager · test-alpha",
             "folder_id": "f-aic", "running": True},
        ],
        folders=[
            {"id": "f-td", "name": "Trading Desk", "parent_id": ""},
            {"id": "f-desk", "name": "Desk", "parent_id": "f-td"},
            {"id": "f-aic", "name": "test-alpha", "parent_id": "f-desk"},
        ],
        # macro's session is resolvable by hint but no longer OPEN, which is the
        # 409 path /say must answer rather than reporting a phantom success.
        live_keys=("chat-1001-1700000001", "chat-1197-desk", "chat-1198-lm-aic"),
    )

    # ---- build the router the way the gateway does: static app routes first,
    # ---- then the RouteRegistry catch-all app routes dispatch from.
    app = web.Application()
    app["state"] = state
    register_app_routes(app)
    registry = RouteRegistry(app)
    routes = register_routes(ctx)
    registry._routes["trading-desk"] = [  # noqa: SLF001 — no trust gate in a test
        r for r in _compiled(routes)
    ]
    registry._contexts["trading-desk"] = ctx  # noqa: SLF001
    registry.ensure_catch_all()

    async def resolved_handler(method: str, path: str):
        request = make_mocked_request(method, path, app=app)
        match = await app.router.resolve(request)
        return match, request

    # ---- who wins each path
    match, _ = await resolved_handler("GET", "/api/apps/trading-desk/config")
    winner = getattr(match.handler, "__name__", "") or ""
    check("gateway's own handler wins /api/apps/{name}/config (cycle3 finding)",
          winner == "handle_app_config", winner)

    for method, path, label in (
        ("GET", "/api/apps/trading-desk/deskconfig", "/deskconfig"),
        ("GET", "/api/apps/trading-desk/org", "/org"),
        ("POST", "/api/apps/trading-desk/member/fund/reset", "/member/{id}/reset"),
        ("POST", "/api/apps/trading-desk/config/validate", "/config/validate"),
    ):
        match, _ = await resolved_handler(method, path)
        owner = getattr(match.handler, "__qualname__", "")
        check(f"{label} reaches the app's RouteRegistry", "dispatch" in owner, owner)

    # ---- reset through real dispatch, so {id} is matched by the pattern matcher
    async def dispatch(method: str, sub_path: str, user="tester", body=None):
        route, _, query = sub_path.partition("?")
        url = f"/api/apps/trading-desk/{sub_path}"
        request = make_mocked_request(
            method, url, app=app,
            headers={"Content-Type": "application/json"} if body is not None else None,
            match_info={"app_name": "trading-desk", "path": route},
            payload=_json_payload(body) if body is not None else sentinel_payload(),
        )
        if user is not None:
            request["user"] = user
        return await registry.dispatch(request)

    org_before = await body_of(await dispatch("GET", "org"))
    fund_before = next(m for m in org_before["members"] if m["id"] == "fund")
    check("before reset: fund is on its slot_hint session",
          fund_before["slot_key"] == "chat-1001-1700000001", fund_before["slot_key"])

    resp = await dispatch("POST", "member/fund/reset", user=None)
    check("reset unauthenticated → 401", resp.status == 401, str(resp.status))

    resp = await dispatch("POST", "member/nope/reset")
    check("reset unknown member → 404", resp.status == 404, str(resp.status))
    resp = await dispatch("POST", "member/..%2F..%2Fetc/reset")
    check("reset rejects a non-member id → 404", resp.status == 404, str(resp.status))

    resp = await dispatch("POST", "member/fund/reset")
    payload = await body_of(resp)
    check("reset 200 with {slot_key, previous}",
          resp.status == 200 and set(payload) == {"slot_key", "previous"},
          json.dumps(payload, ensure_ascii=False))
    first_key = payload.get("slot_key", "")
    m = KEY_RE.match(first_key)
    check("slot_key is td-<member_id>-<epoch>", bool(m) and m.group(1) == "fund", first_key)
    check("previous echoes the pre-reset key",
          payload.get("previous") == "chat-1001-1700000001", str(payload.get("previous")))

    # ---- the write itself
    written = json.loads(config_file.read_text())
    check("config.json slots override points at the new key",
          written.get("slots", {}).get("fund") == first_key,
          json.dumps(written.get("slots"), ensure_ascii=False))
    check("config.json keeps deskRoot / appRoot / statePath",
          written.get("deskRoot") == DESK
          and written.get("appRoot", "").endswith("/apps/trading-desk")
          and written.get("statePath", "").endswith("state.json"),
          json.dumps({k: v for k, v in written.items() if k != "slots"}, ensure_ascii=False))
    check("config.json keeps its permission bits (0600)",
          oct(config_file.stat().st_mode & 0o777) == "0o600",
          oct(config_file.stat().st_mode & 0o777))

    # ---- /org reflects it, and only for that member
    org_after = await body_of(await dispatch("GET", "org"))
    fund_after = next(m for m in org_after["members"] if m["id"] == "fund")
    check("/org binds fund to the new key", fund_after["slot_key"] == first_key,
          fund_after["slot_key"])
    # THE P0 REGRESSION GUARD. The new key exists nowhere in the gateway yet — the
    # embed creates that session lazily on the first message — and the member's OLD
    # session is still there and running. A slots override must still win outright:
    # filtering it back to null is what makes a just-opened chat vanish on a page
    # switch and the member read as "not started yet".
    check("override survives even though its session does not exist yet",
          fund_after["slot_key"] == first_key
          and not any(s["key"] == first_key for s in state.serialize_slots()),
          f"{fund_after['slot_key']} vs live keys "
          f"{[s['key'] for s in state.serialize_slots()]}")
    check("a bound-but-uncreated session does not read as not started",
          fund_after["state_msg"] != "not started", fund_after["state_msg"])
    check("/org reports the new session as not running",
          fund_after["slot_live"] is False and fund_after["state"] == "idle",
          f"{fund_after['slot_live']} / {fund_after['state']}")
    unbound = next(m for m in org_after["members"] if m["slot_key"] is None)
    check("a member with no session at all still reads not started",
          unbound["state_msg"] == "not started", f"{unbound['id']}: {unbound['state_msg']}")
    others_before = {m["id"]: m["slot_key"] for m in org_before["members"] if m["id"] != "fund"}
    others_after = {m["id"]: m["slot_key"] for m in org_after["members"] if m["id"] != "fund"}
    check("reset touched no other member's binding", others_before == others_after)

    # ---- the old session is untouched in the gateway
    check("old session still present in the gateway",
          any(s["key"] == "chat-1001-1700000001" for s in state.serialize_slots()))

    # ---- a second reset chains off the first, never repeating a key
    resp = await dispatch("POST", "member/fund/reset")
    second = await body_of(resp)
    check("second reset chains previous → the first new key",
          second.get("previous") == first_key, str(second.get("previous")))
    check("second reset mints a different key", second.get("slot_key") != first_key,
          f"{first_key} -> {second.get('slot_key')}")
    check("config.json now holds the second key",
          json.loads(config_file.read_text())["slots"]["fund"] == second["slot_key"])

    # ---- a line-manager id (contains a hyphen) resets too
    resp = await dispatch("POST", "member/lm-test-alpha/reset")
    lm = await body_of(resp)
    check("reset works for lm-<pod>",
          resp.status == 200 and lm["slot_key"].startswith("td-lm-test-alpha-"),
          json.dumps(lm, ensure_ascii=False))
    check("first member's binding survived the second member's reset",
          json.loads(config_file.read_text())["slots"]["fund"] == second["slot_key"])

    # ---- a corrupt config must not lose the reset
    config_file.write_text("{ not json")
    resp = await dispatch("POST", "member/fund/reset")
    check("reset recovers from a corrupt config.json", resp.status == 200, str(resp.status))
    recovered = json.loads(config_file.read_text())
    check("recovered config carries the new slot",
          recovered.get("slots", {}).get("fund", "").startswith("td-fund-"),
          json.dumps(recovered, ensure_ascii=False))
    check("recovery rebuilds deskRoot + appRoot instead of dropping them",
          recovered.get("deskRoot") == DESK and str(recovered.get("appRoot", "")) == str(APP),
          json.dumps({k: v for k, v in recovered.items() if k != "slots"}, ensure_ascii=False))
    aside = sorted(data_dir.glob("config.json.corrupt-*"))
    check("the unreadable file is kept aside, not deleted",
          bool(aside) and aside[-1].read_text() == "{ not json", str(aside[-1:]))

    # ---- M2 threads
    await check_threads(routes, ctx, config_file, app, state, dispatch, body_of)

    # ---- rev6.1 threads folder as the second source
    await check_threads_folder(ctx, config_file, app, dispatch, body_of)

    # ---- rev7b POST /thread
    await check_thread_create(ctx, config_file, app, dispatch, body_of)

    # ---- rev8 §13.2 anchors, on the real conversation the ruling was measured on
    await check_rev8_real_anchors(ctx, config_file, app, dispatch, body_of)

    print()
    print("ALL PASS" if not FAILURES else f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    return 1 if FAILURES else 0


# ---------------------------------------------------------------------------
# rev6 threads (CONTRACT §11)
# ---------------------------------------------------------------------------
#: The fake session universe the derive is exercised against:
#: ``key -> (agent, title, running, open, rows)``.
#:
#: The agents are the roster's real ones, because classification is BY AGENT and
#: nothing else. Two sessions share ``tada-line-manager`` on purpose — nine
#: line-managers really do — so both the resolvable and the unresolvable case of a
#: shared agent are covered.
MAIN = "chat-1001-1700000001"
CLONE = "chat-7001-1700000001"
DISPATCH = "chat-7002-1700000002"
FOREIGN = "chat-7003-1700000003"
LM_NAMED = "chat-7004-1700000004"
LM_VAGUE = "chat-7005-1700000005"
FROM_TOOL = "chat-7006-1700000006"
FROM_LISTING = "chat-7007-1700000007"
CLOSED = "chat-7008-1700000008"
#: §11.5.2 — the same session named the store's way, never bare.
PREFIXED = "chat-7010-1700000010"
UNDERSCORED = "chat-7011-1700000011"
#: Named BOTH ways, prefixed first: one thread, anchored at the prefixed mention.
DUAL = "chat-7012-1700000012"
#: rev6.1 — reported ONLY by a session_create output, never in prose.
CREATED = "chat-7013-1700000013"
#: Reported only by a session_create the user DENIED: nothing was opened.
DENIED = "chat-7014-1700000014"
#: One of the 86 keys a chat_folder_tree output lists, and a desk session at that.
LISTED_DESK = "chat-7015-1700000015"
#: Named before the conversation's first user message — a resumed or cron-driven
#: session — so §13.2's fallback is the only thing that can anchor it.
ORPHAN = "chat-7016-1700000016"
#: Quoted inside a session_send's MESSAGE body as routing advice. A real desk
#: agent, so only not reading the body keeps it from becoming a phantom thread.
QUOTED_IN_SEED = "chat-7017-1700000017"


def _rows(*pairs):
    return [
        {"role": role, "ts": ts, "content": text, "meta": {"mid": f"m-{i:016d}"}}
        for i, (role, ts, text) in enumerate(pairs, 1)
    ]


UNIVERSE = {
    CLONE: ("tada-fund-manager", "test-alpha deep dive", True, True, _rows(
        ("user", "2026-09-14T16:45:00+00:00", "Dig into HBM supply"),
        ("assistant", "2026-09-14T16:50:00+00:00", "Start with the three vendors' capacity guidance."),
        ("tool", "2026-09-14T16:51:00+00:00", "🔧 read teams/test-alpha"),
        ("assistant", "2026-09-14T17:07:41+00:00", "Supply only loosens in 2027, so assume a tight balance for now."),
    )),
    DISPATCH: ("tada-desk-manager", "desk-manager", False, True, _rows(
        ("user", "2026-09-14T16:46:00+00:00", "Collect each pod's conclusions"),
        ("assistant", "2026-09-14T16:58:00+00:00", "All 9 pods are in."),
    )),
    FOREIGN: ("kirocrew", "some random tab", False, True, _rows(
        ("user", "2026-09-14T10:00:00+00:00", "Take a look at a PR for me"),
    )),
    LM_NAMED: ("tada-line-manager", "line-manager · test-alpha", False, True, _rows(
        ("assistant", "2026-09-14T17:00:00+00:00", "Pod report delivered."),
    )),
    LM_VAGUE: ("tada-line-manager", "opened on a whim", False, True, []),
    FROM_TOOL: ("tada-risk-pod", "risk-pod", False, True, _rows(
        ("assistant", "2026-09-14T17:20:00+00:00", "Review passed."),
    )),
    FROM_LISTING: ("tada-trader", "trader", False, True, _rows(
        ("assistant", "2026-09-14T17:30:00+00:00", "The proposal is here."),
    )),
    # Its transcript proves it existed, but the gateway holds no open slot, so the
    # panel cannot be opened — the one honest use of `failed` in rev6.
    CLOSED: ("tada-scrum-master", "scrum-master", False, False, _rows(
        ("assistant", "2026-09-14T09:00:00+00:00", "The rhythm is fine."),
    )),
    # §11.5.2: the two prefixed spellings the store and the API side use.
    PREFIXED: ("tada-fund-manager", "the colon-prefixed one", False, True, _rows(
        ("assistant", "2026-09-14T17:46:00+00:00", "This one is the colon form."),
    )),
    UNDERSCORED: ("tada-fund-manager", "the underscore-prefixed one", False, True, _rows(
        ("assistant", "2026-09-14T17:51:00+00:00", "This one is the underscore form."),
    )),
    DUAL: ("tada-desk-manager", "mentioned in both forms", False, True, []),
    # rev6.1: opened by a session_create whose output is the only record of the key.
    CREATED: ("tada-fund-manager", "opened by the mechanism", False, True, _rows(
        ("assistant", "2026-09-14T18:05:00+00:00", "This one was opened by session_create."),
    )),
    # A desk session that a chat_folder_tree output happens to LIST. It passes the
    # agent test, so only not reading that output keeps it out.
    LISTED_DESK: ("tada-trader", "trader", False, True, []),
    # The denied create's key: this session was never opened, so nothing knows it.
    DENIED: ("tada-fund-manager", "the denied one", False, True, []),
    # Named in the opening row, before any user message exists to anchor it.
    ORPHAN: ("tada-fund-manager", "already running when I took over", False, True, _rows(
        ("assistant", "2026-09-14T15:00:00+00:00", "Last night's work isn't wrapped up yet."),
    )),
    # Quoted in a seed brief as "send here if you need risk". A real risk-pod
    # session, so the agent gate passes and only the field rule keeps it out.
    QUOTED_IN_SEED: ("tada-risk-pod", "risk-pod", False, True, []),
}

#: fund's MAIN conversation, laid out as TURNS — because §13.2 anchors a thread to
#: the user message that triggered the turn it was found in, so a fixture with one
#: user row at the top could not tell a correct anchor from a collapsed one.
#:
#: Every mention source rev6 reads still appears: the conductor's own receipt
#: (prose), a key in a TOOL INPUT, a key only a ``session_create`` OUTPUT reports,
#: and — the trap — a key that appears ONLY in another tool's output, the way one
#: ``chat_folder_tree`` call drops the whole sidebar into a transcript.
MAIN_DAY = [
    # ---- before the first user message: a resumed conversation's opening line.
    # ---- §13.2's fallback is the only thing that can anchor a key named here.
    {"role": "assistant", "ts": "2026-09-14T16:30:00+00:00", "meta": {"mid": "m-preamble"},
     "content": f"Picking up from last night: `{ORPHAN}` is still running."},

    # ---- TURN A: one request, FOUR threads. §13.2 rule 3 — two topics two lines,
    # ---- so several threads may share one user message, one bar each.
    {"role": "user", "ts": "2026-09-14T16:40:00+00:00", "meta": {"mid": "m-ceo-instruction"},
     "content": "Research the test-alpha pod, focus on HBM supply"},
    {"role": "assistant", "ts": "2026-09-14T16:44:00+00:00", "meta": {"mid": "m-receipt-one"},
     "content": f"Opened thread `{CLONE}` to dig in, and dispatched desk-manager `{DISPATCH}`; the steps are all in the thread. "
                f"For the record, that's my own one `{MAIN}`, plus an unrelated tab `{FOREIGN}`."},
    {"role": "assistant", "ts": "2026-09-14T16:59:00+00:00", "meta": {"mid": "m-receipt-two"},
     "content": f"The test-alpha pod one is `{LM_NAMED}`, and there's another I opened on a whim `{LM_VAGUE}`."},

    # ---- TURN B: names the SAME clone a third time, plus a tool-sourced key. The
    # ---- repeat must not mint a second anchor, and must not move the first one.
    {"role": "user", "ts": "2026-09-14T17:10:00+00:00", "meta": {"mid": "m-ceo-risk"},
     "content": "Have risk run through it too"},
    {"role": "assistant", "ts": "2026-09-14T17:15:00+00:00", "meta": {"mid": "m-before-tool"},
     "content": f"Sending it for a risk review; the deep-dive one is still `{CLONE}`."},
    {"role": "tool", "ts": "2026-09-14T17:16:00+00:00", "meta": {
        "mid": "m-tool-send",
        "input": json.dumps({
            # The real shape of a seed: an addressee in `target`, and a body that
            # quotes OTHER sessions as routing advice. §13.2 reads `target` alone.
            "target": FROM_TOOL,
            "message": "Review test-alpha. If needed, session_send into the risk-pod standing session"
                       f" (`{QUOTED_IN_SEED}`).",
        }),
        "output": f"🗂️ Sidebar folder tree — 131 live sessions:\n  · {FROM_LISTING}  trader\n",
    }, "content": "🔧 Running: session_send"},
    {"role": "nudge", "ts": "2026-09-14T17:17:00+00:00", "meta": {"mid": "m-nudge"},
     "content": f"[auto-nudge cycle 3] while you're at it, check `{CLOSED}`"},
    {"role": "assistant", "ts": "2026-09-14T17:40:00+00:00", "meta": {"mid": "m-receipt-three"},
     "content": f"The scrum one `{CLOSED}` was already opened this morning."},

    # ---- TURN C / TURN D: §11.5.2's two prefixed spellings, one per turn so each
    # ---- still anchors on its own. DUAL is named prefixed in C and bare in D: one
    # ---- thread, anchored where it was FIRST seen, which is C's request.
    {"role": "user", "ts": "2026-09-14T17:44:00+00:00", "meta": {"mid": "m-ceo-store"},
     "content": "What are those two in the store"},
    {"role": "assistant", "ts": "2026-09-14T17:45:00+00:00", "meta": {"mid": "m-prefixed"},
     "content": f"The one in the store is `dashboard:{PREFIXED}`, and `dashboard:{DUAL}` is open too."},
    {"role": "user", "ts": "2026-09-14T17:49:00+00:00", "meta": {"mid": "m-ceo-fold"},
     "content": "Where does the transcript land"},
    {"role": "assistant", "ts": "2026-09-14T17:50:00+00:00", "meta": {"mid": "m-underscored"},
     "content": f"The transcript lands at dashboard_{UNDERSCORED}. And `{DUAL}` is the one above."},

    # ---- TURN E — rev6.1: the mechanism is the trigger. These rows carry the REAL
    # ---- content lines and meta shapes, verified against 28 session_create rows
    # ---- and 11 chat_folder_tree rows in the live transcripts.
    {"role": "user", "ts": "2026-09-14T17:59:00+00:00", "meta": {"mid": "m-ceo-create"},
     "content": "Open your own thread and dig into this one"},
    {"role": "assistant", "ts": "2026-09-14T18:00:00+00:00", "meta": {"mid": "m-before-create"},
     "content": "I'll open a thread to dig into this one."},
    {"role": "tool", "ts": "2026-09-14T18:01:00+00:00", "meta": {
        "mid": "m-create-ran", "kind": "unknown",
        "input": json.dumps({"agent": "tada-fund-manager", "title": "opened by the mechanism"}),
        "output": f"🆕 Opened `{CREATED}` (opened by the mechanism). It is empty and waiting in the "
                  "user's sidebar; watch it with session_read_message.",
    }, "content": "🔧 Running: @kirocrew-dashboard/session_create"},
    # The user denied it, so nothing was created — 🚫 instead of 🔧.
    {"role": "tool", "ts": "2026-09-14T18:02:00+00:00", "meta": {
        "mid": "m-create-denied", "kind": "unknown",
        "input": json.dumps({"agent": "tada-fund-manager", "title": "the denied one"}),
        "output": f"🆕 Opened `{DENIED}` (the denied one).",
    }, "content": "🚫 Running: @kirocrew-dashboard/session_create"},
    # The trap this exception has to stay narrow enough to avoid: same meta.kind as
    # a session_create row, and its output lists a session on a real desk agent.
    {"role": "tool", "ts": "2026-09-14T18:03:00+00:00", "meta": {
        "mid": "m-tree", "kind": "unknown",
        "input": json.dumps({"__tool_use_purpose": "see the sidebar"}),
        "output": "🗂️ Sidebar folder tree — 69 folders, 131 live sessions:\n"
                  f"  · {LISTED_DESK}  trader\n  · {FROM_LISTING}  trader\n",
    }, "content": "🔧 Running: @kirocrew-dashboard/chat_folder_tree"},

    # ---- TURN F: the request itself has NO mid, so there is nothing addressable to
    # ---- hang the thread on and it must downgrade rather than ship a bad id.
    {"role": "user", "ts": "2026-09-15T01:59:00+00:00", "content": "Open another one and take a look"},
    {"role": "assistant", "ts": "2026-09-15T02:00:00+00:00", "meta": {"mid": "m-receipt-four"},
     "content": "Opened another one `chat-7009-1700000009`."},
]

UNIVERSE["chat-7009-1700000009"] = ("tada-fund-manager", "no mid", False, True, [])

#: Every request row's mid, read off the fixture rather than restated, so a row
#: added to MAIN_DAY cannot make "the anchor is a user row" pass by omission.
_REQUEST_MIDS = {
    str((row.get("meta") or {}).get("mid"))
    for row in MAIN_DAY
    if row.get("role") == "user" and (row.get("meta") or {}).get("mid")
}


class ThreadState(StubState):
    """The gateway as rev6 reads it: slots that carry an ``agent``."""

    def __init__(self) -> None:
        slots = [
            {"key": MAIN, "title": "fund-manager", "folder_id": "f-td",
             "running": False, "agent": "tada-fund-manager"},
        ]
        for key, (agent, title, running, is_open, _rowlist) in UNIVERSE.items():
            if is_open:
                slots.append({"key": key, "title": title, "folder_id": "f-x",
                              "running": running, "agent": agent})
        super().__init__(
            slots=slots,
            folders=[{"id": "f-td", "name": "Trading Desk", "parent_id": ""},
                     {"id": "f-x", "name": "Trading Desk", "parent_id": ""}],
            live_keys=tuple(k for k, v in UNIVERSE.items() if v[3]),
        )


async def check_threads(routes, ctx, config_file, app, state, dispatch, body_of) -> None:
    """§11: a thread is a session the conductor opened, classified by its agent."""
    from backend import threads as threads_mod
    from backend import transcript

    root = Path(DESK)
    # The reset checks left slot overrides behind; drop them so fund resolves to
    # MAIN through its roster hint, which is the conversation being scanned.
    config_file.write_text(json.dumps({"deskRoot": DESK}, indent=2) + "\n")

    declared = {(r.method, r.path) for r in routes}
    for method, path in (("GET", "/threads"), ("GET", "/thread/{id}"),
                         ("POST", "/thread/{id}/say")):
        check(f"route {method} {path} declared", (method, path) in declared, "")

    # ---- real-data regression FIRST, before any stubbing: the live fund
    # ---- conversation must still derive, since that is what §11.4 is verified on.
    live = await body_of(await dispatch("GET", "threads?member=fund"))
    check("/threads answers 200 against the real desk with no stubs",
          isinstance(live.get("threads"), list),
          json.dumps(live, ensure_ascii=False)[:120])

    # ---- input validation
    resp = await dispatch("GET", "threads")
    check("/threads without member → 400", resp.status == 400, str(resp.status))
    resp = await dispatch("GET", "threads?member=nope")
    check("/threads unknown member → 404", resp.status == 404, str(resp.status))
    resp = await dispatch("GET", "threads", user=None)
    check("/threads unauthenticated → 401", resp.status == 401, str(resp.status))
    resp = await dispatch("GET", "thread/not-a-thread-id")
    check("/thread bad id → 404", resp.status == 404, str(resp.status))
    resp = await dispatch("GET", "thread/th-fund-2026-09-14-99")
    check("/thread seq that names nothing → 404", resp.status == 404, str(resp.status))

    # ---- swap in the fake gateway + universe
    real_read, real_meta = transcript.read, transcript.session_meta
    real_state = app["state"]
    thread_state = ThreadState()
    app["state"] = thread_state

    def fake_read(_gw, key):
        if key == MAIN:
            return [dict(m) for m in MAIN_DAY]
        entry = UNIVERSE.get(key)
        return [dict(m) for m in entry[4]] if entry else []

    def fake_meta(_gw, key):
        entry = UNIVERSE.get(key)
        if key == MAIN:
            return {"agent": "tada-fund-manager", "title": "fund-manager",
                    "created_at": "2026-09-14T16:39:00+00:00"}
        if entry is None:
            return {}
        return {"agent": entry[0], "title": entry[1],
                "created_at": "2026-09-14T16:43:00+00:00"}

    transcript.read, transcript.session_meta = fake_read, fake_meta
    try:
        payload = await body_of(await dispatch("GET", "threads?member=fund"))
        found = payload.get("threads", [])
        by_key = {t["slot_key"]: t for t in found}

        # ---- CLASSIFICATION: the whole of rev6 turns on this
        check("a session with the member's OWN agent is its thread clone",
              CLONE in by_key and by_key[CLONE]["kind"] == "thread"
              and by_key[CLONE]["member"] == "fund",
              json.dumps(by_key.get(CLONE, {}), ensure_ascii=False)[:110])
        check("a session with ANOTHER member's agent is a dispatch, typed as one",
              DISPATCH in by_key and by_key[DISPATCH]["kind"] == "dispatch"
              and by_key[DISPATCH]["member"] == "desk",
              json.dumps(by_key.get(DISPATCH, {}), ensure_ascii=False)[:110])
        check("a session on no desk agent is dropped, not listed",
              FOREIGN not in by_key, str(sorted(by_key)))
        check("the member's OWN main conversation is not a thread of itself",
              MAIN not in by_key, str(sorted(by_key)))
        check("a shared agent is attributed by the session's title",
              LM_NAMED in by_key and by_key[LM_NAMED]["member"] == "lm-test-alpha",
              str(by_key.get(LM_NAMED, {}).get("member")))
        check("an unresolvable shared agent is listed with member null, not guessed",
              LM_VAGUE in by_key and by_key[LM_VAGUE]["member"] is None
              and by_key[LM_VAGUE]["kind"] == "dispatch",
              json.dumps(by_key.get(LM_VAGUE, {}), ensure_ascii=False)[:110])

        # ---- WHICH TEXT IS SCANNED: input yes, output never
        check("a key named in a tool's INPUT is found",
              FROM_TOOL in by_key, str(sorted(by_key)))
        check("a key quoted in a session_send's MESSAGE body is NOT a thread (§13.2)",
              QUOTED_IN_SEED not in by_key,
              "a seed brief's routing advice is talked about, not addressed")
        check("...while the same call's `target` still is",
              FROM_TOOL in by_key and by_key[FROM_TOOL]["kind"] == "dispatch",
              json.dumps(by_key.get(FROM_TOOL, {}), ensure_ascii=False)[:110])
        check("the field rule is keyed on the tool name, and reads target only",
              transcript.tool_input_text({
                  "content": "🔧 Running: @kirocrew-dashboard/session_send",
                  "meta": {"input": json.dumps({"target": "chat-1-1", "message": "chat-2-2"})},
              }).strip() == "chat-1-1"
              and transcript.tool_input_text({
                  "content": "🔧 Running: @kirocrew-dashboard/session_read_message",
                  "meta": {"input": json.dumps({"target": "chat-1-1", "note": "chat-2-2"})},
              }).count("chat-2-2") == 1,
              "session_send narrowed; every other tool's input read whole")
        check("an unreadable session_send input yields nothing, never the whole blob",
              transcript.tool_input_text({
                  "content": "🔧 Running: @kirocrew-dashboard/session_send",
                  "meta": {"input": "{ not json — chat-9-9"},
              }) == ""
              and transcript.tool_input_text({
                  "content": "🔧 Running: @kirocrew-dashboard/session_send",
                  "meta": {"input": ""},
              }) == "",
              "falling back to the raw text would reopen the hole")
        check("a DENIED session_send still names who it addressed",
              transcript.tool_input_text({
                  "content": "🚫 Running: @kirocrew-dashboard/session_send",
                  "meta": {"input": json.dumps({"target": "chat-1-1"})},
              }).strip() == "chat-1-1",
              "the marker gates the OUTPUT scan, not the addressee")
        check("a key that appears ONLY in a tool's OUTPUT is NOT a thread",
              FROM_LISTING not in by_key,
              "one chat_folder_tree call would otherwise mint the whole sidebar")
        check("a nudge row is the runtime talking, not a receipt",
              # CLOSED is named in a nudge AND in a later assistant row. Neither is
              # the anchor under §13.2 — the turn's own request is — but the nudge
              # must not be counted as the request either, which is what this pins.
              by_key.get(CLOSED, {}).get("anchor", {}).get("main_msg") == "m-ceo-risk",
              str(by_key.get(CLOSED, {}).get("anchor")))

        # ---- §11.5.2: BOTH key forms, each anchoring on its own
        check("a `dashboard:`-prefixed key is found and normalised to the bare key",
              PREFIXED in by_key
              and by_key[PREFIXED]["anchor"]["main_msg"] == "m-ceo-store",
              json.dumps(by_key.get(PREFIXED, {}).get("anchor"), ensure_ascii=False))
        check("a `dashboard_`-prefixed key (the transcript-filename fold) is found too",
              UNDERSCORED in by_key
              and by_key[UNDERSCORED]["anchor"]["main_msg"] == "m-ceo-fold",
              json.dumps(by_key.get(UNDERSCORED, {}).get("anchor"), ensure_ascii=False))
        check("a bare key still anchors — the CLONE is named bare only",
              by_key[CLONE]["anchor"]["main_msg"] == "m-ceo-instruction",
              str(by_key[CLONE]["anchor"]["main_msg"]))
        check("the same session named BOTH ways is ONE thread, not two",
              len([t for t in found if t["slot_key"] == DUAL]) == 1,
              str([t["id"] for t in found if t["slot_key"] == DUAL]))
        check("a prefixed mention can BE the first sighting, and dates the anchor",
              by_key[DUAL]["anchor"]["main_msg"] == "m-ceo-store",
              json.dumps(by_key[DUAL]["anchor"], ensure_ascii=False))
        check("a prefixed key resolves its agent off the BARE form",
              by_key[PREFIXED]["agent"] == "tada-fund-manager"
              and by_key[PREFIXED]["kind"] == "thread"
              and by_key[UNDERSCORED]["kind"] == "thread",
              f"{by_key[PREFIXED]['agent']} / {by_key[PREFIXED]['kind']}")
        check("slot_key is emitted bare, never with the store's prefix",
              all(not t["slot_key"].startswith("dashboard") for t in found),
              str([t["slot_key"] for t in found]))
        check("a prefixed mention's preview is scrubbed of the prefix too",
              not transcript.has_key_shape(by_key[PREFIXED]["anchor"]["preview"])
              and not transcript.has_key_shape(by_key[UNDERSCORED]["anchor"]["preview"]),
              f"{by_key[PREFIXED]['anchor']['preview']!r} / "
              f"{by_key[UNDERSCORED]['anchor']['preview']!r}")

        # ---- rev6.1: opening a session IS opening a thread
        check("a session_create's OUTPUT key becomes a thread with no prose mention",
              CREATED in by_key and by_key[CREATED]["kind"] == "thread",
              json.dumps(by_key.get(CREATED, {}), ensure_ascii=False)[:110])
        check("that thread anchors to the request, never to the tool row",
              by_key.get(CREATED, {}).get("anchor", {}).get("main_msg") == "m-ceo-create",
              json.dumps(by_key.get(CREATED, {}).get("anchor"), ensure_ascii=False))
        check("a DENIED session_create opened nothing, so its output is not scanned",
              DENIED not in by_key, str(sorted(by_key)))
        check("chat_folder_tree's output is still unread — its 131-session listing "
              "cannot mint threads",
              LISTED_DESK not in by_key and FROM_LISTING not in by_key,
              str(sorted(by_key)))
        check("the exception is keyed on the tool NAME, not meta.kind — both rows "
              "carry kind='unknown'",
              transcript.tool_created_session(
                  {"content": "🔧 Running: @kirocrew-dashboard/session_create"})
              and not transcript.tool_created_session(
                  {"content": "🔧 Running: @kirocrew-dashboard/chat_folder_tree"})
              and not transcript.tool_created_session(
                  {"content": "🚫 Running: @kirocrew-dashboard/session_create"})
              and transcript.tool_created_session(
                  {"content": "✅ Running: @kirocrew-dashboard/session_create"}),
              "🔧/✅ create yes, 🚫 create no, folder_tree no")

        # ---- ANCHOR (§13.2 rev8: one per thread, on the message that asked)
        clone_anchor = by_key[CLONE]["anchor"]
        check("a thread hangs under the user message that triggered its turn",
              clone_anchor["main_msg"] == "m-ceo-instruction",
              json.dumps(clone_anchor, ensure_ascii=False))
        check("anchor carries all three keys: main_msg, ts, preview",
              set(clone_anchor) == {"main_msg", "ts", "preview"}, str(sorted(clone_anchor)))
        check("anchor ts is the source row's ts, byte for byte",
              clone_anchor["ts"] == MAIN_DAY[1]["ts"],
              f"{clone_anchor['ts']!r} vs {MAIN_DAY[1]['ts']!r}")
        check("anchor ts is NOT reformatted (it is the UI's row key)",
              clone_anchor["ts"] == "2026-09-14T16:40:00+00:00", repr(clone_anchor["ts"]))
        check("anchor preview is the reader's own words, not the manager's narration",
              clone_anchor["preview"].startswith("Research the test-alpha"),
              repr(clone_anchor["preview"]))
        check("anchor preview is scrubbed of every key shape",
              not transcript.has_key_shape(clone_anchor["preview"]),
              repr(clone_anchor["preview"]))
        check("anchor preview is capped at 60 chars",
              len(clone_anchor["preview"]) <= 60, str(len(clone_anchor["preview"])))

        # §13.2 rule 1 — ONE anchor per thread. The clone is named three times over
        # two turns (turn A's receipt, turn A's second receipt, turn B's prose): one
        # thread object, and it stays on the turn that FIRST named it.
        named_thrice = sum(
            1 for row in MAIN_DAY if CLONE in str(row.get("content") or "")
        )
        check("one thread mentioned repeatedly still produces exactly ONE anchor",
              named_thrice >= 2 and len([t for t in found if t["slot_key"] == CLONE]) == 1,
              f"named in {named_thrice} rows")
        check("a repeat mention in a LATER turn does not move the anchor",
              by_key[CLONE]["anchor"]["main_msg"] == "m-ceo-instruction",
              "turn B names it again; turn A's request keeps it")
        check("every anchor lands on a user row, never on the manager's narration",
              all(a["main_msg"] in _REQUEST_MIDS | {"m-preamble"}
                  for a in (t["anchor"] for t in found) if a),
              str(sorted({t["anchor"]["main_msg"] for t in found if t["anchor"]})))

        # §13.2 rule 3 — several threads may share one request, one bar each.
        on_turn_a = sorted(
            t["slot_key"] for t in found
            if t["anchor"] and t["anchor"]["main_msg"] == "m-ceo-instruction"
        )
        check("one user message can carry several threads, each with its own bar",
              on_turn_a == sorted([CLONE, DISPATCH, LM_NAMED, LM_VAGUE]),
              str(on_turn_a))

        # §13.2's fallback: no request to hang on, so the nearest visible row does.
        check("a key named before the first user message falls back to that row",
              by_key.get(ORPHAN, {}).get("anchor", {}).get("main_msg") == "m-preamble",
              json.dumps(by_key.get(ORPHAN, {}).get("anchor"), ensure_ascii=False))

        check("a tool-sourced key anchors on the request, never on the tool row",
              by_key[FROM_TOOL]["anchor"]["main_msg"] == "m-ceo-risk",
              json.dumps(by_key[FROM_TOOL]["anchor"], ensure_ascii=False))
        check("a request with no mid downgrades to anchor null",
              by_key.get("chat-7009-1700000009", {}).get("anchor") is None,
              str(by_key.get("chat-7009-1700000009", {}).get("anchor")))

        # ---- IDENTITY
        ids = [t["id"] for t in found]
        check("ids are th-{member}-{date}-{seq}, seq scoped per date",
              [i for i in ids if i.startswith("th-fund-2026-09-14-")] == [
                  f"th-fund-2026-09-14-{n}" for n in range(1, 12)]
              and "th-fund-2026-09-15-1" in ids, str(ids))
        again = await body_of(await dispatch("GET", "threads?member=fund"))
        check("derive is idempotent (same inputs, same ids and order)",
              [t["id"] for t in again["threads"]] == ids, str([t["id"] for t in again["threads"]]))
        check("no duplicate ids", len(set(ids)) == len(ids), str(ids))

        # ---- DATE: a filter, not a default
        check("no ?date= returns EVERY date's threads",
              len({t["refs"]["run_date"] for t in found}) > 1,
              str(sorted({t["refs"]["run_date"] for t in found})))
        one_day = await body_of(await dispatch("GET", "threads?member=fund&date=2026-09-15"))
        check("?date= filters to that date only",
              [t["id"] for t in one_day["threads"]] == ["th-fund-2026-09-15-1"],
              str([t["id"] for t in one_day["threads"]]))

        # ---- STATE
        check("a session with a turn in flight is running",
              by_key[CLONE]["state"] == "running", by_key[CLONE]["state"])
        check("an open, idle session is done",
              by_key[DISPATCH]["state"] == "done", by_key[DISPATCH]["state"])
        check("a session the gateway no longer holds open is failed — the panel cannot open",
              by_key[CLOSED]["state"] == "failed", by_key[CLOSED]["state"])

        # ---- THE REPLY BAR'S OWN NUMBERS
        check("entry_count is the thread session's visible rows, tool rows excluded",
              by_key[CLONE]["entry_count"] == 3, str(by_key[CLONE]["entry_count"]))
        check("last_ts is the newest visible row's instant, verbatim",
              by_key[CLONE]["last_ts"] == "2026-09-14T17:07:41+00:00",
              repr(by_key[CLONE]["last_ts"]))
        check("a thread with no rows reports 0 and a null last_ts",
              by_key[LM_VAGUE]["entry_count"] == 0 and by_key[LM_VAGUE]["last_ts"] is None,
              f"{by_key[LM_VAGUE]['entry_count']} / {by_key[LM_VAGUE]['last_ts']!r}")
        check("last_msg quotes the thread's newest line",
              by_key[CLONE]["last_msg"].startswith("Supply only loosens in 2027"), by_key[CLONE]["last_msg"])
        check("no thread ships an empty last_msg",
              all(t["last_msg"] for t in found),
              str([t["id"] for t in found if not t["last_msg"]]))

        # ---- /thread/{id}: metadata + slot_key, and the SAME object
        detail = await body_of(await dispatch("GET", f"thread/{by_key[CLONE]['id']}"))
        check("/thread/{id} is byte-for-byte the list's entry — they cannot drift",
              detail == by_key[CLONE],
              json.dumps(detail, ensure_ascii=False)[:120])
        check("/thread/{id} no longer returns a folded timeline",
              "entries" not in detail, str(sorted(detail)))
        check("/thread/{id} carries slot_key and agent, which the panel needs",
              detail.get("slot_key") == CLONE and detail.get("agent") == "tada-fund-manager",
              f"{detail.get('slot_key')} / {detail.get('agent')}")

        # ---- rev6's NARROWER red line. §11.2 puts the key in the payload on
        # ---- purpose, so the invariant is no longer "no key anywhere": it is that a
        # ---- key appears in slot_key and NOWHERE else. The main conversation above
        # ---- is full of keys, so anchor.preview is the field this really tests.
        for thread in found:
            rest = {k: v for k, v in thread.items() if k != "slot_key"}
            check(f"{thread['id']}: a key appears in slot_key and nowhere else",
                  not transcript.has_key_shape(rest),
                  json.dumps(rest, ensure_ascii=False)[:120])

        # ---- /say goes to the thread's OWN slot
        resp = await dispatch("POST", f"thread/{by_key[CLONE]['id']}/say", body={})
        check("/say without text → 400", resp.status == 400, str(resp.status))
        resp = await dispatch("POST", "thread/nope/say", body={"text": "hi"})
        check("/say unknown thread → 404", resp.status == 404, str(resp.status))

        thread_state.delivered.clear()
        resp = await dispatch("POST", f"thread/{by_key[CLONE]['id']}/say",
                              body={"text": "Ask macro one more round"})
        said = await body_of(resp)
        check("/say 200 with {ok, delivered_to, slot_key}",
              resp.status == 200 and said.get("ok") is True
              and said.get("delivered_to") == "fund" and said.get("slot_key") == CLONE,
              json.dumps(said, ensure_ascii=False))
        check("/say lands on the THREAD's own session, not a participant search",
              thread_state.delivered and thread_state.delivered[-1][0] == CLONE,
              str(thread_state.delivered[-1:]))
        check("/say actually put the text on that session",
              thread_state.delivered and thread_state.delivered[-1][1] == "Ask macro one more round",
              str(thread_state.delivered[-1:]))
        resp = await dispatch("POST", f"thread/{by_key[CLOSED]['id']}/say",
                              body={"text": "Still there?"})
        check("/say into a session the gateway dropped → 409, not a silent success",
              resp.status == 409, f"{resp.status} {await body_of(resp)}")

        # ---- a dispatch to a member whose agent is shared and unattributed still
        # ---- has somewhere to go: the thread's owner names it.
        resp = await dispatch("POST", f"thread/{by_key[LM_VAGUE]['id']}/say",
                              body={"text": "What are you working on?"})
        said = await body_of(resp)
        check("/say on an unattributed thread names the thread's owner",
              resp.status == 200 and said.get("delivered_to") == "fund",
              json.dumps(said, ensure_ascii=False))

        target = threads_mod.target(
            root, ctx, await slots_snapshot(thread_state), by_key[DISPATCH]["id"])
        check("threads.target resolves to (member, the thread's own key)",
              target == ("desk", DISPATCH), str(target))
    finally:
        transcript.read, transcript.session_meta = real_read, real_meta
        app["state"] = real_state



async def slots_snapshot(state):
    from backend import slots as slots_mod
    return await slots_mod.snapshot(state)


# ---------------------------------------------------------------------------
# rev7b — POST /thread (CONTRACT §12)
# ---------------------------------------------------------------------------
NEW_THREAD = "chat-8201-1700003001"
NEW_SECOND = "chat-8202-1700003002"

#: The member's own conversation, with one message the user can pick.
MAIN_712 = [
    {"role": "user", "ts": "2026-09-14T11:00:00+00:00", "meta": {"mid": "m-712-pick"},
     "content": "I want a separate line for the HBM supply topic, kept out of the main conversation, and also take a look at test-alpha"},
    {"role": "assistant", "ts": "2026-09-14T11:01:00+00:00", "meta": {"mid": "m-712-reply"},
     "content": "Got it."},
]


class CreateState(StubState):
    """A gateway with the member's conversation open and NO threads folder yet."""

    def __init__(self, main_key: str) -> None:
        super().__init__(
            slots=[{"key": main_key, "title": "fund-manager", "folder_id": "h-td",
                    "running": False, "agent": "tada-fund-manager"}],
            folders=[{"id": "h-td", "name": "Trading Desk", "parent_id": ""}],
            live_keys=(main_key,),
        )
        self.opened: list = []
        self.folders_made: list = []
        self.conversation_log = _CreateCatalogue(self)


class _CreateCatalogue:
    """Only the catalogue read the derive makes; the created slots stand in memory."""

    def __init__(self, state) -> None:
        self._state = state

    def list_sessions(self):
        return []

    def read_messages_chained(self, _key):
        return []

    def get_metadata(self, _key):
        return {}


async def check_thread_create(ctx, config_file, app, dispatch, body_of) -> None:
    """§12: open a thread on a message, and it is immediately a thread with that anchor."""
    from backend import anchors
    from backend import threadnew
    from backend import transcript

    main_key = "chat-8200-1700003000"
    real_read, real_meta = transcript.read, transcript.session_meta
    real_state = app["state"]
    real_open, real_folder = threadnew.open_session, threadnew.ensure_threads_folder
    anchors_file = anchors.path_for(ctx)
    config_file.write_text(
        json.dumps({"deskRoot": DESK, "slots": {"fund": main_key}}, indent=2) + "\n"
    )
    anchors_file.unlink(missing_ok=True)
    state = CreateState(main_key)
    app["state"] = state

    def fake_read(_gw, key):
        return [dict(m) for m in MAIN_712] if key == main_key else []

    def fake_meta(_gw, key):
        if key == main_key:
            return {"agent": "tada-fund-manager", "title": "fund-manager"}
        opened = dict(state.opened_by_key()).get(key)
        return opened or {}

    # The two gateway calls are stubbed at their own seam, and ONLY those two: the
    # session-control verb and the folder create are core's own tested code, while
    # what has to be proven here is the wiring into them — which agent, which
    # folder, which caller conversation, which title. Their real signatures are
    # checked separately below, so a stub cannot hide a wrong call shape.
    minted = [NEW_THREAD, NEW_SECOND]

    async def fake_folder(gw, view, member):
        path = threadnew.threads_folder_of(member)
        # Mirrors the real function's early return, so this stub cannot make a
        # reuse look like a create. The real walk is exercised on its own below.
        found = view.folder_ids_for_path(path)
        if found:
            return sorted(found)[0]
        state.folders_made.append(path)
        fid = f"h-made-{len(state.folders_made)}"
        view.folder_paths[fid] = path
        state._f.append({"id": fid, "name": "threads", "parent_id": "h-td"})
        return fid

    async def fake_open(gw, *, caller_key, title, agent, folder_id):
        key = minted.pop(0)
        state.opened.append({"caller": caller_key, "title": title, "agent": agent,
                             "folder_id": folder_id, "key": key})
        state._s.append({"key": key, "title": title, "folder_id": folder_id,
                         "running": False, "agent": agent,
                         "created": "2026-09-14T11:02:00+00:00"})
        state._live.add(key)
        return key

    state.opened_by_key = lambda: [
        (o["key"], {"agent": o["agent"], "title": o["title"]}) for o in state.opened
    ]
    transcript.read, transcript.session_meta = fake_read, fake_meta
    threadnew.open_session, threadnew.ensure_threads_folder = fake_open, fake_folder
    try:
        # ---- input validation, before anything is created
        for label, body, status in (
            ("no body", {}, 400),
            ("no anchor", {"member_id": "fund"}, 400),
            ("anchor missing ts", {"member_id": "fund", "anchor": {"mid": "m-712-pick"}}, 400),
            ("anchor missing mid", {"member_id": "fund", "anchor": {"ts": "x"}}, 400),
            ("unknown member",
             {"member_id": "nope", "anchor": {"mid": "m", "ts": "t"}}, 404),
        ):
            resp = await dispatch("POST", "thread", body=body)
            check(f"POST /thread {label} → {status}", resp.status == status, str(resp.status))
        resp = await dispatch("POST", "thread", body={"member_id": "fund"}, user=None)
        check("POST /thread unauthenticated → 401", resp.status == 401, str(resp.status))
        check("nothing was created by a refused request",
              not state.opened and not anchors_file.exists(),
              f"{state.opened} / {anchors_file.exists()}")

        # ---- the create
        anchor = {"mid": "m-712-pick", "ts": "2026-09-14T11:00:00+00:00"}
        resp = await dispatch("POST", "thread", body={"member_id": "fund", "anchor": anchor})
        made = await body_of(resp)
        check("POST /thread returns {id, slot_key}",
              resp.status == 200 and made.get("slot_key") == NEW_THREAD
              and str(made.get("id", "")).startswith("th-fund-"),
              json.dumps(made, ensure_ascii=False))
        check("the session is opened FROM the member's own conversation",
              state.opened[-1]["caller"] == main_key, str(state.opened[-1]["caller"]))
        check("...on the member's own agent, which is what makes it a clone",
              state.opened[-1]["agent"] == "tada-fund-manager", state.opened[-1]["agent"])
        check("...filed in the member's threads folder, created because it was missing",
              state.folders_made == ["Trading Desk/threads"]
              and state.opened[-1]["folder_id"] == "h-made-1",
              f"{state.folders_made} / {state.opened[-1]['folder_id']}")
        check("the default title is the anchor message's first 40 chars",
              state.opened[-1]["title"]
              == MAIN_712[0]["content"][:threadnew.TITLE_FROM_ANCHOR],
              repr(state.opened[-1]["title"]))
        check("the id the response names is the thread's own id",
              made["id"] == f"th-fund-2026-09-14-{made['id'].rsplit('-', 1)[1]}",
              made["id"])

        # ---- it appears in /threads IMMEDIATELY, carrying the anchor passed in
        listed = await body_of(await dispatch("GET", "threads?member=fund"))
        by_key = {t["slot_key"]: t for t in listed.get("threads", [])}
        check("the new thread is in /threads right away",
              NEW_THREAD in by_key, str(sorted(by_key)))
        one = by_key.get(NEW_THREAD, {})
        check("...with the caller's own anchor, both keys, ts byte-for-byte",
              one.get("anchor") == {"main_msg": anchor["mid"], "ts": anchor["ts"],
                                    "preview": one.get("anchor", {}).get("preview")}
              and one["anchor"]["ts"] == anchor["ts"],
              json.dumps(one.get("anchor"), ensure_ascii=False))
        check("...so it DOES grow a row-level reply bar, unlike a folder-only thread",
              one.get("anchor") is not None, "")
        check("...typed as the member's own clone",
              one.get("kind") == "thread" and one.get("member") == "fund"
              and one.get("agent") == "tada-fund-manager",
              json.dumps({k: one.get(k) for k in ("kind", "member", "agent")}))
        check("...and dated by the ANCHOR, not by when the session was made",
              one.get("refs", {}).get("run_date") == "2026-09-14",
              str(one.get("refs")))
        check("no session key escapes into a field other than slot_key",
              not transcript.has_key_shape({k: v for k, v in one.items() if k != "slot_key"}),
              json.dumps({k: v for k, v in one.items() if k != "slot_key"},
                         ensure_ascii=False)[:120])

        # ---- the recorded anchor is the app's own file, and it is atomic-written
        stored = anchors.read(ctx)
        check("the anchor is recorded under the app's own data dir",
              anchors_file.name == "thread-anchors.json"
              and stored.get(NEW_THREAD, {}).get("main_msg") == anchor["mid"]
              and stored[NEW_THREAD]["ts"] == anchor["ts"],
              json.dumps(stored, ensure_ascii=False)[:140])
        check("the recorded anchor names its member, so it surfaces under that one only",
              stored[NEW_THREAD].get("member") == "fund",
              str(stored[NEW_THREAD].get("member")))

        # ---- /say reaches it
        state.delivered.clear()
        said = await body_of(
            await dispatch("POST", f"thread/{made['id']}/say", body={"text": "HBM first"})
        )
        check("/say reaches the thread just created",
              said.get("ok") is True and said.get("slot_key") == NEW_THREAD
              and state.delivered[-1] == (NEW_THREAD, "HBM first"),
              f"{json.dumps(said, ensure_ascii=False)} / {state.delivered[-1:]}")
        detail = await body_of(await dispatch("GET", f"thread/{made['id']}"))
        check("/thread/{id} opens it and agrees with the listing",
              detail == by_key[NEW_THREAD], json.dumps(detail, ensure_ascii=False)[:120])

        # ---- idempotent per anchor: a double-click must not fork the conversation
        again = await body_of(
            await dispatch("POST", "thread", body={"member_id": "fund", "anchor": anchor})
        )
        check("a second create on the SAME message returns the same thread",
              again.get("slot_key") == NEW_THREAD and again.get("id") == made["id"]
              and again.get("created") is False,
              json.dumps(again, ensure_ascii=False))
        check("...and opened no second session",
              len(state.opened) == 1, str(len(state.opened)))

        # ---- a DIFFERENT message gets its own thread, in the folder that now exists
        other = {"mid": "m-712-reply", "ts": "2026-09-14T11:01:00+00:00"}
        second = await body_of(
            await dispatch("POST", "thread",
                           body={"member_id": "fund", "anchor": other, "title": "second one"})
        )
        check("another message opens a second, distinct thread",
              second.get("slot_key") == NEW_SECOND and second.get("created") is True
              and second["id"] != made["id"],
              json.dumps(second, ensure_ascii=False))
        check("a caller-supplied title is used verbatim",
              state.opened[-1]["title"] == "second one", state.opened[-1]["title"])
        check("the threads folder is reused, not created a second time",
              state.folders_made == ["Trading Desk/threads"], str(state.folders_made))
        both = await body_of(await dispatch("GET", "threads?member=fund"))
        keys = [t["slot_key"] for t in both.get("threads", [])]
        check("both threads are listed, each with its own anchor",
              keys.count(NEW_THREAD) == 1 and keys.count(NEW_SECOND) == 1
              and len({t["anchor"]["main_msg"] for t in both["threads"]}) == 2,
              str(keys))
        check("the first anchor survived the second create's rewrite of the file",
              anchors.read(ctx).get(NEW_THREAD, {}).get("main_msg") == anchor["mid"],
              str(sorted(anchors.read(ctx))))

        # ---- §12 stays reachable when the conversation is reset out from under it
        config_file.write_text(
            json.dumps({"deskRoot": DESK, "slots": {"fund": "td-fund-1700009998"}},
                       indent=2) + "\n"
        )
        after = await body_of(await dispatch("GET", "threads?member=fund"))
        check("a created thread survives a reset of the conversation it was opened in",
              {NEW_THREAD, NEW_SECOND} <= {t["slot_key"] for t in after.get("threads", [])},
              str([t["slot_key"] for t in after.get("threads", [])]))
        check("...and keeps its anchor, because the record is the app's own",
              all(t["anchor"] is not None for t in after["threads"]
                  if t["slot_key"] in {NEW_THREAD, NEW_SECOND}),
              str([(t["slot_key"], t["anchor"]) for t in after["threads"]])[:140])
    finally:
        transcript.read, transcript.session_meta = real_read, real_meta
        threadnew.open_session, threadnew.ensure_threads_folder = real_open, real_folder
        app["state"] = real_state
        anchors_file.unlink(missing_ok=True)
        config_file.write_text(json.dumps({"deskRoot": DESK}, indent=2) + "\n")

    # ---- the two stubbed seams must match core's REAL signatures, or the stub is
    # ---- testing a call shape the gateway does not accept.
    import inspect
    try:
        from kiro_crew.dashboard.chat_folders import create_folder_record
        from kiro_crew.dashboard.session_control import SessionControlError, create_session
    except Exception as exc:  # noqa: BLE001
        check("core exposes create_session + create_folder_record", False, str(exc))
        return
    create_params = inspect.signature(create_session).parameters
    check("core's create_session accepts the kwargs this backend passes",
          {"caller_session_key", "title", "agent", "folder_id"} <= set(create_params)
          and list(create_params)[0] == "state",
          str(list(create_params)))
    folder_params = inspect.signature(create_folder_record).parameters
    check("core's create_folder_record accepts name + parent_id",
          {"name", "parent_id"} <= set(folder_params) and list(folder_params)[0] == "state",
          str(list(folder_params)))
    check("SessionControlError carries the status this backend relays",
          hasattr(SessionControlError("x"), "status")
          or "status" in inspect.signature(SessionControlError.__init__).parameters,
          "")

    # ---- the REAL folder walk, with core's create stubbed at ITS seam. Its job is
    # ---- mkdir -p over the gateway's single create path, and the two branches that
    # ---- matter are "already there" (create nothing) and "one segment missing".
    from backend import org as org_mod
    from backend import slots as slots_mod
    from kiro_crew.dashboard import chat_folders as cf_mod

    real_create = cf_mod.create_folder_record
    made: list[tuple[str, str]] = []

    async def fake_record(state, *, name, parent_id="", **_kw):
        made.append((name, parent_id))
        return {"id": f"k-{len(made)}", "name": name, "parent_id": parent_id}

    cf_mod.create_folder_record = fake_record
    try:
        desk = org_mod.find_member(Path(DESK), "lm-test-alpha")
        # Everything already present: nothing may be created.
        present = slots_mod.SlotView(slots=[], folder_paths={
            "k-td": "Trading Desk", "k-desk": "Trading Desk/Desk",
            "k-pod": "Trading Desk/Desk/test-alpha",
            "k-th": "Trading Desk/Desk/test-alpha/threads",
        })
        got = await threadnew.ensure_threads_folder(None, present, desk)
        check("ensure_threads_folder returns the existing folder and creates nothing",
              got == "k-th" and not made, f"{got} / {made}")
        # Only the leaf missing: exactly one segment is created, under the pod.
        partial = slots_mod.SlotView(slots=[], folder_paths={
            "k-td": "Trading Desk", "k-desk": "Trading Desk/Desk",
            "k-pod": "Trading Desk/Desk/test-alpha",
        })
        got = await threadnew.ensure_threads_folder(None, partial, desk)
        check("...creates only the missing segment, parented on the member's folder",
              made == [("threads", "k-pod")] and got == "k-1",
              f"{made} / {got}")
        check("...and the created id resolves in the caller's own view afterwards",
              partial.folder_ids_for_path("Trading Desk/Desk/test-alpha/threads") == {"k-1"},
              str(partial.folder_paths))
        # Nothing present: mkdir -p walks the whole path rather than dead-ending.
        made.clear()
        empty = slots_mod.SlotView(slots=[], folder_paths={})
        await threadnew.ensure_threads_folder(None, empty, desk)
        check("...walks the whole path when even the member's folder is absent",
              [n for n, _p in made] == ["Trading Desk", "Desk", "test-alpha", "threads"],
              str(made))
        # A member with no folder in the roster has nowhere to file: refused, 409.
        try:
            await threadnew.ensure_threads_folder(None, empty, {"id": "ghost"})
            check("a member with no roster folder is refused, not filed at the top level",
                  False, "no refusal")
        except threadnew.CreateRefused as exc:
            check("a member with no roster folder is refused, not filed at the top level",
                  exc.status == 409, f"{exc.status} {exc}")
    finally:
        cf_mod.create_folder_record = real_create


# ---------------------------------------------------------------------------
# rev6.1 — the threads folder as a second source (CONTRACT §11.6)
# ---------------------------------------------------------------------------
#: fund and macro share ``Trading Desk``, so they share ONE threads folder and are
#: told apart by agent; desk has its own, and a pod has its own below that. All
#: four paths are needed: the two collision shapes and the descendant trap live in
#: different pairs of them.
FOLDERS_611 = [
    {"id": "g-td", "name": "Trading Desk", "parent_id": ""},
    {"id": "g-td-th", "name": "threads", "parent_id": "g-td"},
    {"id": "g-desk", "name": "Desk", "parent_id": "g-td"},
    {"id": "g-desk-th", "name": "threads", "parent_id": "g-desk"},
    {"id": "g-pod", "name": "test-alpha", "parent_id": "g-desk"},
    {"id": "g-pod-th", "name": "threads", "parent_id": "g-pod"},
]

OWN = "chat-8001-1700001001"        # fund's own clone, folder-only
MACRO_CLONE = "chat-8002-1700001002"  # macro's clone in the SHARED threads folder
NO_AGENT = "chat-8003-1700001003"   # a clone whose agent cannot be read
BOTH = "chat-8004-1700001004"       # in the folder AND named in the conversation
DESK_TO_LM = "chat-8005-1700001005"  # desk's folder, a line-manager's agent
POD_OWN = "chat-8006-1700001006"    # one level DOWN, in the pod's own folder
GONE = "chat-8007-1700001007"       # filed, but the gateway no longer holds it
OLD_MAIN = "td-fund-1700001008"     # a reset-minted MAIN conversation, misfiled

#: The threads-folder world: ``key -> (folder_id, agent, title, running, open)``.
FILED = {
    OWN: ("g-td-th", "tada-fund-manager", "the one opened before the reset", False, True),
    MACRO_CLONE: ("g-td-th", "tada-macro-strategist", "macro's own", True, True),
    NO_AGENT: ("g-td-th", "", "agent unreadable", False, True),
    BOTH: ("g-td-th", "tada-fund-manager", "in both sources", False, True),
    DESK_TO_LM: ("g-desk-th", "tada-line-manager", "line-manager · test-alpha", False, True),
    POD_OWN: ("g-pod-th", "tada-line-manager", "opened by the pod itself", False, True),
    GONE: ("g-td-th", "tada-fund-manager", "session is already gone", False, False),
    OLD_MAIN: ("g-td-th", "tada-fund-manager", "main conversation before the reset", False, True),
}

#: A main conversation that names exactly one of the filed sessions, so the merge
#: has something to dedupe and the anchored/unanchored pair can be compared.
MAIN_611 = [
    {"role": "user", "ts": "2026-09-14T10:00:00+00:00", "meta": {"mid": "m-611-ask"},
     "content": "This one is worth opening a thread for"},
    {"role": "assistant", "ts": "2026-09-14T10:01:00+00:00", "meta": {"mid": "m-611-receipt"},
     "content": f"Opened thread `{BOTH}`; the steps are all inside it."},
]


class FolderState(StubState):
    """The gateway with clones filed in ``<member folder>/threads`` (§11.6.1)."""

    def __init__(self, main_key: str) -> None:
        slots = [
            {"key": main_key, "title": "fund-manager", "folder_id": "g-td",
             "running": False, "agent": "tada-fund-manager"},
            # desk's and the pod's own resident sessions, filed BESIDE their
            # threads folders — a member's main conversation is not a thread.
            {"key": "chat-8100-1700002001", "title": "desk-manager", "folder_id": "g-desk",
             "running": False, "agent": "tada-desk-manager"},
            {"key": "chat-8101-1700002002", "title": "line-manager · test-alpha",
             "folder_id": "g-pod", "running": False, "agent": "tada-line-manager"},
        ]
        for key, (folder, agent, title, running, is_open) in FILED.items():
            if is_open:
                slots.append({"key": key, "title": title, "folder_id": folder,
                              "running": running, "agent": agent,
                              "created": "2026-09-14T09:30:00+00:00"})
        super().__init__(
            slots=slots,
            folders=FOLDERS_611,
            live_keys=tuple(k for k, v in FILED.items() if v[4]),
        )
        # The gateway's session catalogue: what ``GET /api/chat/folders`` counts
        # per folder. An archived session appears ONLY here — it has no slot — and
        # is named by its transcript stem, which is why the derive normalises it.
        self.conversation_log = _FolderCatalogue()


class _FolderCatalogue:
    """``conversation_log`` as the folder source reads it: the session catalogue."""

    def list_sessions(self):
        return [
            {"key": f"dashboard_{key}", "folder_id": folder, "agent": agent,
             "title": title, "created": "2026-09-14T09:30:00+00:00"}
            for key, (folder, agent, title, _running, _open) in FILED.items()
        ]

    def read_messages_chained(self, _key):
        return []

    def get_metadata(self, _key):
        return {}


async def check_threads_folder(ctx, config_file, app, dispatch, body_of) -> None:
    """§11.6: the threads folder is the second source, and reset loses nothing."""
    from backend import threads as threads_mod
    from backend import transcript

    root = Path(DESK)
    real_read, real_meta = transcript.read, transcript.session_meta
    real_state = app["state"]

    # The member's main conversation after a reset: a brand-new slot whose
    # transcript is EMPTY. This is the P0 shape — S1 can find nothing at all.
    fresh_main = "td-fund-1700009999"
    config_file.write_text(
        json.dumps({"deskRoot": DESK, "slots": {"fund": fresh_main}}, indent=2) + "\n"
    )

    def read_empty(_gw, _key):
        return []

    def read_with_receipt(_gw, key):
        return [dict(m) for m in MAIN_611] if key == fresh_main else []

    def fake_meta(_gw, key):
        entry = FILED.get(key)
        if entry is None:
            return {}
        _folder, agent, title, _running, _open = entry
        # NO_AGENT is the case where neither the slot nor the header knows.
        meta = {"title": title, "created_at": "2026-09-14T09:30:00+00:00"}
        if agent:
            meta["agent"] = agent
        return meta

    transcript.session_meta = fake_meta
    try:
        # ---- 1. RESET: the conversation mentions nothing, the folder still does
        transcript.read = read_empty
        app["state"] = FolderState(fresh_main)
        payload = await body_of(await dispatch("GET", "threads?member=fund"))
        after = payload.get("threads", [])
        by_key = {t["slot_key"]: t for t in after}
        check("after a reset the empty conversation derives nothing on its own",
              read_empty(None, fresh_main) == [], "")
        check("every clone in the member's threads folder is still reachable",
              {OWN, NO_AGENT, BOTH, GONE} <= set(by_key),
              f"missing {sorted({OWN, NO_AGENT, BOTH, GONE} - set(by_key))}")
        check("a thread whose TAB was closed is reachable too — it is in the "
              "catalogue, not in the slot table",
              GONE in by_key and GONE not in {s["key"] for s in app["state"].serialize_slots()},
              json.dumps(by_key.get(GONE, {}), ensure_ascii=False)[:110])
        check("a reset-minted MAIN conversation misfiled there is NOT republished "
              "as a thread (§8.2 pins slot_key to the bare chat shape)",
              OLD_MAIN not in by_key, str(sorted(by_key)))
        check("every slot_key holds the bare chat shape the panel builds a URL from",
              all(re.fullmatch(r"chat-\d+-\d+", t["slot_key"]) for t in after),
              str([t["slot_key"] for t in after]))
        # Every filed session is in BOTH populations here — a live slot AND a
        # catalogue row naming it by its transcript stem — which is the real shape.
        # One thread each, or the stem normalisation is not collapsing them.
        check("a session in both the slot table and the catalogue is ONE thread",
              len(after) == len({t["slot_key"] for t in after})
              and len(after) == len({OWN, NO_AGENT, BOTH, GONE}),
              f"{len(after)} listed for {len({t['slot_key'] for t in after})} sessions")
        check("a folder-only thread carries NO anchor, so no row grows a reply bar",
              all(by_key[k]["anchor"] is None for k in (OWN, NO_AGENT, BOTH, GONE)),
              str({k: by_key[k]["anchor"] for k in (OWN, BOTH) if k in by_key}))
        check("it is still listed, which is the header entry's whole input",
              all(by_key[k]["id"] for k in (OWN, NO_AGENT, BOTH, GONE)),
              str(sorted(t["id"] for t in after)))

        # ---- 2. the two collision shapes: folder gives candidacy, agent gives owner
        check("a co-tenant's clone in the SHARED folder is not listed as fund's",
              MACRO_CLONE not in by_key,
              json.dumps(by_key.get(MACRO_CLONE, {}), ensure_ascii=False)[:110])
        macro = await body_of(await dispatch("GET", "threads?member=macro"))
        macro_keys = {t["slot_key"]: t for t in macro.get("threads", [])}
        check("...it is listed under macro instead, as macro's own clone",
              MACRO_CLONE in macro_keys and macro_keys[MACRO_CLONE]["kind"] == "thread"
              and macro_keys[MACRO_CLONE]["member"] == "macro",
              json.dumps(macro_keys.get(MACRO_CLONE, {}), ensure_ascii=False)[:110])
        check("a clone whose agent cannot be read is listed anyway — the folder is "
              "the declaration",
              NO_AGENT in by_key and by_key[NO_AGENT]["kind"] == "thread"
              and by_key[NO_AGENT]["member"] == "fund",
              json.dumps(by_key.get(NO_AGENT, {}), ensure_ascii=False)[:110])
        check("...and it takes the member's own agent, which the composer posts under",
              by_key.get(NO_AGENT, {}).get("agent") == "tada-fund-manager",
              str(by_key.get(NO_AGENT, {}).get("agent")))

        # ---- 3. a dispatch the owner's own folder would NOT find stays where it is
        desk = await body_of(await dispatch("GET", "threads?member=desk"))
        desk_keys = {t["slot_key"]: t for t in desk.get("threads", [])}
        check("a line-manager's session in DESK's threads folder is kept under desk",
              DESK_TO_LM in desk_keys and desk_keys[DESK_TO_LM]["kind"] == "dispatch"
              and desk_keys[DESK_TO_LM]["member"] == "lm-test-alpha",
              json.dumps(desk_keys.get(DESK_TO_LM, {}), ensure_ascii=False)[:110])
        check("a descendant folder is NOT swallowed — the pod's own clone is not desk's",
              POD_OWN not in desk_keys, str(sorted(desk_keys)))
        pod = await body_of(await dispatch("GET", "threads?member=lm-test-alpha"))
        pod_keys = {t["slot_key"]: t for t in pod.get("threads", [])}
        check("...the pod lists it itself, from its own threads folder",
              POD_OWN in pod_keys and pod_keys[POD_OWN]["kind"] == "thread",
              json.dumps(pod_keys.get(POD_OWN, {}), ensure_ascii=False)[:110])
        check("a member's resident session beside its threads folder is not a thread",
              "chat-8100-1700002001" not in desk_keys
              and "chat-8101-1700002002" not in pod_keys,
              f"{sorted(desk_keys)} / {sorted(pod_keys)}")

        # ---- 4. state is still judged by the slot, not by the filing
        check("a filed session the gateway no longer holds reads failed",
              by_key.get(GONE, {}).get("state") == "failed",
              str(by_key.get(GONE, {}).get("state")))
        check("a filed session with a turn in flight reads running",
              macro_keys.get(MACRO_CLONE, {}).get("state") == "running",
              str(macro_keys.get(MACRO_CLONE, {}).get("state")))

        # ---- 5. MERGE: the same session named in the conversation is ONE thread,
        # ---- and it is the conversation's copy that wins, because it has the anchor
        transcript.read = read_with_receipt
        merged = await body_of(await dispatch("GET", "threads?member=fund"))
        listed = merged.get("threads", [])
        both = [t for t in listed if t["slot_key"] == BOTH]
        check("a session in both sources appears exactly once",
              len(both) == 1, f"{len(both)} copies")
        check("...and it is the conversation's copy, carrying the anchor",
              bool(both) and both[0]["anchor"]
              and both[0]["anchor"]["main_msg"] == "m-611-ask",
              json.dumps(both[0]["anchor"] if both else None, ensure_ascii=False))
        check("the folder-only threads are still all there alongside it",
              {OWN, NO_AGENT, GONE} <= {t["slot_key"] for t in listed},
              str(sorted(t["slot_key"] for t in listed)))
        check("no session key escapes into any other field of a folder-sourced thread",
              not any(
                  transcript.has_key_shape({k: v for k, v in t.items() if k != "slot_key"})
                  for t in listed
              ),
              str([t["id"] for t in listed]))

        # ---- 6. the id does not depend on WHICH source found the thread (§11.6.3)
        before = {t["slot_key"]: t["id"] for t in listed}
        check("a thread keeps its id when the conversation stops mentioning it",
              all(before.get(k) == by_key.get(k, {}).get("id")
                  for k in (OWN, NO_AGENT, GONE, BOTH)),
              f"anchored {before} vs folder-only "
              f"{ {k: v['id'] for k, v in by_key.items()} }")
        check("ids run in session-creation order within the date, not mention order",
              [t["id"] for t in listed]
              == sorted((t["id"] for t in listed), key=lambda i: int(i.rsplit("-", 1)[1])),
              str([t["id"] for t in listed]))

        # ---- 7. /thread/{id} and /say reach a folder-only thread too
        only = by_key[OWN]["id"]
        detail = await body_of(await dispatch("GET", f"thread/{only}"))
        check("/thread/{id} opens a folder-only thread and names its session",
              detail.get("slot_key") == OWN and detail.get("anchor") is None,
              json.dumps(detail, ensure_ascii=False)[:120])
        app["state"].delivered.clear()
        said = await dispatch("POST", f"thread/{only}/say", body={"text": "continue"})
        check("/say into a folder-only thread lands on its own session",
              said.status == 200 and app["state"].delivered
              and app["state"].delivered[-1][0] == OWN,
              f"{said.status} {app['state'].delivered[-1:]}")

        # ---- 8. §11.6.4: gateway facts come off the injected state, not off disk
        class FakeLog:
            def __init__(self) -> None:
                self.asked: list[str] = []

            def read_messages_chained(self, key):
                self.asked.append(key)
                return [{"role": "user", "ts": "2026-09-14T09:31:00+00:00",
                         "content": "read from the gateway's log"}]

            def get_metadata(self, key):
                self.asked.append(key)
                return {"agent": "tada-fund-manager"}

        transcript.read, transcript.session_meta = real_read, real_meta
        log = FakeLog()
        gw = type("Gw", (), {"conversation_log": log, "get_slot": staticmethod(lambda _k: None)})()
        rows = transcript.read(gw, OWN)
        check("transcript.read goes through the state's OWN conversation log",
              rows and rows[0]["content"] == "read from the gateway's log"
              and f"dashboard:{OWN}" in log.asked,
              f"{rows} / {log.asked}")
        check("transcript.session_meta goes through it too",
              transcript.session_meta(gw, OWN).get("agent") == "tada-fund-manager", "")
        check("with no gateway state there is no disk fallback — it reads nothing",
              transcript.read(None, OWN) == [] and transcript.session_meta(None, OWN) == {},
              "")
        # An AST check, not a substring one: the rule is about CODE, and this
        # module's own docstring names the thing it stopped doing. Checked across
        # every backend module, so the next one cannot quietly reintroduce it.
        offenders = []
        for module in sorted((Path(__file__).parent).glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "kiro_crew.history":
                    offenders.append(f"{module.name}: imports {node.module}")
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "ConversationLog"
                ):
                    offenders.append(f"{module.name}:{node.lineno} builds ConversationLog()")
        check("no backend module resolves gateway data paths of its own (§11.6.4)",
              not offenders, str(offenders))
    finally:
        transcript.read, transcript.session_meta = real_read, real_meta
        app["state"] = real_state
        config_file.write_text(json.dumps({"deskRoot": DESK}, indent=2) + "\n")


# ---------------------------------------------------------------------------
# rev8 anchors, on the real conversation (CONTRACT §13.2)
# ---------------------------------------------------------------------------
#: The conversation the ruling was measured on. One request opened a thread and the
#: manager narrated it across four paragraphs; three of those grew a reply bar, so
#: one action read as three threads on the real machine.
REV8_MAIN = "td-fund-1789450893"
REV8_CLONE = "chat-9301-1700004001"
#: macro's and risk-pod's own resident sessions. The 09-15 seed briefs quote them as
#: routing advice inside a ``session_send`` body ("if needed, send into the risk-pod
#: standing session"), and reading that body published both as fund-manager's threads.
REV8_PHANTOMS = ("chat-9303-1700004003", "chat-9304-1700004004")


def _gateway_sessions_dir():
    """Where the gateway keeps transcripts, by its OWN configured data home."""
    from kiro_crew.config.paths import data_home  # noqa: PLC0415 — harness-only

    return data_home() / "sessions"


def _real_session(key: str):
    """``(rows, header)`` for a real session, or ``(None, {})`` when it is gone."""
    path = _gateway_sessions_dir() / f"dashboard_{key}.jsonl"
    if not path.exists():
        return None, {}
    rows, header = [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("role"):
            rows.append(row)
        elif not header:
            header = row
    return rows, header


def _named_in(row: dict, key: str) -> bool:
    """Whether this row names ``key`` in text the derive is allowed to read.

    An independent restatement of §11.5's three sources — a plain per-row test
    rather than the streaming scan under test — so it can serve as the oracle for
    where the anchor belongs.
    """
    from backend import transcript  # noqa: PLC0415 — harness-only

    role = str(row.get("role") or "")
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    if role in ("user", "assistant"):
        blobs = [str(row.get("content") or "")]
    elif role == "tool":
        blobs = [transcript.tool_input_text(row)]
        if transcript.tool_created_session(row):
            blobs.append(str(meta.get("output") or ""))
    else:
        return False
    return any(key in blob for blob in blobs)


def _expected_anchor_row(rows: list[dict], key: str):
    """The row §13.2 says ``key`` hangs under: its turn's request message.

    Computed by index scan — find the first row that names the key, then walk back
    to the nearest ``user`` row — which is deliberately a different shape from the
    production single-pass scan.
    """
    first = next((i for i, row in enumerate(rows) if _named_in(row, key)), None)
    if first is None:
        return None, None
    for j in range(first, -1, -1):
        if str(rows[j].get("role") or "") == "user":
            return rows[j], first
    return None, first


async def check_rev8_real_anchors(ctx, config_file, app, dispatch, body_of) -> None:
    """§13.2 against the real 09-15 conversation, not a stand-in for it.

    The stubbed universe cannot settle this one: the bug was three bars in a single
    real turn, and what produced it was the SHAPE of a real manager turn — narration
    between tool calls, the create's output, the send's input, the closing receipt.
    So the rows here are the gateway's own, read off the transcript, with each
    session's agent taken from its real metadata header.
    """
    from backend import transcript

    rows, _header = _real_session(REV8_MAIN)
    path = _gateway_sessions_dir() / f"dashboard_{REV8_MAIN}.jsonl"
    check("the 09-15 conversation §13.2 was measured on is readable", bool(rows), str(path))
    if not rows:
        return

    # Every key it names, with the agent its OWN metadata header reports — so the
    # classification here is the real one and nothing is asserted into being.
    named: dict[str, dict] = {}
    for row in rows:
        for key in transcript.MENTIONED_KEY.findall(
            " ".join(
                [
                    str(row.get("content") or ""),
                    str((row.get("meta") or {}).get("input") or ""),
                    str((row.get("meta") or {}).get("output") or ""),
                ]
            )
        ):
            if key in named:
                continue
            _krows, kheader = _real_session(key)
            named[key] = {
                "agent": str(kheader.get("agent") or ""),
                "title": str(kheader.get("title") or ""),
                "rows": _krows or [],
            }

    real_read, real_meta = transcript.read, transcript.session_meta
    real_state = app["state"]
    config_file.write_text(
        json.dumps({"deskRoot": DESK, "slots": {"fund": REV8_MAIN}}, indent=2) + "\n"
    )
    slots = [{"key": REV8_MAIN, "title": "fund-manager", "folder_id": "r-td",
              "running": False, "agent": "tada-fund-manager"}]
    for key, facts in named.items():
        if facts["agent"]:
            slots.append({"key": key, "title": facts["title"], "folder_id": "r-other",
                          "running": False, "agent": facts["agent"]})
    state = StubState(
        slots=slots,
        # No folder named `Trading Desk/threads`, so S2 finds nothing and what is
        # under test is the conversation scan alone.
        folders=[{"id": "r-td", "name": "Trading Desk", "parent_id": ""},
                 {"id": "r-other", "name": "Somewhere else", "parent_id": ""}],
        live_keys=tuple([REV8_MAIN] + list(named)),
    )
    app["state"] = state

    def fake_read(_gw, key):
        if key == REV8_MAIN:
            return [dict(m) for m in rows]
        return [dict(m) for m in named.get(key, {}).get("rows", [])]

    def fake_meta(_gw, key):
        if key == REV8_MAIN:
            return {"agent": "tada-fund-manager", "title": "fund-manager"}
        facts = named.get(key)
        return {"agent": facts["agent"], "title": facts["title"]} if facts else {}

    transcript.read, transcript.session_meta = fake_read, fake_meta
    try:
        payload = await body_of(await dispatch("GET", "threads?member=fund"))
        found = payload.get("threads", [])

        mentions = [i for i, row in enumerate(rows) if _named_in(row, REV8_CLONE)]
        check("the real turn names that one thread several times over",
              len(mentions) >= 3, f"named in rows {mentions}")
        copies = [t for t in found if t["slot_key"] == REV8_CLONE]
        check("chat-1503 produces exactly ONE anchor on the real conversation",
              len(copies) == 1, f"{len(copies)} copies of {[t['id'] for t in copies]}")

        # ---- §13.2's field ruling, on the two real phantoms it was made for
        listed = {t["slot_key"] for t in found}
        quoted_only = []
        for phantom in REV8_PHANTOMS:
            in_body = any(
                phantom in str(json.loads(str((row.get("meta") or {}).get("input") or "{}"))
                               .get("message") or "")
                for row in rows
                if row.get("role") == "tool"
                and transcript.tool_name(row) == "session_send"
                and str((row.get("meta") or {}).get("input") or "").strip().startswith("{")
            )
            addressed = any(
                phantom in transcript.tool_input_text(row)
                for row in rows if row.get("role") == "tool"
            )
            in_prose = any(
                phantom in str(row.get("content") or "")
                for row in rows if row.get("role") in ("user", "assistant")
            )
            if in_body and not addressed and not in_prose:
                quoted_only.append(phantom)
        check("both 09-15 phantoms really are quoted-in-a-seed-body and nothing else",
              sorted(quoted_only) == sorted(REV8_PHANTOMS), str(quoted_only))
        check("neither is derived as a thread any more (§13.2 ruling)",
              not (set(REV8_PHANTOMS) & listed),
              f"still listed: {sorted(set(REV8_PHANTOMS) & listed)}")
        check("and the sessions the manager DID open are still there",
              {REV8_CLONE, "chat-9302-1700004002"} <= listed, str(sorted(listed)))
        if not copies:
            return

        anchor = copies[0]["anchor"]
        want, first_at = _expected_anchor_row(rows, REV8_CLONE)
        check("its anchor is a USER message, not the manager's narration",
              bool(anchor) and bool(want)
              and anchor["main_msg"] == (want.get("meta") or {}).get("mid")
              and str(want.get("role")) == "user",
              json.dumps({"anchor": anchor, "row": str(want.get("role")) if want else None},
                         ensure_ascii=False)[:160])
        check("the anchored row sits ABOVE the first mention, i.e. the request that "
              "started the turn",
              bool(want) and rows.index(want) < first_at,
              f"request row {rows.index(want) if want else '?'} < first mention {first_at}")
        check("its ts is that row's ts, byte for byte",
              bool(anchor) and anchor["ts"] == (want or {}).get("ts"),
              f"{(anchor or {}).get('ts')!r} vs {(want or {}).get('ts')!r}")
        check("its preview quotes the reader's own question",
              bool(anchor) and anchor["preview"]
              and anchor["preview"] in str((want or {}).get("content") or ""),
              repr((anchor or {}).get("preview")))

        # The measured regression: before rev8 every one of these sat on an
        # assistant row, and three of them inside one turn.
        by_mid = {(r.get("meta") or {}).get("mid"): str(r.get("role") or "")
                  for r in rows if (r.get("meta") or {}).get("mid")}
        landed = {t["anchor"]["main_msg"]: by_mid.get(t["anchor"]["main_msg"], "?")
                  for t in found if t["anchor"]}
        check("no thread on the real conversation anchors to an assistant row",
              landed and all(role == "user" for role in landed.values()),
              json.dumps(landed, ensure_ascii=False))
        shared = [mid for mid, count in
                  ((m, sum(1 for t in found if t["anchor"] and t["anchor"]["main_msg"] == m))
                   for m in landed) if count > 1]
        check("§13.2 rule 3: one request may hold several threads, one bar each",
              all(
                  len({t["slot_key"] for t in found
                       if t["anchor"] and t["anchor"]["main_msg"] == mid})
                  == sum(1 for t in found if t["anchor"] and t["anchor"]["main_msg"] == mid)
                  for mid in shared
              ),
              f"requests holding more than one thread: {shared}")
    finally:
        transcript.read, transcript.session_meta = real_read, real_meta
        app["state"] = real_state
        config_file.write_text(json.dumps({"deskRoot": DESK}, indent=2) + "\n")


def _compiled(routes: list[AppRoute]):
    """Mirror RouteRegistry.register_app_routes' compilation of an AppRoute list."""
    from kiro_crew.apps.route_registry import _compile_pattern, _has_params, _RegisteredRoute

    out = []
    for route in routes:
        path = route.path if route.path.startswith("/") else f"/{route.path}"
        rr = _RegisteredRoute(
            method=route.method.upper(), path=path, handler=route.handler,
            has_params=_has_params(path),
        )
        if rr.has_params:
            rr.compiled, rr.param_names = _compile_pattern(path)
        out.append(rr)
    return out


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
