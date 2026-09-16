"""Threads — the sessions a conductor opened, found by key-mention (CONTRACT §11).

rev6 replaced the model. A thread is no longer a derived summary of a dispatch;
it is **a session whose agent is the conductor's own** — the conductor opens it
with ``session_create``, seeds the topic, and answers one line in the main
conversation carrying the key. So this module does not fold a timeline any more.
It answers three questions about a member's main conversation:

* which sessions does it mention — ``chat-<n>-<ts>`` bare, or prefixed as
  ``dashboard:chat-<n>-<ts>`` / ``dashboard_chat-<n>-<ts>``, normalised to the bare
  key so the two spellings are one thread (§11.5.2) — plus every session a
  ``session_create`` in it actually opened, since rev6.1 makes the MECHANISM the
  trigger rather than the manager remembering to quote the key,
* what is each of those sessions (the member's own agent → its **thread clone**;
  another member's agent → a **dispatch** session; anything else → not ours), and
* which message does each one hang under — ONE row per thread, and the row is the
  user message that asked for the work rather than the manager's narration of
  doing it (§13.2).

The panel's contents are no longer this module's business: the UI reads
``/api/chat/slots/{slot_key}`` and renders the clone's own live transcript
(§11.2). That is why ``slot_key`` and ``agent`` are now fields — the composer
posts ``/api/chat {slot, agent}`` — and it **reverses the M2 red line** that kept
every key out of these payloads. The narrower invariant that replaces it: a key
appears in ``slot_key`` and nowhere else, which is why ``anchor.preview`` is still
scrubbed.

Classification is by AGENT, never by folder or title, and that is what makes the
scan safe on a real transcript: a main conversation mentions dozens of unrelated
session keys (a pasted session list, an injected memory block), and every one of
them fails the agent test.

rev6.1 adds a SECOND source, because the first one has a cliff: reset a member's
main conversation and the new one mentions nothing, so every thread it had
becomes unreachable inside the app while the clone sessions are all still alive
in ``<member folder>/threads``. So that folder is read too, and the two are
merged on ``slot_key`` with the conversation winning — its copy is the one that
carries an anchor. A folder-only thread has ``anchor: null``: no reply bar under
any row, but it still reaches the user through the header's 「进行中的工作」 entry
(§11.6.2). The agent gate is looser on that side, deliberately — being filed in
the folder IS the declaration, whereas a key in prose is just text.

Identity: ``th-{member}-{date}-{seq}``, with ``date`` the anchor message's local
date (a folder-only thread uses the session's creation date) and ``seq`` the
session's place in CREATION order within that date — not its place in mention
order, so the same thread gets the same id whichever source found it and one
reset does not renumber a member's whole list (§11.6.3). Scoping ``seq`` per date
is what keeps it stable under rotation: dropping an old day removes that day's
threads instead of renumbering every later one.

Every gateway fact — the slot table, the folder tree, a session's messages, its
metadata header — arrives through the state object the gateway injects; this
module resolves no gateway path of its own (§11.6.4).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import anchors, org, transcript
from .respond import log
from .slots import SlotView

_ID = re.compile(r"^th-([a-z0-9-]+)-(\d{4}-\d{2}-\d{2})-(\d{1,3})$")

#: The subfolder a conductor files its clones in (§11.5.3), under the member's own
#: ``slot_hint.folder``. This is the second derive source's whole locator.
THREADS_FOLDER = "threads"

#: Roles whose own text is read, and which a reply bar may hang under. A ``tool``
#: row is not one: its INPUT is scanned (see ``_mentions``) but it can never be an
#: anchor, because TdChat draws it as a collapsed line.
_SCANNED_ROLES = ("user", "assistant")

_MAX_LAST_MSG = 90


def parse_id(thread_id: str) -> tuple[str, str, int] | None:
    """``th-fund-2026-09-14-2`` -> ``("fund", "2026-09-14", 2)``."""
    match = _ID.match(thread_id or "")
    if match is None:
        return None
    return match.group(1), match.group(2), int(match.group(3))


# ---------------------------------------------------------------------------
# who owns which agent
# ---------------------------------------------------------------------------


def agents_by_member(root: Path) -> dict[str, str]:
    """``{member_id: agent}`` from the roster — the classification table.

    ``crews/members.json`` is the only source: the same file ``/org`` publishes as
    ``profiles[id].agent``, so a thread's classification can never disagree with
    the agent the UI posts to.
    """
    return _agents_of(org.roster(root))


def _agents_of(roster: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for member in roster:
        agent = member.get("agent")
        if isinstance(agent, str) and agent.strip():
            out[str(member.get("id"))] = agent.strip()
    return out


def _hint_title(member: dict[str, Any]) -> str:
    hint = member.get("slot_hint")
    if isinstance(hint, dict):
        return str(hint.get("title") or "")
    return str(hint or "")


def _attribute(roster: list[dict[str, Any]], agent: str, title: str) -> str | None:
    """Which member a session's agent belongs to, or None when it cannot be told.

    One agent can serve several members — all nine line-managers run
    ``tada-line-manager`` — so a unique holder is used directly and a shared one is
    resolved by the session's TITLE against the roster's own ``slot_hint``. With
    neither, None: the thread is still listed (its agent proves it is a desk
    session) but it is not attributed to a crew it might not be.
    """
    holders = [m for m in roster if str(m.get("agent") or "") == agent]
    if not holders:
        return None
    if len(holders) == 1:
        return str(holders[0].get("id"))
    wanted = (title or "").strip()
    if not wanted:
        return None
    for member in holders:
        if _hint_title(member) == wanted:
            return str(member.get("id"))
    return None


# ---------------------------------------------------------------------------
# one session's facts
# ---------------------------------------------------------------------------


def _session_facts(gw: Any, key: str, view: SlotView) -> dict[str, Any]:
    """``agent`` / ``title`` / ``created_at`` / ``running`` / ``open`` for a key.

    The live slot table answers first because it alone knows whether a turn is in
    flight; the transcript header is the fallback, and it is what lets a session
    the gateway has since closed still be classified instead of disappearing.
    """
    slot = view.by_key(key)
    meta = transcript.session_meta(gw, key)
    agent = ""
    if slot is not None:
        agent = str(slot.get("agent") or slot.get("effective_agent") or "")
    if not agent:
        agent = str(meta.get("agent") or "")
    return {
        "agent": agent or None,
        "title": str((slot or {}).get("title") or meta.get("title") or "").strip(),
        # The slot payload spells it ``created``; the transcript header spells it
        # ``created_at``. Both are read so a brand-new session with no header yet
        # still has a date to key an id on.
        "created_at": meta.get("created_at") or (slot or {}).get("created"),
        "running": bool(slot is not None and slot.get("running")),
        "open": slot is not None,
    }


def _visible_rows(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows a human counts as 动态 — what was said, not how it was done."""
    return [m for m in messages if str(m.get("role") or "") in _SCANNED_ROLES]


def _local_date(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    local = parsed.astimezone() if parsed.tzinfo else parsed
    return local.strftime("%Y-%m-%d")


def _anchor_of(message: dict[str, Any]) -> dict[str, Any] | None:
    """The message a thread hangs under, as the two identifiers the UI needs.

    ``main_msg`` is the row's ``meta.mid`` — the identity the gateway mints and the
    ledger will key on — and ``ts`` is what the SPA actually matches, because its
    ChatMessage carries no mid and ChatMessageList identifies a row by timestamp.
    ``ts`` is passed through VERBATIM for that reason: reformat it and the anchor
    silently stops matching the rendered row while still looking correct.

    No mid means nothing addressable, so this degrades to None rather than shipping
    an identifier the UI cannot resolve (§11.2 has a downgrade for that).
    """
    mid = transcript.mid_of(message)
    if mid is None:
        return None
    return {
        "main_msg": mid,
        "ts": message.get("ts"),
        # Scrubbed, then truncated: a key cut in half by the limit would still be
        # a fragment of one, and the key already has a field of its own.
        "preview": transcript.preview(str(message.get("content") or "")),
    }


def _recorded_anchor(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The anchor a ``POST /thread`` caller supplied, in the wire shape (§12).

    Same three fields as a derived one, and ``ts`` is passed through as it was
    STORED — which is as the caller sent it, which is as the SPA renders it. The
    store already dropped any entry missing an identifier, so a half anchor never
    reaches here.
    """
    if not entry:
        return None
    return {
        "main_msg": str(entry.get("main_msg") or ""),
        "ts": entry.get("ts"),
        "preview": transcript.preview(str(entry.get("preview") or "")),
    }


# ---------------------------------------------------------------------------
# derive
# ---------------------------------------------------------------------------


def _mentions(
    messages: list[dict[str, Any]], skip: set[str]
) -> list[tuple[str, dict[str, Any]]]:
    """``[(key, the row it hangs under)]`` in transcript order — one entry per key.

    Three places a key is read from, and the asymmetry between them is the point:

    * a **visible row**'s own text — the conductor's "已开 thread" reply, or the CEO
      naming a key (§11.1: the key rides in the reply);
    * a **tool call's INPUT** — what the conductor deliberately addressed, e.g. the
      ``session_send`` it drove a subordinate with. For a tool that takes an
      addressee beside a free-text body, only the addressing field is read
      (``ADDRESSED_INPUT_FIELDS``): a seed brief quoting "necessary 时 send 进
      risk-pod 的常驻 session" names a session the manager TALKED ABOUT, and reading
      the body minted two such quotes as the manager's own threads on the real
      09-15 conversation (§13.2);
    * a **session-creating tool's OUTPUT**, and no other tool's. rev6.1 made the
      mechanism the trigger: opening a session IS opening a thread, whether or not
      the manager then names the key in prose — and ``session_create`` reports the
      new key ONLY in its output.

    Every other tool's output stays unread, which is why that exception has to be
    keyed on the tool's name. One ``chat_folder_tree`` call puts the whole sidebar
    in the transcript — 86 keys on a real fund conversation — and every desk session
    in it would mint a thread nobody opened. Its input names three; its output names
    86; ``session_create``'s output names exactly the one it just made.

    Two rules decide WHICH row the key hangs under, both from §13.2:

    **One anchor per thread.** A key is recorded the first time it is seen and
    never again, so however many times one manager turn names the same session —
    the create's output, the "Thread 已开" line, the send's input, the closing
    receipt: five mentions of one key on the real 09-15 conversation — that thread
    hangs in exactly one place.

    **The anchor is the message that ASKED.** A thread belongs to the sentence the
    reader typed, not to the manager's narration of carrying it out, so the row a
    key hangs under is the user message that triggered the turn it was found in;
    the nearest visible row is the fallback for a turn no user message started (a
    cron-driven run, or a window that no longer holds the request). This is Slack's
    own meaning of a thread, and it is also what survives §13.1: intermediate prose
    folds into 过程, and a bar anchored there would have no visible row to sit on.

    A tool-sourced key never hangs on the tool row itself under either rule: TdChat
    draws one as a collapsed line, and a reply bar under something the reader cannot
    see is worse than none.
    """
    seen: set[str] = set()
    out: list[tuple[str, dict[str, Any]]] = []
    visible: dict[str, Any] | None = None
    asked: dict[str, Any] | None = None
    for message in messages:
        role = str(message.get("role") or "")
        if role in _SCANNED_ROLES:
            visible = message
            if role == "user":
                # Every runtime-authored row has a role of its own — ``nudge``,
                # ``notice``, ``inject``, ``error`` — so a ``user`` row here is a
                # message somebody sent, which is what may start a turn.
                asked = message
            raw = message.get("content")
            text = raw if isinstance(raw, str) else str(raw or "")
        elif role == "tool":
            meta = message.get("meta")
            meta = meta if isinstance(meta, dict) else {}
            parts = [transcript.tool_input_text(message)]
            if transcript.tool_created_session(message):
                parts.append(str(meta.get("output") or ""))
            text = "\n".join(parts)
        else:
            continue  # nudge / notice rows are the runtime talking, not the desk
        if visible is None:
            continue  # a key named before anything was said has nothing to hang on
        # findall yields the pattern's capture group, so a `dashboard:`-prefixed
        # mention arrives already normalised to the bare key (§11.5.2) and dedupes
        # against a bare mention of the same session instead of forking a thread.
        for key in transcript.MENTIONED_KEY.findall(transcript.strip_provenance(text)):
            if key in seen or key in skip:
                continue
            seen.add(key)
            out.append((key, asked or visible))
    return out


def _state_of(facts: dict[str, Any]) -> str:
    """``running`` | ``done`` | ``failed`` — the §8.2 vocabulary, rev6 meanings.

    ``running`` a turn is in flight right now. ``done`` the gateway holds the
    session and it is idle, i.e. the last turn finished. ``failed`` the gateway
    holds no OPEN slot for it: the transcript proves the session existed, but
    ``/api/chat/slots/{slot_key}`` serves live slots, so the panel cannot be opened
    and the UI needs to say so rather than draw a bar onto nothing.

    Note this is deliberately NOT ``/org``'s rule for a member's main session, where
    a key is honoured before its session exists so the embed can create it on the
    first message. A thread's session was created by the conductor when it opened
    the thread; a missing slot there is a session that went away, not one still to
    come.
    """
    if facts["running"]:
        return "running"
    return "done" if facts["open"] else "failed"


def _last_line(rows: list[dict[str, Any]], fallback: str) -> str:
    for message in reversed(rows):
        text = transcript.preview(str(message.get("content") or ""), limit=_MAX_LAST_MSG)
        if text:
            return text
    return fallback


def _build(
    *,
    gw: Any,
    member_id: str,
    key: str,
    facts: dict[str, Any],
    mention: dict[str, Any] | None,
    recorded: dict[str, Any] | None,
    date: str,
    seq: int,
    kind: str,
    worker: str | None,
) -> dict[str, Any]:
    rows = _visible_rows(transcript.read(gw, key))
    stamps = [m.get("ts") for m in rows if m.get("ts")]
    participants = [member_id] + ([worker] if worker and worker != member_id else [])
    title = facts["title"] or ("新 thread" if kind == "thread" else f"派工 · {worker or '未定'}")
    state = _state_of(facts)

    return {
        "id": f"th-{member_id}-{date}-{seq}",
        # §11.1: the clone the conductor talks to itself in, or a session it opened
        # for someone else. Both are reachable from the anchor; they are not the
        # same thing and the UI labels them differently.
        "kind": kind,
        "title": title,
        # Whose session it is. None when one agent serves several members and the
        # title does not say which — better unattributed than wrong.
        "member": worker,
        "state": state,
        "opened_at": facts["created_at"]
        or (stamps[0] if stamps else (mention or {}).get("ts")),
        "participants": participants,
        "last_msg": _last_line(
            rows,
            "刚开好，还没说话" if state != "failed" else "这个 session 已经不在了",
        ),
        # §11.2: the reply bar hangs under this message. None when the row has no
        # mid for the UI to resolve — and None for a thread found in the threads
        # FOLDER rather than in the conversation (§11.6.2): there is no message it
        # came out of, so it reaches the user through the header entry instead.
        # A thread the user opened ON a message carries the anchor they picked,
        # recorded at creation (§12), which is the one case a folder-sourced thread
        # does have a row to hang under.
        "anchor": _anchor_of(mention) if mention is not None else _recorded_anchor(recorded),
        # What the reply bar renders ("🧵 N 条动态 · 最新 hh:mm"). rev6 source: the
        # thread session's own rows, so the number is the panel's own length.
        "entry_count": len(rows),
        "last_ts": stamps[-1] if stamps else None,
        # rev6 (§11.2): the panel reads /api/chat/slots/{slot_key} and the composer
        # posts /api/chat {slot, agent}, so both are fields now. This is the one
        # place a session key appears.
        "slot_key": key,
        "agent": facts["agent"],
        "refs": {"run_date": date, "artifacts": []},
    }


def _hint_folder(member: dict[str, Any]) -> str:
    hint = member.get("slot_hint")
    if isinstance(hint, dict):
        return str(hint.get("folder") or "").strip()
    return ""


def threads_folder_of(member: dict[str, Any]) -> str:
    """``<member's own folder>/threads`` — where its clones are filed (§11.5.3)."""
    folder = _hint_folder(member)
    return f"{folder}/{THREADS_FOLDER}" if folder else ""


def _creation_rank(key: str) -> tuple[int, int, str]:
    """A session's place in creation order, from its key.

    ``chat-<n>-<epoch>``: the epoch is what orders two sessions, and the slot
    number breaks a same-second tie. Lexicographic order on the key itself will
    not do — ``chat-1470-…`` sorts before ``chat-983-…``. The key is kept as the
    last element so the sort is total even for a shape this does not parse.
    """
    match = re.match(r"^chat-(\d+)-(\d+)$", key or "")
    if match is None:
        return (0, 0, key or "")
    return (int(match.group(2)), int(match.group(1)), key or "")


def _classify_mention(
    roster: list[dict[str, Any]], own_agent: str | None, facts: dict[str, Any]
) -> tuple[str, str | None] | None:
    """S1's classification: by AGENT, and None when the agent is not the desk's.

    Strict, because in a main conversation a key is just text — one real fund
    conversation carries 86 unrelated keys in a single tool output — so the agent
    is the only thing standing between a mention and a thread nobody opened.
    """
    agent = facts["agent"]
    if not agent or agent not in {str(m.get("agent") or "") for m in roster}:
        return None
    if own_agent and agent == own_agent:
        return "thread", None  # the caller fills in its own id
    return "dispatch", _attribute(roster, agent, facts["title"])


def _bare_key(raw: str) -> str:
    """A filed session's bare slot key, or ``""`` when it cannot be a thread.

    Two jobs, both required by the contract. It NORMALISES: an archived record
    names its session by the transcript stem (``dashboard_chat-…``), the same fold
    §11.5.2 already collapses on the mention side, so the two populations dedupe
    against each other instead of listing one session twice.

    And it EXCLUDES a ``td-…`` key. That shape is minted by
    ``POST /member/{id}/reset`` for a member's own MAIN conversation, which §8.2
    pins outside a thread's ``slot_key`` shape — so an old main conversation that
    ends up filed in a threads folder is not silently republished as a thread.
    Found by running this against the live desk, where exactly that had happened.
    """
    found = transcript.MENTIONED_KEY.fullmatch(raw.strip())
    return found.group(1) if found else ""


def _filed_sessions(
    gw: Any, view: SlotView, path: str
) -> list[tuple[str, str, str]]:
    """``[(key, agent, title)]`` for every session filed at this folder path.

    Both populations, because a thread must stay reachable in the app whatever
    the gateway has since done with its tab (§11.6): the LIVE slots filed there,
    and the ARCHIVED sessions filed there, which the gateway's own session
    catalogue reports with the ``folder_id`` they were filed under. Without the
    second one, closing a thread's tab would remove it from the app — the same
    class of loss as the reset this source exists to survive.

    An archived record names the session by its TRANSCRIPT stem
    (``dashboard_chat-…``), so it is normalised to the bare key — the same
    normalisation §11.5.2 applies to a mention — and dropped when a live slot
    already covers it.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for slot in view.in_folder_path(path):
        key = _bare_key(str(slot.get("key") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            (
                key,
                str(slot.get("agent") or slot.get("effective_agent") or ""),
                str(slot.get("title") or ""),
            )
        )

    ids = view.folder_ids_for_path(path)
    conv = getattr(gw, "conversation_log", None)
    lister = getattr(conv, "list_sessions", None) if conv is not None else None
    if not ids or not callable(lister):
        return out
    try:
        catalogue = lister()
    except Exception:  # noqa: BLE001 — an unreadable catalogue must not empty the list
        log.debug("trading-desk: session catalogue unreadable", exc_info=True)
        return out
    for row in catalogue if isinstance(catalogue, list) else []:
        if not isinstance(row, dict) or str(row.get("folder_id") or "") not in ids:
            continue
        key = _bare_key(str(row.get("key") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, str(row.get("agent") or ""), str(row.get("title") or "")))
    return out


def _folder_candidates(
    roster: list[dict[str, Any]],
    member: dict[str, Any],
    view: SlotView,
    own_agent: str | None,
    gw: Any = None,
) -> list[tuple[str, str, str | None]]:
    """``[(key, kind, worker)]`` for every session in this member's threads folder.

    S2 (§11.6.1). The agent gate here is deliberately LOOSER than S1's: being
    filed in ``<member>/threads`` is itself the declaration that this is that
    member's thread, so a session whose agent cannot be resolved — closed slot, no
    metadata header — is still listed rather than dropped. Losing a thread is the
    failure this source exists to prevent.

    A session whose agent belongs to a DIFFERENT member is handed to that member,
    but only when that member reads this same folder path and would therefore find
    it itself. Five members share ``Trading Desk``, so that is the common case; a
    clone in ``Trading Desk/Desk/threads`` running a line-manager's agent is NOT
    (the line-manager reads its own pod folder), and skipping it there would make
    it unreachable in the app.
    """
    path = threads_folder_of(member)
    if not path or not own_agent:
        # No agent for this member means the roster is the degraded fallback, and
        # §11.1 defines a clone BY its agent — so there is no vocabulary to list
        # one under. ``/org`` is already degraded in that state.
        return []
    member_id = str(member.get("id"))
    out: list[tuple[str, str, str | None]] = []
    for key, agent, title in _filed_sessions(gw, view, path):
        if agent and own_agent and agent == own_agent:
            out.append((key, "thread", member_id))
            continue
        owner = _attribute(roster, agent, title) if agent else None
        if owner is not None and owner != member_id:
            other = next((m for m in roster if str(m.get("id")) == owner), None)
            if other is not None and threads_folder_of(other) == path:
                continue  # that member's own derive lists it, with its own agent
            out.append((key, "dispatch", owner))
            continue
        # Unresolvable agent: the folder is the evidence, so it is this member's.
        out.append((key, "thread", member_id))
    return out


def derive(
    root: Path, ctx: Any, view: SlotView, member_id: str, gw: Any = None
) -> list[dict[str, Any]]:
    """Every thread a member has, oldest first — both sources merged (§11.6).

    S1 is the main conversation's key mentions, which carry an anchor. S2 is the
    member's ``threads`` folder, which does not. They are merged on ``slot_key``
    with S1 winning, so a thread the conversation placed keeps its reply bar and a
    thread only the folder knows about still reaches the user through the header
    entry. That is what survives a ``/member/{id}/reset``: the new main
    conversation mentions nothing, and every clone is still in the folder.
    """
    roster = org.roster(root)
    member = next((m for m in roster if str(m.get("id")) == member_id), None)
    if member is None:
        return []

    table = _agents_of(roster)
    own_agent = table.get(member_id)

    main_key = org.current_slot_key(root, ctx, view, member_id)
    # A member's own main key is not a thread of itself. Every OTHER member's
    # currently bound main is left in: it is a session this conductor opened and
    # reached from that message, and hiding real data is the conductor's call to
    # make, not this module's.
    skip = {main_key} if main_key else set()

    picked: dict[str, dict[str, Any]] = {}

    # S1 — the conversation's own mentions. First, so it wins the merge.
    for key, mention in _mentions(transcript.read(gw, main_key), skip):
        facts = _session_facts(gw, key, view)
        classified = _classify_mention(roster, own_agent, facts)
        if classified is None:
            continue
        kind, worker = classified
        date = _local_date(mention.get("ts")) or _local_date(facts["created_at"])
        if date is None:
            continue  # nothing to key an id on
        picked[key] = {
            "key": key,
            "facts": facts,
            "mention": mention,
            "recorded": None,
            "date": date,
            "kind": kind,
            "worker": member_id if kind == "thread" else worker,
        }

    # S2 — the threads folder. Anything the conversation already placed is left
    # alone: the merge is on the key, and S1's copy is the one with the anchor.
    #
    # A RECORDED anchor (§12) is folded in here rather than being a third source:
    # ``POST /thread`` already files its session in the folder, so the thread is
    # found the same way — what the record adds is the message the user picked,
    # which nothing in gateway state knows. A recorded key that is no longer in the
    # folder is still admitted, because the app itself opened that thread and
    # dropping it would be the loss this whole revision exists to stop.
    recorded = anchors.for_member(ctx, member_id)
    candidates = _folder_candidates(roster, member, view, own_agent, gw)
    filed = {key for key, _kind, _worker in candidates}
    for key in recorded:
        if key not in filed and _bare_key(key):
            candidates.append((key, "thread", member_id))
    for key, kind, worker in candidates:
        if key in picked or key in skip:
            continue
        facts = _session_facts(gw, key, view)
        if not facts["agent"] and kind == "thread":
            # A clone whose agent cannot be read — closed slot, no metadata header
            # — takes the member's OWN agent, which §11.1 defines a clone to run.
            # Not cosmetic: the panel's composer posts under this value, so a null
            # here would list a thread the user cannot then talk in.
            facts = {**facts, "agent": own_agent}
        entry = recorded.get(key)
        # The anchor's own date when there is one, so a created thread is dated by
        # the message it hangs under exactly as a mentioned one is — otherwise the
        # same thread would be dated differently depending on how it was made.
        date = (
            _local_date((entry or {}).get("ts"))
            or _local_date(facts["created_at"])
            # Falls back to today rather than dropping the thread: an id that is
            # imperfectly dated is recoverable, an unreachable thread is not.
            or datetime.now().strftime("%Y-%m-%d")
        )
        picked[key] = {
            "key": key,
            "facts": facts,
            "mention": None,
            "recorded": entry,
            "date": date,
            "kind": kind,
            "worker": worker,
        }

    # seq is the session's place in CREATION order within its date, not its place
    # in mention order (§11.6.3): the same thread must get the same id whichever
    # source found it, or one reset would renumber every thread the member has.
    ordered = sorted(picked.values(), key=lambda p: (p["date"], _creation_rank(p["key"])))
    per_date: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for found in ordered:
        date = found["date"]
        per_date[date] = per_date.get(date, 0) + 1
        out.append(
            _build(
                gw=gw,
                member_id=member_id,
                key=found["key"],
                facts=found["facts"],
                mention=found["mention"],
                recorded=found["recorded"],
                date=date,
                seq=per_date[date],
                kind=found["kind"],
                worker=found["worker"],
            )
        )
    return out


def list_threads(
    root: Path,
    ctx: Any,
    view: SlotView,
    member_id: str,
    date: str | None = None,
    gw: Any = None,
) -> dict[str, Any]:
    """``GET /threads?member=`` — that member's threads, optionally one date's.

    No date means EVERY thread. The reply bar hangs on a message wherever it sits
    in the scroll, so filtering to today would make yesterday's bar disappear from
    a conversation the user can still see.
    """
    threads = derive(root, ctx, view, member_id, gw)
    if date:
        threads = [t for t in threads if t["refs"]["run_date"] == date]
    return {"threads": threads}


def detail(
    root: Path, ctx: Any, view: SlotView, thread_id: str, gw: Any = None
) -> dict[str, Any] | None:
    """``GET /thread/{id}`` — the thread's metadata and its ``slot_key`` (§11.2).

    No entries: the panel renders the clone session's own live transcript through
    ``/api/chat/slots/{slot_key}``. Returned by re-deriving and picking the id, so
    the detail is the SAME object the list published and the two cannot drift.
    """
    parsed = parse_id(thread_id)
    if parsed is None:
        return None
    member_id, _date, _seq = parsed
    for thread in derive(root, ctx, view, member_id, gw):
        if thread["id"] == thread_id:
            return thread
    return None


def target(
    root: Path, ctx: Any, view: SlotView, thread_id: str, gw: Any = None
) -> tuple[str, str] | None:
    """``(display_member, slot_key)`` a ``/say`` goes to — the thread's OWN slot.

    rev6: talking in a thread is talking to the clone in it, so there is no
    deepest-running-participant search any more. The display name falls back to the
    thread's owner when the session's agent is shared and unattributed, so a reply
    always names somebody.
    """
    parsed = parse_id(thread_id)
    if parsed is None:
        return None
    thread = detail(root, ctx, view, thread_id, gw)
    if thread is None:
        return None
    return thread["member"] or parsed[0], thread["slot_key"]
