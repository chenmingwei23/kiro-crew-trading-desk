"""Caller-supplied thread anchors — the app's own record (CONTRACT §12).

§11.6's two sources each answer "which message does this thread hang under?" from
what they can see: a mention IS a message, and a folder session has none. ``POST
/thread`` is the third case and the only one where the answer is an INPUT — the
user picked a row and asked for a thread on it — so it has to be written down.

It is written HERE, in the app's own data dir beside ``config.json``, for two
reasons. No gateway field means "the message this session hangs under", so gateway
state cannot hold it; and the alternative of posting the key into the member's
conversation so the mention source would find it is exactly what §11.5.1 ruled
out, besides overwriting the user's own message with a receipt.

This is the app's data, not the gateway's, so §11.6.4's rule — resolve no GATEWAY
data path — is intact. Own module rather than part of the create endpoint because
the derive reads it on every ``/threads`` while only the endpoint writes it, and a
shared import between the two would be a cycle.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import atomic_write_text
from .respond import log

#: Beside ``config.json`` in the app's data dir.
ANCHORS_FILE = "thread-anchors.json"


def path_for(ctx: Any) -> Path:
    return Path(getattr(ctx, "data_dir")) / ANCHORS_FILE


def read(ctx: Any) -> dict[str, dict[str, Any]]:
    """``{slot_key: {member, main_msg, ts, preview}}``, empty when unreadable.

    Read on every ``/threads``, so anything wrong with the file degrades to "no
    recorded anchors" — the threads still list from the folder, just without a
    reply bar — rather than failing the page. Entries missing either identifier are
    dropped here: a half anchor cannot place a row (§8.2 rev2 needs both), and
    letting one through would put a bar on a message the UI cannot match.
    """
    try:
        raw = path_for(ctx).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("trading-desk: %s does not parse; ignoring recorded anchors",
                    path_for(ctx))
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): value
        for key, value in parsed.items()
        if isinstance(value, dict) and value.get("main_msg") and value.get("ts")
    }


def for_member(ctx: Any, member_id: str) -> dict[str, dict[str, Any]]:
    """This member's recorded anchors, keyed by slot key."""
    return {
        key: entry
        for key, entry in read(ctx).items()
        if str(entry.get("member") or "") == member_id
    }


def record(ctx: Any, slot_key: str, entry: dict[str, Any]) -> None:
    """Add one anchor, carrying every existing one forward.

    Re-read immediately before the replace, the same read-modify-write discipline
    ``reset`` follows: that window is what decides whether a concurrent create's
    anchor survives, and two threads opened seconds apart is the ordinary case.
    """
    stored = read(ctx)
    stored[slot_key] = entry
    atomic_write_text(
        path_for(ctx),
        json.dumps(stored, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def find(ctx: Any, member_id: str, main_msg: str) -> str | None:
    """The session already opened on this message, if there is one."""
    for key, entry in for_member(ctx, member_id).items():
        if str(entry.get("main_msg") or "") == main_msg:
            return key
    return None
