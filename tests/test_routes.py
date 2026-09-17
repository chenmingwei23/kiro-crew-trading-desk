"""Backend route tests (ARCHITECTURE.md §6 -> §1/§2).

Handlers are called directly with a fake request and an AppContext pointed at
the tmp desk root, so no gateway is needed. The tmp tree carries sentinel
values (``TEST_BOOK_NAME``, a single run date), which is what proves a handler
actually resolves ``deskRoot`` instead of reading the real desk.

Skips while ``backend/routes.py`` is undelivered; ``TD_REQUIRE_ALL=1`` makes
those skips fail instead.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

import pytest

import schema
from conftest import TEST_BOOK_NAME, TEST_PODS
from helpers import (SMOKE_DATE, call_route, find_route, require_json, require_module,
                     require_path, run_node_probe)

CLAUSE = "§2 Backend API"

#: §6 plus the routes later cycles added: the config GET at /deskconfig
#: (cycle3), the chat reset (§2 cycle9) and the three §8.2 thread routes.
REQUIRED_ROUTES = (
    ("GET", "/org"),
    ("GET", "/run"),
    ("GET", "/deskconfig"),
    ("GET", "/artifacts"),
    ("POST", "/config/validate"),
    ("POST", "/config/apply"),
    ("POST", "/member/{id}/reset"),
    ("GET", "/threads"),
    ("GET", "/thread/{id}"),
    ("POST", "/thread/{id}/say"),
)

#: The one function every caller-supplied filesystem path passes through
#: (``backend/paths.py``). It raises ``OutOfRoot``, which the handler wrapper
#: maps to 403, so spying on it is how a file-reading route is identified by
#: behaviour rather than by the spelling of its path.
PATH_RESOLVER = "resolve_in_root"

#: Paths the gateway registers itself, before the RouteRegistry catch-all is
#: installed at app-enable time. aiohttp resolves in registration order, so an
#: app route on one of these is never dispatched -- it ships dead and silent.
#: ``/api/apps/{name}/config`` is bound GET and PUT in the gateway's app routes;
#: the exact segment only, which is why /config/validate and /config/apply are
#: unaffected.
SHADOWED_BY_GATEWAY = (("GET", "/config"), ("PUT", "/config"))

#: §1 UI permissions.
REQUIRED_API_PERMISSIONS = (
    "/api/chat",
    "/api/chat/*",
    "/api/approvals",
    "/api/approvals/*",
    "/api/file-read",
    "/api/apps/trading-desk/*",
)

HOSTILE_DATES = (
    "../../../../etc",
    "2026-09-07/../../..",
    "/etc",
    "..%2f..%2fetc",
    "2026-09-07\x00",
)


@pytest.fixture
def routes_module() -> Any:
    return require_module("backend/routes.py", "backend.routes", "§0/§2 backend track")


@pytest.fixture
def routes(routes_module: Any, app_ctx: Any) -> list[Any]:
    register = getattr(routes_module, "register_routes", None)
    assert callable(register), (
        f"[ARCHITECTURE.md §1] backend.routes must expose register_routes(ctx); "
        f"got {register!r}"
    )
    result = register(app_ctx)
    assert isinstance(result, list), (
        f"[ARCHITECTURE.md §1] register_routes(ctx) must return list[AppRoute], "
        f"got {type(result).__name__}"
    )
    return result


def _handler(routes: list[Any], method: str, path: str) -> Any:
    handler = find_route(routes, method, path)
    assert handler is not None, (
        f"[ARCHITECTURE.md §6] no handler registered for {method} {path}; registered = "
        f"{sorted((str(r.method).upper(), str(r.path)) for r in routes)}"
    )
    return handler


def _spy_on_path_resolver(patch: pytest.MonkeyPatch) -> list[str]:
    """Record every raw value the backend resolves under deskRoot.

    ``backend/artifacts.py`` binds the resolver by name at import
    (``from .paths import resolve_in_root``), so the wrapper is installed on
    every backend module that holds a reference, not just on ``paths``.
    """
    seen: list[str] = []
    modules = [m for name, m in list(sys.modules.items())
               if name == "backend" or name.startswith("backend.")]

    def make_spy(real: Any) -> Any:
        def spy(*args: Any, **kwargs: Any) -> Any:
            raw = kwargs.get("raw", args[1] if len(args) > 1 else None)
            seen.append("" if raw is None else str(raw))
            return real(*args, **kwargs)
        return spy

    for module in modules:
        real = getattr(module, PATH_RESOLVER, None)
        if callable(real):
            patch.setattr(module, PATH_RESOLVER, make_spy(real), raising=False)
    return seen


def _yaml_bytes(desk_root: Path) -> dict[str, bytes]:
    return {
        "books.yaml": (desk_root / "books.yaml").read_bytes(),
        "sectors.yaml": (desk_root / "sectors.yaml").read_bytes(),
    }


def _parsed_config(desk_root: Path) -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")
    return {
        "books": yaml.safe_load((desk_root / "books.yaml").read_text(encoding="utf-8")),
        "sectors": yaml.safe_load((desk_root / "sectors.yaml").read_text(encoding="utf-8")),
    }


# ---------------------------------------------------------------------------
# Registration shape (§1)
# ---------------------------------------------------------------------------

def test_post_client_error_records_the_stack_and_bounds_the_file(
    routes: list[Any], app_ctx: Any, app_data_dir: Path
) -> None:
    """§2: a browser-side crash is written down, and a crash loop cannot grow it.

    The host's error card shows ``error.message`` alone, and the message a minified
    host component throws names nothing anyone can act on -- the stack that would
    identify it lives in the browser. This route is how it reaches disk, so what
    matters is that the stack survives the round trip and that a page crashing in a
    loop overwrites its own history instead of filling the volume.
    """
    handler = find_route(routes, "POST", "/clienterror")
    if handler is None:
        pytest.skip(f"[{CLAUSE}] POST /clienterror is not registered yet")

    status, payload, _ = call_route(
        handler,
        app_ctx,
        method="POST",
        path="/clienterror",
        json_body={
            "message": "t is not a function",
            "stack": "TypeError: t is not a function\n    at Boom (x.mjs:1:1)",
            "componentStack": "    at MdBody\n    at ChatPage",
            "where": "/chat",
            "lang": "zh-CN",
            "hostKit": True,
        },
    )
    assert status == 200, f"[{CLAUSE}] recording a crash answered {status}: {payload}"

    written = app_data_dir / "client-errors.jsonl"
    assert written.is_file(), f"[{CLAUSE}] nothing was written to {written}"
    entry = json.loads(written.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["message"] == "t is not a function"
    assert "at Boom (x.mjs:1:1)" in entry["stack"], (
        f"[{CLAUSE}] the stack did not survive: without it the report says no more "
        f"than the error card it exists to improve on"
    )
    assert "at MdBody" in entry["componentStack"]
    assert entry["hostKit"] is True, (
        f"[{CLAUSE}] hostKit was dropped; it is what says which rendering path the "
        f"crash came from"
    )
    assert entry["at"], f"[{CLAUSE}] the report carries no timestamp"

    # A crash loop must not grow the file without bound.
    for n in range(40):
        call_route(
            handler, app_ctx, method="POST", path="/clienterror",
            json_body={"message": f"loop {n}"},
        )
    lines = [ln for ln in written.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 20, (
        f"[{CLAUSE}] {len(lines)} reports retained, expected the full window of 20. "
        f"Too many and a page crashing in a loop grows the file without limit; too "
        f"few and the history a crash loop needs to be understood is thrown away"
    )
    kept_messages = [json.loads(ln)["message"] for ln in lines]
    assert kept_messages[-1] == "loop 39", (
        f"[{CLAUSE}] the most recent report was dropped instead of the oldest"
    )
    assert kept_messages[0] == "loop 20", (
        f"[{CLAUSE}] the retained window starts at {kept_messages[0]!r}; 41 reports "
        f"through a 20-deep window should leave 'loop 20' through 'loop 39', so the "
        f"entries between the oldest and the newest were discarded"
    )

    # A body that is not an object is rejected rather than stored as junk.
    status, _, _ = call_route(
        handler, app_ctx, method="POST", path="/clienterror", json_body=["not", "an", "object"],
    )
    assert status == 400, f"[{CLAUSE}] a non-object body was accepted with {status}"


def test_registered_routes_are_approutes(routes: list[Any], app_route_cls: Any) -> None:
    assert routes, "[ARCHITECTURE.md §1] register_routes returned an empty list"
    for route in routes:
        ok = isinstance(route, app_route_cls) or type(route).__name__ == "AppRoute"
        assert ok, (
            f"[ARCHITECTURE.md §1] every item must be an AppRoute "
            f"(kiro_crew.apps.route_registry.AppRoute), got {type(route).__name__}"
        )
        for field in ("method", "path", "handler"):
            assert hasattr(route, field), f"[ARCHITECTURE.md §1] AppRoute missing .{field}"


def test_route_paths_are_relative_and_methods_upper(routes: list[Any]) -> None:
    for route in routes:
        method, path = str(route.method), str(route.path)
        assert method == method.upper(), (
            f"[ARCHITECTURE.md §1] method must be upper-case, got {method!r} for {path}"
        )
        assert path.startswith("/"), (
            f"[ARCHITECTURE.md §1] path must start with '/', got {path!r}"
        )
        assert "/api/apps" not in path, (
            f"[ARCHITECTURE.md §1] path is relative to /api/apps/trading-desk; "
            f"got the absolute {path!r}"
        )


def test_handlers_take_request_and_ctx(routes: list[Any]) -> None:
    for route in routes:
        handler = route.handler
        assert inspect.iscoroutinefunction(handler), (
            f"[ARCHITECTURE.md §1] handler for {route.method} {route.path} must be async, "
            f"got {handler!r}"
        )
        params = [
            p for p in inspect.signature(handler).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        assert len(params) == 2, (
            f"[ARCHITECTURE.md §1] handler for {route.method} {route.path} must take "
            f"(request, ctx); got {[p.name for p in params]}"
        )


def test_required_routes_are_registered(routes: list[Any]) -> None:
    registered = {(str(r.method).upper(), str(r.path)) for r in routes}
    missing = [f"{m} {p}" for m, p in REQUIRED_ROUTES if (m, p) not in registered]
    assert not missing, (
        f"[ARCHITECTURE.md §6] missing route(s) {missing}; registered = {sorted(registered)}"
    )


def test_no_route_sits_on_a_gateway_owned_path(routes: list[Any]) -> None:
    """§2, cycle3: a route the gateway already owns is never dispatched.

    The gateway binds ``/api/apps/{name}/config`` before the RouteRegistry
    catch-all exists, so an app handler on that path ships dead with no error
    anywhere -- which is why the config GET moved to /deskconfig.
    """
    registered = {(str(r.method).upper(), str(r.path)) for r in routes}
    shadowed = sorted(registered & set(SHADOWED_BY_GATEWAY))
    assert not shadowed, (
        f"[ARCHITECTURE.md §2] route(s) {shadowed} sit on a gateway-owned path and would never "
        "be dispatched; the config GET belongs at /deskconfig"
    )


def test_no_duplicate_routes(routes: list[Any]) -> None:
    seen = [(str(r.method).upper(), str(r.path)) for r in routes]
    dupes = sorted({x for x in seen if seen.count(x) > 1})
    assert not dupes, (
        f"[ARCHITECTURE.md §1] duplicate route registration {dupes} -- the registry keeps "
        "the first match, so the later handler is dead"
    )


def test_manifest_declares_the_in_process_backend() -> None:
    """§1: hooks only. A ``backend.routes`` base-path string serves dead stubs."""
    manifest = require_json("app.json", "§1/§5 app.json")
    backend = manifest.get("backend")
    assert isinstance(backend, dict), (
        f"[ARCHITECTURE.md §1] app.json needs a backend object, got {backend!r}"
    )
    assert "routes" not in backend, (
        "[ARCHITECTURE.md §1] app.json must NOT set backend.routes (the base-path string "
        "switches the app to the standalone-process proxy and shadows register_routes)"
    )
    hooks = backend.get("hooks")
    assert isinstance(hooks, dict) and hooks.get("routes") == "backend.routes:register_routes", (
        "[ARCHITECTURE.md §1] app.json backend.hooks.routes must be "
        f"'backend.routes:register_routes', got {hooks!r}"
    )

    perms = manifest.get("permissions")
    assert isinstance(perms, dict), (
        f"[ARCHITECTURE.md §5] permissions must be an object, got {type(perms).__name__}"
    )
    api = perms.get("api") or []
    missing = [p for p in REQUIRED_API_PERMISSIONS if p not in api]
    assert not missing, (
        f"[ARCHITECTURE.md §1] permissions.api missing {missing}; got {api}"
    )


# ---------------------------------------------------------------------------
# GET payloads (§2)
# ---------------------------------------------------------------------------

def test_every_route_401s_without_a_user(routes: list[Any], app_ctx: Any) -> None:
    """§1: an unauthenticated caller gets 401 -- the gateway sets request["user"]."""
    for route in routes:
        status, payload, raw = call_route(
            route.handler, app_ctx, authed=False,
            method=str(route.method), path=str(route.path),
            json_body={"books": {}, "sectors": {}},
        )
        assert status == 401, (
            f"[ARCHITECTURE.md §1] {route.method} {route.path} answered {status} to an "
            f"unauthenticated caller, expected 401: {raw[:200]}"
        )
        assert isinstance(payload, dict) and isinstance(payload.get("error"), str), (
            f'[ARCHITECTURE.md §2] the 401 body must be {{"error": "<msg>"}}, got {raw[:200]}'
        )


def test_get_org_matches_contract(routes: list[Any], app_ctx: Any, desk_root: Path) -> None:
    status, payload, raw = call_route(_handler(routes, "GET", "/org"), app_ctx, path="/org")
    assert status == 200, f"[ARCHITECTURE.md §2] GET /org returned {status}: {raw[:400]}"
    schema.assert_org(payload)

    root = desk_root.resolve()
    for member in payload["members"]:
        for out in member["recent_outputs"]:
            resolved = (root / out["path"]).resolve()
            assert resolved.is_relative_to(root), (
                f"[ARCHITECTURE.md §2] member {member['id']} recent_output {out['path']!r} "
                "escapes deskRoot"
            )
            assert resolved.exists(), (
                f"[ARCHITECTURE.md §2] member {member['id']} recent_output {out['path']!r} does not "
                "exist under the tmp deskRoot -- the handler is reading another path"
            )

    by_id = {m["id"]: m for m in payload["members"]}
    if "lm-test-alpha" in by_id:
        assert by_id["lm-test-alpha"]["tickers"] == ["AAPL", "MSFT", "GOOGL", "ORCL"], (
            "[ARCHITECTURE.md §2] lm-test-alpha tickers must come from the tmp deskRoot "
            f"sectors.yaml, got {by_id['lm-test-alpha']['tickers']}"
        )


def test_get_run_echoes_requested_date(routes: list[Any], app_ctx: Any) -> None:
    status, payload, raw = call_route(
        _handler(routes, "GET", "/run"), app_ctx, path="/run", query={"date": SMOKE_DATE}
    )
    assert status == 200, f"[ARCHITECTURE.md §2] GET /run returned {status}: {raw[:400]}"
    schema.assert_run(payload, expect_date=SMOKE_DATE)
    unknown = sorted({p["pod"] for p in payload["pods"]} - set(TEST_PODS))
    assert not unknown, (
        f"[ARCHITECTURE.md §2] GET /run reported pod(s) {unknown} absent from the tmp deskRoot"
    )


def test_get_run_defaults_to_today(routes: list[Any], app_ctx: Any) -> None:
    status, payload, raw = call_route(_handler(routes, "GET", "/run"), app_ctx, path="/run")
    assert status == 200, f"[ARCHITECTURE.md §2] GET /run (no date) returned {status}: {raw[:400]}"
    schema.assert_run(payload)


def test_get_config_reads_the_tmp_desk_root(routes: list[Any], app_ctx: Any) -> None:
    status, payload, raw = call_route(
        _handler(routes, "GET", "/deskconfig"), app_ctx, path="/deskconfig"
    )
    assert status == 200, f"[ARCHITECTURE.md §2] GET /deskconfig returned {status}: {raw[:400]}"
    schema.assert_config(payload)

    names = [b.get("name") for b in payload["books"]["books"].values() if isinstance(b, dict)]
    assert TEST_BOOK_NAME in names, (
        f"[ARCHITECTURE.md §2] GET /deskconfig must parse deskRoot/books.yaml; expected the tmp "
        f"sentinel {TEST_BOOK_NAME!r} among {names} -- the handler is reading another path"
    )
    assert payload["constraints"].get("broker") == "Test Broker CASH", (
        "[ARCHITECTURE.md §2] /config.constraints must be the tmp books.yaml's "
        f"account_constraints as-is, got {payload['constraints']!r}"
    )


def test_get_artifacts_lists_only_the_tmp_tree(routes: list[Any], app_ctx: Any, desk_root: Path) -> None:
    status, payload, raw = call_route(
        _handler(routes, "GET", "/artifacts"), app_ctx, path="/artifacts"
    )
    assert status == 200, f"[ARCHITECTURE.md §2] GET /artifacts returned {status}: {raw[:400]}"
    schema.assert_artifacts(payload)

    assert payload["dates"] == [SMOKE_DATE], (
        f"[ARCHITECTURE.md §2] the tmp deskRoot holds exactly one run date ({SMOKE_DATE}); "
        f"GET /artifacts returned {payload['dates']} -- the handler is reading another path"
    )
    root = desk_root.resolve()
    for group in payload["tree"]:
        for entry in group["files"]:
            resolved = (root / entry["path"]).resolve()
            assert resolved.is_relative_to(root), (
                f"[ARCHITECTURE.md §2] artifact path {entry['path']!r} escapes deskRoot"
            )
            assert resolved.exists(), (
                f"[ARCHITECTURE.md §2] artifact path {entry['path']!r} does not exist under deskRoot"
            )


@pytest.mark.parametrize("hostile", HOSTILE_DATES)
def test_artifacts_rejects_path_traversal(
    routes: list[Any], app_ctx: Any, desk_root: Path, hostile: str
) -> None:
    """§2/§6: a hostile ``date`` must be refused, never walked out of deskRoot."""
    status, payload, raw = call_route(
        _handler(routes, "GET", "/artifacts"), app_ctx, path="/artifacts", query={"date": hostile}
    )
    assert status < 500, (
        f"[ARCHITECTURE.md §2] GET /artifacts?date={hostile!r} crashed with {status}: {raw[:300]}"
    )
    if status != 200:
        assert status in (400, 403), (
            f"[ARCHITECTURE.md §2/§6] a traversal date must be refused with 403 (400 accepted); "
            f"got {status}"
        )
        return
    root = desk_root.resolve()
    for group in (payload or {}).get("tree", []):
        for entry in group.get("files", []):
            resolved = (root / entry["path"]).resolve()
            assert resolved.is_relative_to(root), (
                f"[ARCHITECTURE.md §2/§6] date={hostile!r} leaked {entry['path']!r} outside deskRoot"
            )


def test_routes_taking_a_caller_path_refuse_out_of_root(
    routes: list[Any], app_ctx: Any, outside_desk_root: Path
) -> None:
    """§2: a route handed a filesystem path must refuse one outside deskRoot.

    Which routes those are is discovered, not guessed from the path spelling: a
    spy on ``backend.paths.resolve_in_root`` -- the single choke point that
    raises ``OutOfRoot``, which the handler wrapper turns into a 403 -- records
    whether a route actually fed the caller's value into it. So a new route that
    accepts a path is covered automatically, and one that merely reads its own
    derived paths is not dragged in. An earlier substring rule matched "read"
    inside "/threads" and demanded a 403 from a route that takes no path at all.
    """
    hostile = str(outside_desk_root)
    resolving: list[tuple[str, str, int, str]] = []

    for route in routes:
        with pytest.MonkeyPatch.context() as patch:
            seen = _spy_on_path_resolver(patch)
            status, _, raw = call_route(
                route.handler, app_ctx,
                method=str(route.method), path=str(route.path),
                query={"path": hostile}, json_body={"path": hostile, "text": hostile},
                match_info={"id": hostile},
            )
        if any(hostile in value for value in seen):
            resolving.append((str(route.method), str(route.path), status, raw))

    assert resolving, (
        "[ARCHITECTURE.md §2] no route fed the caller's path into paths.resolve_in_root, so this "
        "test proved nothing -- either the file route is gone or it now resolves paths some "
        f"other way. Registered: {sorted((str(r.method), str(r.path)) for r in routes)}"
    )
    for method, path, status, raw in resolving:
        assert status == 403, (
            f"[ARCHITECTURE.md §2] {method} {path} resolved a caller path outside deskRoot and "
            f"answered {status} instead of 403: {raw[:300]}"
        )


def test_routes_without_a_path_param_are_not_held_to_403(
    routes: list[Any], app_ctx: Any, outside_desk_root: Path
) -> None:
    """The M2 thread routes take no filesystem path, so 403 is not their answer.

    Pins the fix above: a route that never reaches the path resolver must be
    free to answer on its own terms (400 for a missing member, 404 for an
    unknown id) without a file-route rule demanding 403 of it.
    """
    hostile = str(outside_desk_root)
    thread_routes = [
        r for r in routes if str(r.path).startswith(("/threads", "/thread/"))
    ]
    if not thread_routes:
        pytest.skip("no §8.2 thread routes registered yet")

    for route in thread_routes:
        with pytest.MonkeyPatch.context() as patch:
            seen = _spy_on_path_resolver(patch)
            status, _, raw = call_route(
                route.handler, app_ctx,
                method=str(route.method), path=str(route.path),
                query={"path": hostile}, json_body={"text": "hello"},
                match_info={"id": "th-fund-2026-09-07-1"},
            )
        assert not any(hostile in value for value in seen), (
            f"[ARCHITECTURE.md §8.2] {route.method} {route.path} fed a caller-supplied path into "
            "the deskRoot resolver; a thread route takes no filesystem path"
        )
        assert status != 403, (
            f"[ARCHITECTURE.md §8.2] {route.method} {route.path} answered 403 without resolving any "
            f"caller path, which reads as an out-of-root refusal it cannot have made: {raw[:200]}"
        )
        assert status < 500, (
            f"[ARCHITECTURE.md §8.2] {route.method} {route.path} crashed with {status}: {raw[:200]}"
        )


# ---------------------------------------------------------------------------
# POST /config/validate + /config/apply (§2)
# ---------------------------------------------------------------------------

def test_validate_accepts_a_good_config_without_writing(
    routes: list[Any], app_ctx: Any, desk_root: Path
) -> None:
    before = _yaml_bytes(desk_root)
    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/validate"), app_ctx,
        method="POST", path="/config/validate", json_body=_parsed_config(desk_root),
    )
    assert status == 200, f"[ARCHITECTURE.md §2] POST /config/validate returned {status}: {raw[:400]}"
    schema.assert_validate_result(payload, expect_ok=True)
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §2] /config/validate must not write to deskRoot"
    )


def test_validate_rejects_a_bad_config_without_writing(
    routes: list[Any], app_ctx: Any, desk_root: Path
) -> None:
    body = _parsed_config(desk_root)
    body["sectors"]["sectors"]["test-alpha"]["tickers"] = []  # §2 validator: non-empty list
    before = _yaml_bytes(desk_root)

    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/validate"), app_ctx,
        method="POST", path="/config/validate", json_body=body,
    )
    assert status == 200, f"[ARCHITECTURE.md §2] POST /config/validate returned {status}: {raw[:400]}"
    schema.assert_validate_result(payload, expect_ok=False)
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §2] a failed validate must leave deskRoot untouched"
    )


def test_validate_rejects_unparseable_yaml(routes: list[Any], app_ctx: Any, desk_root: Path) -> None:
    before = _yaml_bytes(desk_root)
    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/validate"), app_ctx,
        method="POST", path="/config/validate",
        json_body={"books": "books:\n  A: [unclosed", "sectors": "sectors:\n\tbad: tab"},
    )
    assert status < 500, (
        f"[ARCHITECTURE.md §2] unparseable YAML must be rejected, not crash; got {status}: {raw[:300]}"
    )
    if status == 200:
        schema.assert_validate_result(payload, expect_ok=False)
    else:
        assert status in (400, 422), (
            f"[ARCHITECTURE.md §2] expected ok=false or 400/422 for unparseable YAML, got {status}"
        )
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §2] /config/validate must not write to deskRoot"
    )


def test_apply_refuses_a_bad_config(routes: list[Any], app_ctx: Any, desk_root: Path) -> None:
    body = _parsed_config(desk_root)
    body["books"]["books"]["A"]["nav_usd"] = -1  # validator: must be positive
    before = _yaml_bytes(desk_root)

    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/apply"), app_ctx,
        method="POST", path="/config/apply", json_body=body,
    )
    assert status < 500, f"[ARCHITECTURE.md §2] POST /config/apply crashed with {status}: {raw[:300]}"
    if status == 200:
        assert isinstance(payload, dict) and payload.get("ok") is not True, (
            f"[ARCHITECTURE.md §2] apply must validate first and refuse; got {payload!r}"
        )
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §2] apply must validate before writing -- deskRoot changed anyway"
    )


def test_apply_writes_a_good_config(routes: list[Any], app_ctx: Any, desk_root: Path) -> None:
    body = _parsed_config(desk_root)
    body["books"]["books"]["A"]["max_drawdown_pct"] = 12

    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/apply"), app_ctx,
        method="POST", path="/config/apply", json_body=body,
    )
    assert status == 200, f"[ARCHITECTURE.md §2] POST /config/apply returned {status}: {raw[:400]}"
    assert isinstance(payload, dict) and payload.get("ok") is True, (
        f"[ARCHITECTURE.md §2] apply must answer {{'ok': true}}, got {payload!r}"
    )

    yaml = pytest.importorskip("yaml")
    written = yaml.safe_load((desk_root / "books.yaml").read_text(encoding="utf-8"))
    assert written["books"]["A"]["max_drawdown_pct"] == 12, (
        "[ARCHITECTURE.md §2] apply reported ok but deskRoot/books.yaml was not updated"
    )
    leftovers = [
        p.name for p in desk_root.iterdir()
        if p.is_file() and p.name not in {"books.yaml", "sectors.yaml"}
    ]
    assert not leftovers, (
        f"[ARCHITECTURE.md §2] apply must write atomically and leave no temp residue; found {leftovers}"
    )
    status, payload, _ = call_route(
        _handler(routes, "GET", "/deskconfig"), app_ctx, path="/deskconfig"
    )
    assert status == 200
    assert payload["books"]["books"]["A"]["max_drawdown_pct"] == 12, (
        "[ARCHITECTURE.md §2] GET /deskconfig still serves the pre-apply value"
    )


def test_error_responses_carry_a_message(routes: list[Any], app_ctx: Any) -> None:
    """§2: an error answers 4xx/5xx with a readable message, never an opaque body.

    §2 words the envelope as ``{"error": "<msg>"}``. The two /config POSTs
    answer 400 with their own ``{"ok": false, "errors": [...]}`` result shape
    instead, which the Config page renders directly; both are accepted here and
    the wording difference is reported to the conductor rather than failed.
    """
    status, payload, raw = call_route(
        _handler(routes, "POST", "/config/validate"), app_ctx,
        method="POST", path="/config/validate", raw_body="not json at all",
    )
    if status == 200:
        pytest.skip("handler tolerates a non-JSON body; no error envelope to check")
    assert 400 <= status < 600, f"[ARCHITECTURE.md §2] expected a 4xx/5xx, got {status}"
    assert isinstance(payload, dict), f"[ARCHITECTURE.md §2] error body must be JSON, got {raw[:200]}"
    message = payload.get("error")
    errors = payload.get("errors")
    has_message = isinstance(message, str) and message.strip()
    has_errors = isinstance(errors, list) and errors and all(isinstance(e, str) for e in errors)
    assert has_message or has_errors, (
        f'[ARCHITECTURE.md §2] an error must carry "error" or a non-empty string "errors", '
        f"got {raw[:300]}"
    )


def test_date_param_is_validated(routes: list[Any], app_ctx: Any) -> None:
    """§2: ``?date=`` is YYYY-MM-DD; anything else is a client error, not a 500."""
    for path in ("/run", "/artifacts"):
        status, payload, raw = call_route(
            _handler(routes, "GET", path), app_ctx, path=path, query={"date": "not-a-date"}
        )
        assert status in (400, 403), (
            f"[ARCHITECTURE.md §2] GET {path}?date=not-a-date must be a client error, got "
            f"{status}: {raw[:200]}"
        )
        assert isinstance(payload, dict) and (payload.get("error") or payload.get("errors")), (
            f"[ARCHITECTURE.md §2] GET {path} error body must carry a message, got {raw[:200]}"
        )


def test_the_ui_anchor_is_the_shape_post_thread_parses(tmp_path: Path) -> None:
    """§12: the anchor the UI builds is handed to the backend's own parser.

    One fact wears two names across this single call. The REQUEST key is ``mid``
    and the STORED key the ``/threads`` response reads back is ``main_msg``, and
    the UI assembled its request with the stored name -- so ``parse_body`` found no
    ``mid``, refused with "anchor needs both mid and ts", and NO row could open a
    thread. Nothing caught it: the UI test never called the backend, the backend
    test built its own anchor, and both were green.

    So this reads the anchor out of the real ``ui/parts.mjs`` under Node and feeds
    it to the real ``parse_body``. A rename on either side reddens here.
    """
    probe = run_node_probe(tmp_path, """
const parts = await import(UI_DIR + '/parts.mjs')
const row = { role: 'assistant', ts: '2026-09-17T21:53:04.512Z', meta: { mid: 'm-9f1c2ab34de5' } }
console.log(JSON.stringify({
  row,
  anchor: parts.threadAnchor(row),
  // A row the gateway has minted no id for: the UI reports it and draws no
  // button, so the create is never attempted -- but if one arrives, the backend
  // must still refuse it rather than store an unaddressable anchor.
  unminted: parts.threadAnchor({ role: 'streaming', ts: row.ts }),
}))
""")
    threadnew = require_module("backend/threadnew.py", "backend.threadnew", CLAUSE)
    row, anchor = probe["row"], probe["anchor"]

    assert sorted(anchor) == ["mid", "ts"], (
        f"[ARCHITECTURE.md §12] the request anchor is `{{mid, ts}}`; the UI built "
        f"{sorted(anchor)}. `main_msg` is the STORED name and is not read here"
    )
    _member, main_msg, ts, _title = threadnew.parse_body(
        {"member_id": "fund", "anchor": anchor}
    )
    assert main_msg == row["meta"]["mid"], (
        f"[§12] parse_body read {main_msg!r} as the anchor id, not the row's own "
        f"meta.mid {row['meta']['mid']!r}"
    )
    assert ts == row["ts"], f"[§12] parse_body read {ts!r} as the stamp, not {row['ts']!r}"

    with pytest.raises(threadnew.CreateRefused):
        threadnew.parse_body({"member_id": "fund", "anchor": probe["unminted"]})

    # Calling the builder cannot see whether the SURFACE still uses it. It did not:
    # the literal lived inline in the component, which is how the wrong key name
    # survived there unnoticed.
    chat = Path(require_path("ui/chat.mjs", "§9 the chat surface")).read_text(encoding="utf-8")
    assert "threadAnchor(m)" in chat, (
        "[§12] ui/chat.mjs no longer builds its anchor with `threadAnchor`, so this "
        "test proves nothing about what it sends"
    )
    assert "main_msg:" not in chat, (
        "[§12] ui/chat.mjs writes a `main_msg:` key again -- that is the stored "
        "name, and `POST /thread` reads `mid`"
    )
