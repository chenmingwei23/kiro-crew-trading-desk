"""``POST /member/{id}/reset`` — give one member a fresh chat session.

Resetting does NOT delete anything. A new slot key (``td-<member_id>-<epoch>``)
is written into ``data/config.json``'s ``slots`` map, which already outranks the
roster's ``slot_hint`` when ``/org`` resolves a member's session. The member's old
session stays in the gateway untouched, as history; the new one is created lazily
by ChatEmbed's first message.

The write is a read-modify-write of the app's own config file: it is re-read
immediately before replacing so the other keys (``deskRoot``, ``appRoot``,
``statePath``) and any slot another reset just set are carried forward, and the
replace itself is atomic, so a concurrent reader never sees a half-written config.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from .paths import DEFAULT_DESK_ROOT, app_root, atomic_write_text

log = logging.getLogger("kirocrew.app.trading-desk")

#: A member id safe to embed in a slot key and a config key. The roster check
#: already gates this; the pattern is the second line, so a roster entry with an
#: odd id can never reach the key or the file.
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class BadMember(Exception):
    """The member id is not usable. Handler turns this into 400."""


def config_path(ctx: Any) -> Path:
    return Path(getattr(ctx, "data_dir")) / "config.json"


def slot_key_for(member_id: str, epoch: int) -> str:
    return f"td-{member_id}-{epoch}"


def _load_for_write(ctx: Any, path: Path) -> dict[str, Any]:
    """The config to modify — recovering, not discarding, an unparseable file.

    ``app_config`` reads a broken file as empty, which is right for a read but
    wrong here: writing that back would drop ``deskRoot``/``appRoot`` and the heal
    cron only recreates the file when it is ABSENT, so nothing would ever repair
    it. So a file that exists but does not parse is moved aside under a
    ``.corrupt-<epoch>`` name and replaced with the keys this backend can state
    from its own resolution.
    """
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return parsed
        reason = f"top level is {type(parsed).__name__}, not an object"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        reason = str(exc)

    aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        path.replace(aside)
        log.warning(
            "trading-desk: %s was unreadable (%s); kept a copy at %s and rebuilt it",
            path, reason, aside,
        )
    except OSError:
        log.warning("trading-desk: %s was unreadable (%s) and could not be set aside",
                    path, reason)
    # The contract default, not the resolved path: a corrupt file is no evidence of
    # a custom deskRoot, and any customisation is in the copy set aside above.
    return {"deskRoot": DEFAULT_DESK_ROOT, "appRoot": str(app_root())}


def reset(ctx: Any, member_id: str, previous: str | None) -> dict[str, Any]:
    """Point ``member_id`` at a brand-new slot key and return the swap.

    ``previous`` is the key the member was bound to before this call (whatever
    ``/org`` reported), echoed back so the UI can still reach the old session.
    """
    if not _SAFE_ID.match(member_id):
        raise BadMember(f"member id {member_id!r} is not a usable slot-key segment")

    epoch = int(time.time())
    new_key = slot_key_for(member_id, epoch)
    # Two resets inside one second would otherwise mint the same key and silently
    # do nothing — a double-click has to produce a genuinely new session.
    while new_key == previous:
        epoch += 1
        new_key = slot_key_for(member_id, epoch)

    path = config_path(ctx)
    # Re-read HERE rather than reuse an earlier snapshot: the read-modify-write
    # window is what decides whether a concurrent write is preserved or dropped.
    config = _load_for_write(ctx, path)
    slots = config.get("slots")
    slots = dict(slots) if isinstance(slots, dict) else {}
    stored = slots.get(member_id)
    slots[member_id] = new_key
    config["slots"] = slots

    atomic_write_text(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")

    return {
        "slot_key": new_key,
        "previous": previous or (stored if isinstance(stored, str) and stored else None),
    }
