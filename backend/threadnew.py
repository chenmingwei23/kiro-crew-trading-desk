"""``POST /thread`` — open a thread on any message (CONTRACT §12).

Slack parity: the user picks a message and gets a thread on it, so the anchor is
an INPUT here, not something derived. That is the whole difference from §11.6's
two sources — a mention is discovered in the transcript and a folder session has
no message at all, while a thread created this way knows exactly which row it
hangs under because the person clicked it.

Two halves, and they are deliberately separate:

* the SESSION is created through the gateway's own ``session_control`` verb — the
  same function the ``session_create`` MCP tool reaches over HTTP — so every gate
  it applies (caller eligibility, workspace inheritance, agent/workspace binding,
  persist-at-birth, filing before the first broadcast frame) applies here too and
  none of it is reimplemented. Requires the member's own conversation to be OPEN,
  which it is by construction: the anchor is a message the user is looking at in
  it.
* the ANCHOR is recorded in the APP's own ``data/thread-anchors.json``. It cannot
  live in gateway state — no gateway field means "the message this session hangs
  under" — and it must not be written into the member's conversation either
  (§11.5.1 ruled out clone→main posting, and the anchor is the user's own message,
  not a receipt). This is the app's own data dir, the same file space
  ``config.json`` already occupies; §11.6.4 forbids resolving GATEWAY data paths,
  which this is not.

Creating is idempotent per anchor: a second call on the same message returns the
thread already opened on it rather than a second session. A double-click on a
reply bar must not fork the conversation in two.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import anchors, org, transcript
from .respond import log
from .slots import SlotView
from .threads import THREADS_FOLDER, agents_by_member, threads_folder_of

#: §12: the default title is the anchor message's opening, so a thread is named
#: after the thing it is about without the user having to type anything.
TITLE_FROM_ANCHOR = 40


class CreateRefused(Exception):
    """The create cannot proceed. Carries the HTTP status the handler should use."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# input
# ---------------------------------------------------------------------------


def parse_body(body: Any) -> tuple[str, str, str, str]:
    """``(member_id, main_msg, ts, title)`` out of the request body.

    Both anchor keys are required and neither is defaulted: ``main_msg`` is the
    durable identity the ledger will key on and ``ts`` is what the SPA actually
    matches a rendered row by, so a create that supplied only one would hand back
    a thread the UI cannot place (§8.2 rev2).
    """
    if not isinstance(body, dict):
        raise CreateRefused("body must be a JSON object")
    member_id = str(body.get("member_id") or "").strip()
    if not member_id:
        raise CreateRefused("member_id is required")
    anchor = body.get("anchor")
    if not isinstance(anchor, dict):
        raise CreateRefused("anchor is required, as {mid, ts}")
    main_msg = str(anchor.get("mid") or "").strip()
    ts = str(anchor.get("ts") or "").strip()
    if not main_msg or not ts:
        raise CreateRefused("anchor needs both mid and ts")
    title = body.get("title")
    if title is not None and not isinstance(title, str):
        raise CreateRefused("title must be a string")
    return member_id, main_msg, ts, (title or "").strip()


def title_for(gw: Any, main_key: str | None, main_msg: str, ts: str, given: str) -> str:
    """The thread's name: the caller's, else the anchor message's opening.

    Read off the anchor row rather than taken from the request so the UI does not
    have to send the text back — and scrubbed by ``preview``, which is what keeps a
    session key out of a title (a title is persisted to the metadata line and
    pushed to every dashboard client).
    """
    if given:
        return given[:200]
    for message in transcript.read(gw, main_key):
        if transcript.mid_of(message) == main_msg or str(message.get("ts") or "") == ts:
            text = transcript.preview(
                str(message.get("content") or ""), limit=TITLE_FROM_ANCHOR
            )
            if text:
                return text
            break
    return "new thread"


# ---------------------------------------------------------------------------
# the gateway side
# ---------------------------------------------------------------------------


async def ensure_threads_folder(gw: Any, view: SlotView, member: dict[str, Any]) -> str:
    """The folder id of ``<member folder>/threads``, creating what is missing.

    ``create_session`` refuses an unknown folder and cannot create one, and the
    folder is where §11.6's second source then FINDS this thread — so a create
    that skipped the filing would produce a thread that disappears from the app
    the moment the conversation scrolls out of the anchor's reach.

    Segments are created through the gateway's own single folder-create path, so
    the validation, app-ownership isolation and store serialisation are the ones
    every other folder gets. ``request_app`` is empty on purpose: this runs inside
    a request the person themselves made from the dashboard, and an app-owned
    folder would be isolated out of the sidebar they need to see it in.
    """
    path = threads_folder_of(member)
    if not path:
        raise CreateRefused(
            f"member {member.get('id')!r} has no folder in the roster, so it has "
            "nowhere to file a thread",
            status=409,
        )
    existing = view.folder_ids_for_path(path)
    if existing:
        return sorted(existing)[0]

    try:
        from kiro_crew.dashboard.chat_folders import (  # noqa: PLC0415 — gateway-only
            create_folder_record,
        )
    except Exception as exc:  # noqa: BLE001
        raise CreateRefused(
            "this gateway does not expose folder creation, so the thread cannot be filed",
            status=503,
        ) from exc

    # Walk the path so a member folder that does not exist yet is created too,
    # rather than dead-ending the create. Same mkdir -p semantics the
    # ``session_create`` tool's own `folder` argument documents.
    parent = ""
    walked = ""
    for segment in [s for s in path.split("/") if s]:
        walked = f"{walked}/{segment}" if walked else segment
        found = view.folder_ids_for_path(walked)
        if found:
            parent = sorted(found)[0]
            continue
        try:
            record = await create_folder_record(gw, name=segment, parent_id=parent)
        except Exception as exc:  # noqa: BLE001
            raise CreateRefused(
                f"could not create the folder {walked!r} to file this thread: {exc}",
                status=502,
            ) from exc
        parent = str(record.get("id") or "")
        if not parent:
            raise CreateRefused(
                f"the gateway created {walked!r} but reported no id", status=502
            )
        # So the next segment resolves against what was just created, and so the
        # caller's own SlotView agrees with the tree from here on.
        view.folder_paths[parent] = walked
    return parent


async def open_session(
    gw: Any, *, caller_key: str, title: str, agent: str, folder_id: str
) -> str:
    """The new session's slot key, via the gateway's own session-control verb.

    ``caller_key`` is the member's OWN conversation — the one the anchor message
    lives in. That is what makes the child the member's: ``create_session``
    inherits the caller's workspace (the memory boundary) and defaults the agent
    to the caller's own, so the clone lands on the same memory store the conductor
    is already using, which is §11.3's whole premise.
    """
    try:
        from kiro_crew.dashboard.session_control import (  # noqa: PLC0415 — gateway-only
            SessionControlError,
            create_session,
        )
    except Exception as exc:  # noqa: BLE001
        raise CreateRefused(
            "this gateway does not expose session creation", status=503
        ) from exc

    try:
        result = await create_session(
            gw, caller_session_key=caller_key, title=title, agent=agent,
            folder_id=folder_id,
        )
    except SessionControlError as exc:
        # Relayed verbatim rather than flattened to one message: its codes name
        # real, separable states the user can act on — session control disabled in
        # config, the member's own conversation not open, an ineligible caller.
        raise CreateRefused(
            f"the gateway refused to open the session: {exc}",
            status=getattr(exc, "status", 409) or 409,
        ) from exc
    key = str((result or {}).get("target") or "")
    if not key:
        raise CreateRefused("the gateway opened no session", status=502)
    return key


# ---------------------------------------------------------------------------
# the endpoint's body
# ---------------------------------------------------------------------------


async def create(
    root: Path, ctx: Any, gw: Any, view: SlotView, body: Any
) -> dict[str, Any]:
    """``POST /thread`` — open a thread on one message and return it.

    Returns ``{"id", "slot_key", "created"}``. ``created`` is false when the
    message already had a thread, which is the idempotent answer rather than a
    second session on the same row.
    """
    from . import threads as threads_mod  # noqa: PLC0415 — cycle: threads imports us not

    member_id, main_msg, ts, given_title = parse_body(body)
    member = org.find_member(root, member_id)
    if member is None:
        raise CreateRefused(f"no such member: {member_id}", status=404)

    agent = agents_by_member(root).get(member_id, "")
    if not agent:
        raise CreateRefused(
            f"member {member_id!r} declares no agent, so a clone has nothing to run",
            status=409,
        )

    main_key = org.current_slot_key(root, ctx, view, member_id)
    if not main_key:
        raise CreateRefused(
            f"member {member_id!r} has no conversation to open a thread from", status=409
        )

    already = anchors.find(ctx, member_id, main_msg)
    if already:
        found = _find_by_slot(threads_mod, root, ctx, view, member_id, already, gw)
        if found is not None:
            return {"id": found["id"], "slot_key": already, "created": False}
        # The record survives a session that does not. Fall through and open a new
        # one rather than reporting a thread the user cannot reach.
        log.info("trading-desk: recorded anchor for %s names a session that is gone",
                 already)

    folder_id = await ensure_threads_folder(gw, view, member)
    title = title_for(gw, main_key, main_msg, ts, given_title)
    slot_key = await open_session(
        gw, caller_key=main_key, title=title, agent=agent, folder_id=folder_id
    )

    anchors.record(
        ctx,
        slot_key,
        {
            "member": member_id,
            "main_msg": main_msg,
            # Stored VERBATIM: the SPA matches a rendered row on this string, so
            # reformatting it here would make the anchor stop matching while still
            # looking correct (§8.2 rev2).
            "ts": ts,
            "preview": transcript.preview(title),
        },
    )

    # The new slot is already in the gateway's table (create_session publishes it
    # before returning), but not in the snapshot this request took, so the derive
    # would not see it. Refreshing the view is what makes "appears immediately in
    # /threads" true for THIS response rather than the next poll.
    from . import slots as slots_mod  # noqa: PLC0415

    fresh = await slots_mod.snapshot(gw)
    fresh.folder_paths.setdefault(folder_id, threads_folder_of(member))
    found = _find_by_slot(threads_mod, root, ctx, fresh, member_id, slot_key, gw)
    if found is None:
        raise CreateRefused(
            "the session was opened but does not derive as a thread; it is in the "
            f"sidebar as {slot_key}",
            status=500,
        )
    return {"id": found["id"], "slot_key": slot_key, "created": True}


def _find_by_slot(
    threads_mod: Any,
    root: Path,
    ctx: Any,
    view: SlotView,
    member_id: str,
    slot_key: str,
    gw: Any,
) -> dict[str, Any] | None:
    for thread in threads_mod.derive(root, ctx, view, member_id, gw):
        if thread["slot_key"] == slot_key:
            return thread
    return None


__all__ = ["THREADS_FOLDER", "CreateRefused", "create"]
