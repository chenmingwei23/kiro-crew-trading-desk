"""Shared test helpers for the Trading Desk App test suite (ARCHITECTURE.md §6).

Nothing here asserts contract shape -- that lives in ``tests/schema.py``.
This module only carries plumbing: repo paths, "not delivered yet" guards,
and a way to invoke an app route handler without a running gateway.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"

#: The real desk data root (ARCHITECTURE.md §1). Only read from, never written to,
#: and only for optional inputs like ``engine/validate_config.py``.
REAL_DESK_ROOT = Path(os.environ.get("DESK_ROOT") or Path.home() / "trading-desk")

#: The smoke-test run replayed by M0 acceptance (ARCHITECTURE.md §7).
SMOKE_DATE = "2026-09-07"
#: The date the shared fixtures are cut for. §3, cycle1 adjudication: fixtures
#: use the real smoke date, so this IS the smoke date.
FIXTURE_DATE = SMOKE_DATE

APP_NAME = "trading-desk"


# ---------------------------------------------------------------------------
# Cross-track delivery guards
# ---------------------------------------------------------------------------

def strict_mode() -> bool:
    """True when skips must become failures (final acceptance run).

    Run ``TD_REQUIRE_ALL=1 pytest tests/ -x -q`` once every track has landed:
    any test that would silently skip because a deliverable is missing fails
    instead, so a green suite cannot be green by omission.
    """
    return os.environ.get("TD_REQUIRE_ALL") == "1"


def _unmet(msg: str) -> None:
    if strict_mode():
        pytest.fail(f"{msg} [TD_REQUIRE_ALL=1]")
    pytest.skip(msg)


def require_path(rel: str, clause: str) -> Path:
    """Return ``REPO_ROOT/rel``, skipping while that track has not delivered."""
    path = REPO_ROOT / rel
    if not path.exists():
        _unmet(f"{rel} not delivered yet (ARCHITECTURE.md {clause})")
    return path


def require_module(rel: str, dotted: str, clause: str) -> Any:
    """Import ``dotted`` from the repo, skipping while its file is missing."""
    require_path(rel, clause)
    try:
        return importlib.import_module(dotted)
    except Exception as exc:  # pragma: no cover - reported as a real failure
        pytest.fail(f"import {dotted} failed ({rel}, ARCHITECTURE.md {clause}): {exc!r}")


def require_json(rel: str, clause: str) -> Any:
    path = require_path(rel, clause)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"{rel} is not valid JSON (ARCHITECTURE.md {clause}): {exc}")


# ---------------------------------------------------------------------------
# Route invocation without a gateway
# ---------------------------------------------------------------------------

try:  # aiohttp ships multidict; fall back to a plain dict if absent
    from multidict import MultiDict as _MultiDict
except Exception:  # pragma: no cover
    _MultiDict = dict  # type: ignore[assignment]

_MISSING = object()

#: The gateway's ``token_auth`` middleware sets ``request["user"]`` (and an
#: ``app`` scope, empty for the dashboard user) after validating the token, and
#: an app route decides its own 401 from that (ARCHITECTURE.md §1). Route tests run
#: authenticated by default; pass ``authed=False`` to exercise the 401 path.
AUTHED_STATE: dict[str, Any] = {"user": "test-user", "app": ""}


class FakeRequest:
    """Duck-typed stand-in for ``aiohttp.web.Request``.

    Covers the surface a route handler needs per ARCHITECTURE.md §2:
    ``request.query`` for ``?date=``, ``await request.json()`` for the two
    POST bodies, plus method/path/headers/match_info and mapping access.
    """

    def __init__(
        self,
        method: str = "GET",
        path: str = "/",
        query: dict[str, str] | None = None,
        json_body: Any = _MISSING,
        raw_body: str | None = None,
        headers: dict[str, str] | None = None,
        match_info: dict[str, str] | None = None,
        state: dict[str, Any] | None = None,
        app: dict[str, Any] | None = None,
    ) -> None:
        self.method = method.upper()
        self.path = f"/api/apps/{APP_NAME}{path}" if path.startswith("/") else path
        self.rel_path = path
        self.query = _MultiDict(query or {})
        self.headers = dict(headers or {})
        self.match_info = dict(match_info or {})
        self._json_body = json_body
        self._raw_body = raw_body
        self._state: dict[str, Any] = dict(state or {})
        #: A real request exposes the aiohttp Application, which handlers read
        #: gateway state off. A plain dict is mapping-compatible with it.
        self.app: dict[str, Any] = dict(app or {})

    # --- body -------------------------------------------------------------
    async def json(self, *, loads: Callable[[str], Any] = json.loads) -> Any:
        if self._raw_body is not None:
            return loads(self._raw_body)
        if self._json_body is _MISSING:
            raise json.JSONDecodeError("no body", "", 0)
        return self._json_body

    async def text(self) -> str:
        if self._raw_body is not None:
            return self._raw_body
        if self._json_body is _MISSING:
            return ""
        return json.dumps(self._json_body)

    async def read(self) -> bytes:
        return (await self.text()).encode("utf-8")

    # --- mapping access ---------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)


def _response_parts(resp: Any) -> tuple[int, Any, str]:
    """Return (status, parsed_json_or_None, raw_text) for a handler result."""
    status = getattr(resp, "status", None)
    if status is None:
        raise AssertionError(
            f"handler returned {type(resp).__name__}, expected an aiohttp response "
            "(ARCHITECTURE.md §2: all routes answer JSON + 4xx/5xx)"
        )
    body = getattr(resp, "body", None)
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body).decode("utf-8", "replace")
    else:
        raw = getattr(resp, "text", None) or ""
        if not isinstance(raw, str):
            raw = str(raw)
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = None
    return int(status), payload, raw


def call_route(
    handler: Callable[..., Any], ctx: Any, *, authed: bool = True, **request_kw: Any
) -> tuple[int, Any, str]:
    """Invoke one route handler synchronously.

    Returns ``(status, payload, raw_text)``. A raised ``web.HTTPException`` is
    treated as its response, so a handler may either return or raise a 4xx.
    ``authed=False`` drops the gateway's ``request["user"]`` marker, which is
    how the 401 path (§1) is exercised.
    """
    if authed:
        request_kw.setdefault("state", dict(AUTHED_STATE))

    async def _run() -> Any:
        try:
            return await handler(FakeRequest(**request_kw), ctx)
        except Exception as exc:  # HTTPException is an Exception subclass
            if getattr(exc, "status", None) is not None and hasattr(exc, "headers"):
                return exc
            raise

    return _response_parts(asyncio.run(_run()))


def find_route(routes: list[Any], method: str, path: str) -> Any:
    """Return the handler registered for ``method path``, or None."""
    for route in routes:
        r_method = str(getattr(route, "method", "")).upper()
        r_path = str(getattr(route, "path", ""))
        if not r_path.startswith("/"):
            r_path = "/" + r_path
        if r_method == method.upper() and r_path == path:
            return getattr(route, "handler", None)
    return None


# ---------------------------------------------------------------------------
# Reading a real UI module from Python
# ---------------------------------------------------------------------------

#: The translation tables. Every probe loads them as `m`, because a rendered
#: string is a table lookup and a probe that stubbed it would prove nothing.
_TABLE_FILE = "ui/i18n.mjs"


def run_node_probe(tmp_path: Path, body: str) -> dict:
    """Import the real `ui/i18n.mjs` under Node and return the probe's JSON.

    The module imports `react` for its store subscription and there is no
    `node_modules` here, so a resolve hook points that one specifier at a stub.
    The module under test is the real file on disk, not a copy.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH -- run tests/test_i18n.py manually (ARCHITECTURE.md §14)")
    i18n = require_path(_TABLE_FILE, "§14 the translation tables")
    ui_dir = require_path("ui", "§0 ui track deliverable")

    (tmp_path / "react-stub.mjs").write_text(
        # `i18n.mjs` needs only the store hook, but a probe that imports a RENDER
        # module (`parts.mjs`, `chat.mjs`) pulls in the jsx runtime and the hooks
        # too, and a missing named export fails ESM linking before a single line
        # runs. The extras are inert: they let the module load so its pure
        # functions can be called.
        "const noop = () => {}\n"
        "export function useSyncExternalStore(sub, get) { return get() }\n"
        "export function useState(v) { return [typeof v === 'function' ? v() : v, noop] }\n"
        "export function useEffect() {}\n"
        "export function useMemo(f) { return f() }\n"
        "export function useRef(v) { return { current: v } }\n"
        "export function useCallback(f) { return f }\n"
        "export function createElement(type, props) { return { type, props } }\n"
        "export function jsx(type, props) { return { type, props } }\n"
        "export function jsxs(type, props) { return { type, props } }\n"
        "export const Fragment = 'Fragment'\n"
        "export class Component { constructor(p) { this.props = p } render() { return null } }\n"
        "export default { useSyncExternalStore, useState, useEffect, useMemo, useRef,\n"
        "  useCallback, createElement, jsx, jsxs, Fragment, Component }\n",
        encoding="utf-8",
    )
    (tmp_path / "hooks.mjs").write_text(
        "import { pathToFileURL } from 'node:url'\n"
        f"const STUB = pathToFileURL({json.dumps(str(tmp_path / 'react-stub.mjs'))}).href\n"
        "export async function resolve(spec, ctx, next) {\n"
        "  if (spec === 'react' || spec === 'react/jsx-runtime') return { url: STUB, shortCircuit: true }\n"
        "  return next(spec, ctx)\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "register.mjs").write_text(
        "import { register } from 'node:module'\n"
        "import { pathToFileURL } from 'node:url'\n"
        f"register(pathToFileURL({json.dumps(str(tmp_path / 'hooks.mjs'))}).href)\n",
        encoding="utf-8",
    )
    preamble = (
        "globalThis.window = { localStorage: { getItem: () => null, setItem: () => {} } }\n"
        "Object.defineProperty(globalThis, 'navigator', "
        "{ value: { language: 'en-US', languages: ['en-US'] }, configurable: true })\n"
        f"const I18N = {json.dumps(str(i18n))}\n"
        f"const UI_DIR = {json.dumps(str(ui_dir))}\n"
        "const m = await import(I18N)\n"
    )
    probe = tmp_path / "probe.mjs"
    probe.write_text(preamble + body, encoding="utf-8")
    proc = subprocess.run(
        [node, "--import", str(tmp_path / "register.mjs"), str(probe)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])
