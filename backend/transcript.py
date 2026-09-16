"""Fold a work session's transcript down to a thread's boundary messages.

A thread view is NOT a transcript copy (CONTRACT §8.2: "do not copy the full text"). Only three
kinds of line cross into it:

* **dispatch** — a manager driving a subordinate. ``session_control`` prefixes such a
  delivery with ``[sent by session <key> via session_send]``, which is how a
  dispatch is told apart from a human typing; the crews track will additionally
  land a ``DISPATCHED →`` prefix (§8.4) and that is honoured here already.
* **sentinel** — a tier's completion line (``POD DONE`` and friends). It closes the
  thread when it is the thread's own worker reporting, and is a report when it is
  a lower tier reporting up.
* **steer** — any other message from the human.

Two hard rules. The provenance prefix carries a SESSION KEY, so it is stripped
before the text is ever returned — the UI must never see one (§8.2). And the
sentinel token itself is protocol, not prose: it is what this module MATCHES on,
never what the drawer displays, so it is stripped from the text too and the
human half of the message is what survives.

Every gateway read here goes through the state object the gateway injects
(§11.6.4): its live slot for the current rows, its own conversation log for the
older ones and for a session's metadata header. This app resolves no gateway
data path of its own — a self-built ``ConversationLog`` guesses the data home
from the app's process, which is both a direct filesystem read and already the
wrong home on a box still on the legacy one.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

log = logging.getLogger("kirocrew.app.trading-desk")

#: Completion sentinel -> the member whose tier emits it (CONDUCTOR MODE, the
#: engine's own roster). ``POD DONE`` belongs to whichever line-manager is running.
SENTINELS: dict[str, str | None] = {
    "POD DONE": None,
    "CEO BRIEF WRITTEN": "desk",
    "MACRO BRIEF WRITTEN": "macro",
    "RISK REPORT WRITTEN": "risk",
    "FUND PLAN DONE": "fund",
}

#: Explicit dispatch prefixes (§8.4). Both arrow forms, since prose uses either.
DISPATCH_PREFIXES = ("DISPATCHED →", "DISPATCHED ->")

#: What ``session_control`` stamps on a delivered message. Contains a session key.
_PROVENANCE = re.compile(r"^\[sent by session [^\]]*\]\s*", re.MULTILINE)

#: Cross-check for the red line: nothing shaped like a slot key may escape.
_KEY_SHAPE = re.compile(r"\b(?:chat-\d+-\d+|td-[a-z0-9-]+-\d{10,}|dashboard[:_][\w.:-]+)")

#: The session-key shape a main conversation is scanned for (CONTRACT §11.5.2).
#: BOTH forms are accepted and the match NORMALISES to the bare key, because the
#: same session is named two ways depending on who is talking: ``session_create``
#: hands back a bare ``chat-<n>-<ts>``, which is what a manager's receipt carries,
#: while the store and the API side prefix it (``dashboard:`` in a session-map key,
#: ``dashboard_`` in a transcript filename). The prefix is a capture-group exclusion
#: rather than a separate pattern so the two spellings collapse to ONE thread
#: instead of two, and so everything downstream — the live slot table, the metadata
#: read, the self-key exclusion — sees the one form it actually stores.
#:
#: The bare pattern alone happened to extract from ``dashboard:chat-…`` already,
#: since ``:`` leaves a word boundary — but only by accident, and it missed
#: ``dashboard_chat-…`` outright. Stating the prefix makes both deliberate.
#:
#: Deliberately NARROWER than ``_KEY_SHAPE``: a ``td-…`` key is a member's own main
#: conversation minted by ``/member/{id}/reset``, never a thread.
MENTIONED_KEY = re.compile(r"\b(?:dashboard[:_])?(chat-\d+-\d+)\b")

#: A tool row's own header line, which is the ONLY place the tool's name is
#: recorded. Verified against 28 real ``session_create`` rows: ``meta`` carries
#: ``tool_call_id / purpose / input / kind / mid / done / output`` and no name at
#: all, and ``meta.kind`` is ``"unknown"`` for every MCP call — the same value a
#: ``chat_folder_tree`` row carries — so it cannot tell them apart.
#:
#: ``🔧`` and ``✅`` both mean the call RAN; ``🚫`` means the user denied it, and a
#: denied ``session_create`` created nothing, so its output must never be scanned.
#: The server prefix is matched but not checked: the real gate on a created session
#: is whether its agent belongs to the desk, so pinning ``@kirocrew-dashboard``
#: would only make this break silently if that server were ever renamed.
_TOOL_CALL = re.compile(
    r"^\s*(?P<marker>[🔧✅🚫])\s*Running:\s*(?:@[\w.-]+/)?(?P<name>[\w.-]+)"
)

#: The markers that mean the call actually ran.
_RAN = ("🔧", "✅")

#: Tools whose input is read through NAMED fields instead of scanned whole, and the
#: fields that carry an address (CONTRACT §13.2, conductor ruling 2026-09-15).
#:
#: ``session_send`` takes an addressee in ``target`` and a free-text ``message``
#: beside it, and a seed brief routinely quotes other sessions as instructions
#: ("when necessary session_send into risk-pod's standing session ``chat-…``"). Those are
#: things the manager TALKED ABOUT, not things it addressed, and scanning the body
#: minted them as the manager's own threads: two phantoms on the real 09-15 fund
#: conversation, which is half of what made one request read as three threads.
#:
#: Reading only ``target`` loses nothing measurable — across 3614 real
#: ``session_send`` rows, 3586 carry ``target``, and the 26 without it name no
#: addressee at all (``message``-only or purpose-only calls). An input that does not
#: parse yields NOTHING rather than falling back to the whole blob, which would
#: reopen the hole; both unparsable inputs in the corpus are the empty string.
ADDRESSED_INPUT_FIELDS: dict[str, tuple[str, ...]] = {"session_send": ("target",)}

#: Tools whose OUTPUT may be scanned for a session key (CONTRACT §11.5 rev6.1).
#: A frozenset so a second creator is a one-line change; today ``session_create``
#: is the only call that mints a dashboard session.
SESSION_CREATING_TOOLS = frozenset({"session_create"})


def tool_name(message: dict[str, Any]) -> str | None:
    """The tool this row called, whether it ran or was denied."""
    match = _TOOL_CALL.match(str(message.get("content") or ""))
    return match.group("name") if match else None


def tool_created_session(message: dict[str, Any]) -> bool:
    """True when this tool row is a session-creating call that actually ran.

    Opening a session IS opening a thread (rev6.1), whether or not the manager
    then names the key in prose — and ``session_create`` reports the new key only
    in its output. This predicate is what keeps that a NARROW exception instead of
    reading tool output generally, which would let one ``chat_folder_tree`` call
    mint a thread for every session in the sidebar.
    """
    match = _TOOL_CALL.match(str(message.get("content") or ""))
    return bool(
        match
        and match.group("marker") in _RAN
        and match.group("name") in SESSION_CREATING_TOOLS
    )


def tool_input_text(message: dict[str, Any]) -> str:
    """The part of a tool call's input a key scan may read (§13.2).

    Whole input for most tools — what the manager put in a call's arguments is what
    it deliberately acted on. For a tool in ``ADDRESSED_INPUT_FIELDS``, only the
    fields that name an addressee, because the rest is prose that happens to quote
    other sessions.
    """
    meta = message.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    raw = str(meta.get("input") or "")
    fields = ADDRESSED_INPUT_FIELDS.get(tool_name(message) or "")
    if fields is None:
        return raw
    try:
        parsed = json.loads(raw) if raw.strip() else None
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        return ""
    return "\n".join(str(parsed.get(field) or "") for field in fields)


_MAX_TEXT = 400


def _log_of(gw: Any) -> Any:
    """The gateway's OWN conversation log, or None.

    CONTRACT §11.6.4: this app must not resolve gateway data paths. Constructing
    ``ConversationLog()`` here — which is what this module used to do — makes the
    app guess the gateway's data home from its own process, which is both a
    direct filesystem read and already wrong on a box whose home is the legacy
    one. Asking the state object means the reader is the one the gateway
    configured, wherever that turns out to live.
    """
    return getattr(gw, "conversation_log", None)


def _history_key(gw: Any, slot_key: str) -> str:
    """The transcript key for a slot, by the gateway's own derivation.

    ``slot_history_key`` is what every gateway read path uses, and it differs
    from ``dashboard:<key>`` for a channel-born slot — so deriving the name here
    by string concatenation would address a different file than the gateway
    writes. The plain form stands in only when that helper cannot be reached.
    """
    slot = _live_slot(gw, slot_key)
    if slot is not None:
        try:
            from kiro_crew.dashboard.chat_utils import (  # noqa: PLC0415 — gateway-only
                slot_history_key,
            )

            return str(slot_history_key(slot))
        except Exception:  # noqa: BLE001 — fall back to the plain form
            log.debug("trading-desk: slot_history_key unavailable", exc_info=True)
    return f"dashboard:{slot_key}"


def _live_slot(gw: Any, slot_key: str) -> Any:
    getter = getattr(gw, "get_slot", None)
    if not callable(getter):
        return None
    try:
        return getter(slot_key)
    except Exception:  # noqa: BLE001 — a missing slot is not an error here
        return None


def read(gw: Any, slot_key: str | None) -> list[dict[str, Any]]:
    """A session's messages, oldest first. Anything unreadable is an empty list.

    Mirrors what ``GET /api/chat/slots/{slot}`` itself answers, and in the same
    precedence: a live slot's in-memory rows are authoritative for the current
    session, and the gateway's log supplies the older rows the window no longer
    holds. A session the gateway no longer holds open is read from the log alone,
    which is what lets a thread whose slot went away still be classified instead
    of vanishing from the list.
    """
    if not slot_key:
        return []
    slot = _live_slot(gw, slot_key)
    conv = _log_of(gw)
    if slot is not None:
        rows = [m for m in list(getattr(slot, "messages", []) or []) if isinstance(m, dict)]
        older_count = int(getattr(slot, "_disk_older_count", 0) or 0)
        if older_count > 0 and conv is not None:
            older = _chained(conv, _history_key(gw, slot_key))[:older_count]
            return older + rows
        return rows
    if conv is None:
        return []
    return _chained(conv, f"dashboard:{slot_key}")


def _chained(conv: Any, key: str) -> list[dict[str, Any]]:
    """``read_messages_chained`` when the log has it, else the single-file read."""
    for name in ("read_messages_chained", "read_messages"):
        reader = getattr(conv, name, None)
        if not callable(reader):
            continue
        try:
            rows = reader(key)
        except Exception:  # noqa: BLE001 — a missing transcript must not break the page
            log.debug("trading-desk: no readable transcript for a work session", exc_info=True)
            return []
        return [m for m in rows if isinstance(m, dict)] if isinstance(rows, list) else []
    return []


def session_meta(gw: Any, slot_key: str | None) -> dict[str, Any]:
    """A session's metadata line: ``agent``, ``title``, ``created_at``.

    This is the DURABLE answer to "which agent is this session?" — the gateway
    writes it into the transcript's own header at creation and keeps it current
    through an agent switch. It is read here rather than only off the live slot
    table because rev6 classifies a mentioned key by its agent, and a key the
    conductor named yesterday may be a session the gateway no longer holds open:
    the live table would answer "unknown" and the thread would silently vanish
    from the list, which is the worse failure.
    """
    if not slot_key:
        return {}
    conv = _log_of(gw)
    getter = getattr(conv, "get_metadata", None) if conv is not None else None
    if not callable(getter):
        return {}
    try:
        meta = getter(_history_key(gw, slot_key))
    except Exception:  # noqa: BLE001 — an unreadable header must not break the page
        log.debug("trading-desk: no readable metadata for a session", exc_info=True)
        return {}
    return meta if isinstance(meta, dict) else {}


def strip_provenance(text: str) -> str:
    """Drop the ``[sent by session <key> via session_send]`` stamp.

    Applied BEFORE a key scan, not after: the stamp names the session that
    DELIVERED the message, which is never a thread of the member reading it, so
    leaving it in would mint a phantom thread out of the sender.
    """
    return _PROVENANCE.sub("", text or "")


def _ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def on_date(messages: list[dict[str, Any]], date: str) -> list[dict[str, Any]]:
    """Only the messages whose local date is ``date``."""
    out: list[dict[str, Any]] = []
    for message in messages:
        parsed = _ts(message.get("ts"))
        if parsed is None:
            continue
        local = parsed.astimezone() if parsed.tzinfo else parsed
        if local.strftime("%Y-%m-%d") == date:
            out.append(message)
    return out


def sentinel_in(text: str) -> str | None:
    """The completion sentinel this text carries, if any."""
    upper = text.upper()
    return next((name for name in SENTINELS if name in upper), None)


def scrub(text: str) -> str:
    """Strip the session-key provenance prefix and any sentinel token.

    The provenance is a leak; the sentinel is protocol. What is left is the human
    sentence, which is the only part a thread entry shows.
    """
    cleaned = _PROVENANCE.sub("", text or "")
    for name in SENTINELS:
        cleaned = re.sub(re.escape(name), "", cleaned, flags=re.IGNORECASE)
    for prefix in DISPATCH_PREFIXES:
        cleaned = cleaned.replace(prefix, "")
    cleaned = _KEY_SHAPE.sub("", cleaned)
    lines = [line.strip() for line in cleaned.splitlines()]
    joined = " ".join(line for line in lines if line).strip(" -—:·|")
    return joined[:_MAX_TEXT]


def is_dispatch(message: dict[str, Any]) -> bool:
    """True when this user-role message is a manager driving the session."""
    text = str(message.get("content") or "")
    if _PROVENANCE.search(text):
        return True
    return any(text.lstrip().startswith(prefix) for prefix in DISPATCH_PREFIXES)


def fold(
    messages: list[dict[str, Any]],
    *,
    dispatcher: str,
    worker: str,
    human: str = "ceo",
) -> list[dict[str, Any]]:
    """Turn one work session's day into a thread's entries.

    ``dispatcher`` is the member that hands work down (the thread's owner) and
    ``worker`` the member doing it, so an entry names a crew rather than a session.
    """
    entries: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        raw = str(message.get("content") or "")
        at = message.get("ts")

        if role == "user":
            dispatch = is_dispatch(message)
            text = scrub(raw)
            if not text:
                continue
            entries.append(
                {
                    "ts": at,
                    "actor": dispatcher if dispatch else human,
                    "kind": "dispatch" if dispatch else "steer",
                    "text": text,
                    "ref": None,
                }
            )
            continue

        if role != "assistant":
            continue  # tool chatter is process, not a boundary
        name = sentinel_in(raw)
        if name is None:
            continue
        owner = SENTINELS.get(name)
        text = scrub(raw) or _CLOSING_WORDS.get(name, "this step is done")
        entries.append(
            {
                "ts": at,
                "actor": worker,
                # The thread's own worker reporting closes it; a lower tier
                # reporting up is a report inside it.
                "kind": "close" if owner in (None, worker) else "report",
                "text": text,
                "ref": None,
            }
        )
    return entries


#: Plain-language stand-ins for a sentinel-only message, so an entry is never empty.
_CLOSING_WORDS = {
    "POD DONE": "pod report delivered",
    "CEO BRIEF WRITTEN": "desk view delivered",
    "MACRO BRIEF WRITTEN": "macro brief delivered",
    "RISK REPORT WRITTEN": "risk review delivered",
    "FUND PLAN DONE": "this round's dispatch is wrapped up",
}


def mid_of(message: dict[str, Any]) -> str | None:
    """The row's delivery identity (``meta.mid``), which is what addresses it.

    Every persisted row carries one: the gateway mints it on append, copies it to
    the transcript, and hands it back to the browser, which keys the rendered
    bubble on it. That is why an anchor uses ``mid`` and not a transcript index —
    an index shifts the moment a transcript rotates or is compacted, and the UI
    has nothing to match it against.
    """
    meta = message.get("meta")
    mid = meta.get("mid") if isinstance(meta, dict) else None
    return mid if isinstance(mid, str) and mid.strip() else None


def preview(text: str, limit: int = 60) -> str:
    """A short, safe quote of a message: the user's own words, one line.

    Strips the provenance stamp and anything shaped like a session key BEFORE
    truncating, so no fragment of a key can survive by being cut in half.
    """
    cleaned = _PROVENANCE.sub("", text or "")
    cleaned = _KEY_SHAPE.sub("", cleaned)
    joined = " ".join(line.strip() for line in cleaned.splitlines() if line.strip())
    return joined[:limit].strip()


def has_key_shape(value: Any) -> bool:
    """True when a payload fragment contains anything shaped like a session key."""
    if isinstance(value, str):
        return bool(_KEY_SHAPE.search(value))
    if isinstance(value, dict):
        return any(has_key_shape(v) for v in value.values()) or any(
            has_key_shape(k) for k in value
        )
    if isinstance(value, (list, tuple)):
        return any(has_key_shape(v) for v in value)
    return False
