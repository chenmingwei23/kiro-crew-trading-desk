"""Deliver a thread message into the work session that is doing the job.

Typing in a thread IS steering (design §2.2), so this is a real prompt on a real
session, not a note filed somewhere. It goes through the slot's own
``enqueue_or_run_prompt``, which is the gateway's queue-vs-run decision: an idle
session starts a turn now, a busy one takes the message on its next turn. That
matters here — a manager mid-report must not have a second turn raced onto it.

The turn is NOT charged against the app background-turn cap, matching
``session_control.send_to_target``'s own reasoning: that cap binds unattended
app-owned slots, and these are the crew's attended resident sessions with a human
watching the drawer.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("kirocrew.app.trading-desk")

MAX_CHARS = 4000


class SayError(Exception):
    """A ``/say`` cannot be delivered. Carries the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _runner() -> Any:
    """The gateway's chat runner, imported late so the module loads without it."""
    from kiro_crew.dashboard.chat_runner import _run_chat  # noqa: PLC0415

    return _run_chat


async def deliver(gw_state: Any, slot_key: str, text: str) -> bool:
    """Put ``text`` on that session as a turn. Returns True when a turn started.

    Raises :class:`SayError` when there is nothing to deliver to — a thread whose
    session the gateway no longer holds is a 409, not a silent success.
    """
    body = (text or "").strip()
    if not body:
        raise SayError("message is empty", status=400)
    if len(body) > MAX_CHARS:
        raise SayError(f"message exceeds {MAX_CHARS} characters", status=400)
    if gw_state is None:
        raise SayError("no gateway state to deliver through", status=503)

    getter = getattr(gw_state, "get_slot", None)
    slot = getter(slot_key) if callable(getter) else None
    if slot is None:
        raise SayError("this thread's work session is no longer open", status=409)

    try:
        run_chat = _runner()
    except Exception as exc:  # noqa: BLE001 — an unavailable runner is a 503
        raise SayError(f"chat runner unavailable: {type(exc).__name__}", status=503) from exc

    async def _turn(state: Any, target: Any, prompt: str) -> None:
        await run_chat(state, target, prompt, _directive_user_origin=False)

    started = bool(slot.enqueue_or_run_prompt(body, _turn, gw_state))
    # The dashboard shows the same session; nudge its projection so a human
    # watching the sidebar sees the turn rather than discovering it later.
    push = getattr(gw_state, "push_slots_update", None)
    if callable(push):
        try:
            push()
        except Exception:  # noqa: BLE001 — cosmetic
            log.debug("trading-desk: slots push after a thread say failed", exc_info=True)
    return started
