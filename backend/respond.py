"""Response, auth and error plumbing shared by every Trading Desk route.

The external-app backend contract puts the auth decision on the handler:
``request.get("user")`` is None for an unauthenticated caller, which must be a
401. Wrapping that once here keeps each handler to its own job, and turns any
unexpected exception into a JSON error instead of an aiohttp traceback.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

from .paths import BadInput, OutOfRoot

log = logging.getLogger("kirocrew.app.trading-desk")

Handler = Callable[[web.Request, Any], Awaitable[web.Response]]


def ok(payload: dict[str, Any]) -> web.Response:
    return web.json_response(payload)


def err(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def is_authed(request: web.Request) -> bool:
    return request.get("user") is not None


def guarded(fn: Handler) -> Handler:
    """401 unauthenticated, 403 out-of-root, 500-as-JSON for anything unforeseen."""

    @functools.wraps(fn)
    async def _inner(request: web.Request, ctx: Any) -> web.Response:
        if not is_authed(request):
            return err("unauthorized", 401)
        try:
            return await fn(request, ctx)
        except OutOfRoot as exc:
            return err(str(exc), 403)
        except BadInput as exc:
            return err(str(exc), 400)
        except Exception as exc:  # noqa: BLE001 — a route must never 500 opaquely
            log.exception("trading-desk %s failed", fn.__name__)
            return err(f"{type(exc).__name__}: {exc}", 500)

    return _inner
