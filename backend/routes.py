"""Trading Desk backend — in-process routes for an EXTERNAL KiroCrew app.

``register_routes(ctx)`` returns ``list[AppRoute]`` with paths relative to
``/api/apps/trading-desk``; each handler takes ``(request, ctx)``. The manifest
declares this through ``backend.hooks.routes`` only — setting ``backend.routes``
would switch the gateway to the standalone-process proxy, whose stubs shadow
these handlers.

Routes (ARCHITECTURE.md §2):

    GET  /org                 desk roster, duty text, live state, chat slot
    GET  /run?date=           one run as dispatch chain + per-pod lanes
    GET  /deskconfig          books + sectors + account constraints
    POST /config/validate     candidate config, nothing written
    POST /config/apply        validated write-back, atomic
    GET  /artifacts?date=     produced-file tree, grouped
    GET  /file?path=          text of one file inside deskRoot (403 outside)
    POST /member/{id}/reset   bind a member to a fresh session, old one kept
    GET  /threads?member=     the threads that member's conversation mentions (§11)
    GET  /thread/{id}         one thread's metadata + its slot_key
    POST /thread              open a thread on one message (§12)
    POST /thread/{id}/say     say a line into that thread's own session
    GET  /health              deskRoot resolution + which data sources are present

The config READ is ``/deskconfig``, not ``/config``: the gateway owns
``/api/apps/{name}/config`` and registers it before the catch-all this app's
routes dispatch from, so a ``/config`` route here would never be reached.

Thread payloads DO carry a session key — rev6 (§11.2) makes the panel read
``/api/chat/slots/{slot_key}`` and the composer post ``/api/chat {slot, agent}``,
which reverses the M2 red line. The narrower invariant that replaces it: a key
appears in ``slot_key`` and nowhere else, so ``anchor.preview`` stays scrubbed.

Every read is anchored at deskRoot from ``data/config.json``; a path resolving
outside it is a 403. Unauthenticated callers get 401.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from kiro_crew.apps.route_registry import AppRoute

from . import artifacts as artifacts_mod
from . import configio, deskdata, org, reset, runview, say, slots, threadnew, threads
from .paths import BadInput, app_root, atomic_write_text, desk_root, valid_date
from .respond import err, guarded, log, ok

#: Where a browser-side crash report is written, inside the app's own data dir.
_CLIENT_ERROR_FILE = "client-errors.jsonl"
#: Reports retained. A crash loop overwrites its own history rather than growing.
_CLIENT_ERROR_KEEP = 20
#: Per-field ceiling. A stack is worth keeping; an unbounded one is not.
_CLIENT_ERROR_FIELD = 8000


def _date_param(request: web.Request) -> str | None:
    """Read ``?date=``, rejecting anything that is not a literal ``YYYY-MM-DD``.

    The date becomes a path segment (``runs/{date}``), so it is validated as data
    before it can reach the filesystem.
    """
    raw = request.query.get("date")
    if raw is None or not raw.strip():
        return None
    if not valid_date(raw.strip()):
        raise BadInput("date must be YYYY-MM-DD")
    return raw.strip()


async def _json_body(request: web.Request) -> Any:
    try:
        return await request.json()
    except Exception as exc:  # noqa: BLE001 — any decode failure is a 400
        raise configio.ConfigError(f"invalid JSON body — {exc}") from exc


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


@guarded
async def get_org(request: web.Request, ctx: Any) -> web.Response:
    root = desk_root(ctx)
    date = _date_param(request)
    # One snapshot of the gateway's live slots + folder tree, taken on the loop;
    # the assembly itself is a pure function over plain data, off the loop.
    view = await slots.snapshot(request.app.get("state"))
    payload = await asyncio.to_thread(org.build, root, ctx, view, date)
    return ok(payload)


@guarded
async def get_run(request: web.Request, ctx: Any) -> web.Response:
    root = desk_root(ctx)
    date = _date_param(request) or deskdata.today()
    return ok(await runview.build(root, date))


@guarded
async def get_deskconfig(request: web.Request, ctx: Any) -> web.Response:
    return ok(await asyncio.to_thread(configio.read, desk_root(ctx)))


@guarded
async def post_config_validate(request: web.Request, ctx: Any) -> web.Response:
    try:
        body = await _json_body(request)
        return ok(await configio.validate(desk_root(ctx), body))
    except configio.ConfigError as exc:
        return web.json_response(
            {"ok": False, "errors": [str(exc)], "warnings": [], "diff": ""}, status=400
        )


@guarded
async def post_config_apply(request: web.Request, ctx: Any) -> web.Response:
    try:
        body = await _json_body(request)
        payload, status = await configio.apply(
            desk_root(ctx), body, getattr(ctx, "data_dir", None)
        )
        return web.json_response(payload, status=status)
    except configio.ConfigError as exc:
        return web.json_response({"ok": False, "errors": [str(exc)]}, status=400)


@guarded
async def get_artifacts(request: web.Request, ctx: Any) -> web.Response:
    root = desk_root(ctx)
    return ok(await asyncio.to_thread(artifacts_mod.build, root, _date_param(request)))


@guarded
async def get_file(request: web.Request, ctx: Any) -> web.Response:
    root = desk_root(ctx)
    try:
        text, relative = await asyncio.to_thread(
            artifacts_mod.read_file, root, request.query.get("path")
        )
    except FileNotFoundError as exc:
        return err(f"not found: {exc}", 404)
    except ValueError as exc:
        return err(str(exc), 413)
    return web.Response(
        text=text,
        content_type="text/plain",
        charset="utf-8",
        headers={"X-Desk-Path": relative},
    )


@guarded
async def post_client_error(request: web.Request, ctx: Any) -> web.Response:
    """``POST /clienterror`` — record a browser-side crash where it can be read.

    The host's error card shows ``error.message`` and nothing else, and the message
    a MINIFIED host component throws ("t is not a function") names nothing anyone
    can act on: the stack that would identify it lives in the browser and nowhere
    else. So the app writes it down rather than asking a reader to copy it out of a
    console -- a person on another machine cannot hand over a console the way they
    can hand over a screenshot.

    Bounded on both sides: an oversized report is truncated rather than refused,
    and the file keeps only the most recent entries, so a crash loop cannot fill
    the disk.
    """
    data_dir = getattr(ctx, "data_dir", None)
    if data_dir is None:
        return err("no data directory to record into", 503)
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        raise BadInput("body must be JSON")
    if not isinstance(payload, dict):
        raise BadInput("body must be a JSON object")

    entry = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message": str(payload.get("message") or "")[:_CLIENT_ERROR_FIELD],
        "stack": str(payload.get("stack") or "")[:_CLIENT_ERROR_FIELD],
        "componentStack": str(payload.get("componentStack") or "")[:_CLIENT_ERROR_FIELD],
        "where": str(payload.get("where") or "")[:200],
        "lang": str(payload.get("lang") or "")[:20],
        "hostKit": bool(payload.get("hostKit")),
    }
    path = Path(data_dir) / _CLIENT_ERROR_FILE
    await asyncio.to_thread(_append_client_error, path, entry)
    log.warning("trading-desk client crash: %s (%s)", entry["message"], entry["where"])
    return ok({"recorded": True, "path": str(path)})


def _append_client_error(path: Path, entry: dict[str, Any]) -> None:
    """Append one report, keeping only the most recent ``_CLIENT_ERROR_KEEP``."""
    line = json.dumps(entry, ensure_ascii=False)
    try:
        old = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        old = []
    kept = [ln for ln in old if ln.strip()][-(_CLIENT_ERROR_KEEP - 1):]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, "\n".join([*kept, line]) + "\n")


@guarded
async def post_member_reset(request: web.Request, ctx: Any) -> web.Response:
    """Bind a member to a brand-new session, leaving the old one as history."""
    member_id = str(request.match_info.get("id") or "")
    root = desk_root(ctx)
    if await asyncio.to_thread(org.find_member, root, member_id) is None:
        return err(f"no such member: {member_id}", 404)

    view = await slots.snapshot(request.app.get("state"))
    previous = await asyncio.to_thread(org.current_slot_key, root, ctx, view, member_id)
    try:
        payload = await asyncio.to_thread(reset.reset, ctx, member_id, previous)
    except reset.BadMember as exc:
        return err(str(exc), 400)
    log.info(
        "trading-desk reset %s: %s -> %s", member_id, previous, payload["slot_key"]
    )
    return ok(payload)


@guarded
async def get_threads(request: web.Request, ctx: Any) -> web.Response:
    """``/threads?member=`` — the threads that member's main conversation mentions.

    ``?date=`` filters; omitting it returns EVERY thread, because the reply bar
    hangs on its anchor message wherever that sits in the scroll (rev6 §11.2).
    """
    member_id = (request.query.get("member") or "").strip()
    if not member_id:
        raise BadInput("member is required")
    root = desk_root(ctx)
    if await asyncio.to_thread(org.find_member, root, member_id) is None:
        return err(f"no such member: {member_id}", 404)
    date = _date_param(request)
    gw = request.app.get("state")
    view = await slots.snapshot(gw)
    return ok(
        await asyncio.to_thread(
            threads.list_threads, root, ctx, view, member_id, date, gw
        )
    )


@guarded
async def get_thread(request: web.Request, ctx: Any) -> web.Response:
    """``/thread/{id}`` — the thread's metadata plus its ``slot_key`` (rev6 §11.2).

    No entries: the panel renders that session's own live transcript through
    ``/api/chat/slots/{slot_key}``, which is same-origin and already authorised.
    """
    thread_id = str(request.match_info.get("id") or "")
    root = desk_root(ctx)
    gw = request.app.get("state")
    view = await slots.snapshot(gw)
    payload = await asyncio.to_thread(threads.detail, root, ctx, view, thread_id, gw)
    if payload is None:
        return err(f"no such thread: {thread_id}", 404)
    return ok(payload)


@guarded
async def post_thread(request: web.Request, ctx: Any) -> web.Response:
    """``POST /thread`` — open a thread on one message (§12).

    Body ``{member_id, anchor: {mid, ts}, title?}``. Slack parity: the anchor is
    an INPUT, because the user picked the row — unlike §11.6's two sources, which
    each derive what they can see. The session is opened through the gateway's own
    session-control verb and filed in the member's ``threads`` folder, so it is
    found by that folder source from the next request on; the anchor is recorded in
    the app's own data dir, since no gateway field holds "the message this session
    hangs under".

    Idempotent per anchor: a second call on the same message returns the thread
    already opened on it, so a double-click cannot fork one conversation into two.
    """
    try:
        body = await _json_body(request)
    except configio.ConfigError as exc:
        return err(str(exc), 400)
    root = desk_root(ctx)
    gw = request.app.get("state")
    view = await slots.snapshot(gw)
    try:
        payload = await threadnew.create(root, ctx, gw, view, body)
    except threadnew.CreateRefused as exc:
        return err(str(exc), exc.status)
    log.info(
        "trading-desk thread open %s -> %s (created=%s)",
        payload["id"], payload["slot_key"], payload["created"],
    )
    return ok(payload)


@guarded
async def post_thread_say(request: web.Request, ctx: Any) -> web.Response:
    """``/thread/{id}/say`` — a line typed in a thread goes to the thread's own slot.

    rev6: talking in a thread is talking to the clone in it, so the target is the
    thread's session, not a search for whoever looks busiest.
    """
    thread_id = str(request.match_info.get("id") or "")
    try:
        body = await _json_body(request)
    except configio.ConfigError as exc:
        return err(str(exc), 400)
    text = (body or {}).get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return err("text is required", 400)

    root = desk_root(ctx)
    gw = request.app.get("state")
    view = await slots.snapshot(gw)
    found = await asyncio.to_thread(threads.target, root, ctx, view, thread_id, gw)
    if found is None:
        return err(f"no such thread: {thread_id}", 404)
    member_id, slot_key = found
    try:
        started = await say.deliver(gw, slot_key, text)
    except say.SayError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=exc.status)
    log.info("trading-desk thread say %s -> %s (started=%s)", thread_id, member_id, started)
    return ok(
        {
            "ok": True,
            "delivered_to": member_id,
            "started": started,
            # rev6 exposes the key deliberately (§11.2), so the UI can keep the
            # panel and this reply pointed at the same session.
            "slot_key": slot_key,
        }
    )


@guarded
async def get_health(request: web.Request, ctx: Any) -> web.Response:
    """What the backend resolved and which optional inputs the other tracks landed."""
    root = desk_root(ctx)
    today = deskdata.today()
    return ok(
        {
            "ok": True,
            "deskRoot": str(root),
            "deskRootExists": root.is_dir(),
            "appRoot": str(app_root()),
            "sources": {
                "sectors.yaml": (root / "sectors.yaml").is_file(),
                "books.yaml": (root / "books.yaml").is_file(),
                "engine/validate_config.py": (root / "engine" / "validate_config.py").is_file(),
                "crews/members.json": (app_root() / "crews" / "members.json").is_file(),
                "scripts/desk_events.py": (app_root() / "scripts" / "desk_events.py").is_file(),
                f"runs/{today}/events.jsonl": deskdata.events_path(root, today).is_file(),
            },
            "pods": sorted(deskdata.pods(root)),
            "dates": deskdata.available_dates(root)[:10],
        }
    )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def register_routes(ctx: Any) -> list[AppRoute]:
    """Declare this app's HTTP surface. Called once per enable / gateway start."""
    routes = [
        AppRoute("GET", "/org", get_org),
        AppRoute("GET", "/run", get_run),
        # NOT "/config": the gateway registers its own GET/PUT
        # /api/apps/{name}/config (which serves data/config.json) on the router
        # BEFORE the RouteRegistry catch-all, so aiohttp resolves that one first
        # and an app route on /config is never dispatched. The POSTs below are on
        # different paths and are not shadowed.
        AppRoute("GET", "/deskconfig", get_deskconfig),
        AppRoute("POST", "/config/validate", post_config_validate),
        AppRoute("POST", "/config/apply", post_config_apply),
        AppRoute("GET", "/artifacts", get_artifacts),
        AppRoute("GET", "/file", get_file),
        AppRoute("POST", "/clienterror", post_client_error),
        AppRoute("POST", "/member/{id}/reset", post_member_reset),
        AppRoute("GET", "/threads", get_threads),
        AppRoute("POST", "/thread", post_thread),
        AppRoute("GET", "/thread/{id}", get_thread),
        AppRoute("POST", "/thread/{id}/say", post_thread_say),
        AppRoute("GET", "/health", get_health),
    ]
    log.info(
        "trading-desk backend: %d routes, deskRoot=%s", len(routes), desk_root(ctx)
    )
    return routes
