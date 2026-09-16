"""Resolve a member's ``slot_hint`` to a live chat slot.

``crews/members.json`` gives a LOCATOR, not a key — ``{"folder": "Trading
Desk/Desk/example-megacap", "title": "line-manager · example-megacap"}`` — because the slot
key is assigned by the gateway when the session is created. This module takes the
one snapshot of the gateway's sidebar that ``/org`` needs (live slots plus each
folder's human path) so the assembly stays a pure function over plain data.

Both reads are the gateway's public ones (``serialize_slots``, ``read_folders``),
and every one is guarded: with no gateway state — a test, or a state that has
moved on — the snapshot is simply empty and every member reads as not yet
started, instead of the page failing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlotView:
    """What ``/org`` needs to know about the gateway's live sessions."""

    slots: list[dict[str, Any]] = field(default_factory=list)
    folder_paths: dict[str, str] = field(default_factory=dict)

    def by_folder_and_title(self, folder: str, title: str) -> dict[str, Any] | None:
        """The slot filed under ``folder`` with exactly this title."""
        for slot in self.slots:
            if slot.get("title") != title:
                continue
            if self.folder_paths.get(str(slot.get("folder_id") or "")) == folder:
                return slot
        return None

    def by_unique_title(self, title: str) -> dict[str, Any] | None:
        """The only slot with this title, if it is the only one.

        A session the user has not filed into its folder yet still binds, which is
        the same latitude the gateway's own move-session tool allows — but only
        while the title is unambiguous, so a bind is never a guess between two.
        """
        matches = [s for s in self.slots if s.get("title") == title]
        return matches[0] if len(matches) == 1 else None

    def by_key(self, key: str) -> dict[str, Any] | None:
        return next((s for s in self.slots if s.get("key") == key), None)

    def in_folder_path(self, path: str) -> list[dict[str, Any]]:
        """Every slot filed under exactly this folder path (CONTRACT §11.6.1).

        The second thread source. A path rather than an id because the roster
        states a member's location as a human path (``slot_hint.folder``) and the
        gateway assigns folder ids, so the path is the only thing both sides
        share. Descendants are deliberately NOT included: ``Trading Desk/threads``
        must not swallow ``Trading Desk/Desk/example-megacap/threads``, which belongs
        to a different member.
        """
        ids = self.folder_ids_for_path(path)
        if not ids:
            return []
        return [slot for slot in self.slots if str(slot.get("folder_id") or "") in ids]

    def folder_ids_for_path(self, path: str) -> set[str]:
        """Every folder id whose human path is exactly this.

        A set, not one id: nothing stops two sidebar folders from rendering the
        same path, and picking one of them would hide whatever is filed in the
        other. Needed on its own because an ARCHIVED session has no slot to read a
        path off — it carries only its ``folder_id``.
        """
        wanted = (path or "").strip()
        if not wanted:
            return set()
        return {fid for fid, at in self.folder_paths.items() if at == wanted}


def _folder_path_map(folders: list[dict[str, Any]]) -> dict[str, str]:
    """``{folder_id: "Parent/Child"}`` for every folder in the sidebar tree."""
    by_id = {str(f.get("id")): f for f in folders if isinstance(f, dict) and f.get("id")}

    def path_of(folder_id: str, seen: frozenset[str] = frozenset()) -> str:
        folder = by_id.get(folder_id)
        if folder is None or folder_id in seen:
            return ""
        name = str(folder.get("name") or "")
        parent = str(folder.get("parent_id") or "")
        if not parent:
            return name
        above = path_of(parent, seen | {folder_id})
        return f"{above}/{name}" if above else name

    return {fid: path_of(fid) for fid in by_id}


async def snapshot(gw_state: Any) -> SlotView:
    """One read of the gateway's live slots and folder tree."""
    if gw_state is None:
        return SlotView()

    slots: list[dict[str, Any]] = []
    serialize = getattr(gw_state, "serialize_slots", None)
    if callable(serialize):
        try:
            raw = serialize()
            slots = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []
        except Exception:  # noqa: BLE001 — a snapshot must never break the page
            slots = []

    folder_paths: dict[str, str] = {}
    read_folders = getattr(gw_state, "read_folders", None)
    if callable(read_folders):
        try:
            folder_paths = await read_folders(_folder_path_map)
        except Exception:  # noqa: BLE001
            folder_paths = {}

    return SlotView(slots=slots, folder_paths=folder_paths)
