"""pytest fixtures for the Trading Desk App suite (ARCHITECTURE.md §6).

The suite never touches the real desk data root. ``desk_root`` builds a minimal
artifact tree in a tmp dir -- the same shape the backend reads (§2 data
sources) -- and ``app_ctx`` points the app at it, so a handler that ignores
``deskRoot`` and hard-codes the real path fails on the sentinel values baked
into the tmp tree.

Run: ``pytest tests/ -x -q``   (never ``-n auto``; see ARCHITECTURE.md §6)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from helpers import APP_NAME, FIXTURES_DIR, REAL_DESK_ROOT, REPO_ROOT, SMOKE_DATE

# The app's own modules are imported as ``backend.routes`` / ``scripts.x``.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Candidate checkouts of the gateway, needed for the real AppRoute/AppContext.
_GATEWAY_SRC_CANDIDATES = (
    *(Path(p) for p in os.environ.get("KIROCREW_SRC", "").split(":") if p.strip()),
)

#: Sentinel values that only exist in the tmp tree, so a handler reading the
#: real desk root instead of ``deskRoot`` is caught rather than tolerated.
TEST_BOOK_NAME = "Test Book A (tmp desk root)"
TEST_PODS = ("test-alpha", "test-beta")
TEST_TICKERS = {"test-alpha": ["AAPL", "MSFT", "GOOGL", "ORCL"], "test-beta": ["XOM"]}


# ---------------------------------------------------------------------------
# Gateway types (real when importable, otherwise a faithful stub)
# ---------------------------------------------------------------------------

def _load_gateway_types() -> tuple[Any, Any]:
    """Return (AppRoute, AppContext), importing the real gateway if possible."""
    try:
        from kiro_crew.apps.context import AppContext  # type: ignore
        from kiro_crew.apps.route_registry import AppRoute  # type: ignore
        return AppRoute, AppContext
    except Exception:
        pass

    for candidate in _GATEWAY_SRC_CANDIDATES:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.append(str(candidate))
    try:
        from kiro_crew.apps.context import AppContext  # type: ignore
        from kiro_crew.apps.route_registry import AppRoute  # type: ignore
        return AppRoute, AppContext
    except Exception:
        return _install_gateway_stub()


def _install_gateway_stub() -> tuple[Any, Any]:
    """Register a minimal ``kiro_crew.apps`` so ``backend.routes`` can import.

    Mirrors the real dataclasses (route_registry.AppRoute, context.AppContext)
    field for field. Only used when no gateway checkout is available.
    """
    from dataclasses import dataclass, field

    @dataclass
    class AppRoute:  # noqa: D401 - mirrors kiro_crew.apps.route_registry.AppRoute
        method: str
        path: str
        handler: Any

    @dataclass
    class AppHealthStatus:
        status: str = "healthy"
        issues: list = field(default_factory=list)
        last_checked: str = ""

        def mark_degraded(self, issue: str) -> None:
            self.status = "degraded"
            self.issues.append(issue)

        def mark_error(self, issue: str) -> None:
            self.status = "error"
            self.issues.append(issue)

    @dataclass
    class AppContext:
        name: str
        data_dir: Path
        config: dict = field(default_factory=dict)
        logger: Any = field(default_factory=lambda: logging.getLogger("kirocrew.app"))
        cron: Any = None
        events: Any = None
        storage: Any = None
        spawn: Any = None
        job: Any = None
        health: Any = field(default_factory=AppHealthStatus)

    pkg = types.ModuleType("kiro_crew")
    pkg.__path__ = []  # type: ignore[attr-defined]
    apps = types.ModuleType("kiro_crew.apps")
    apps.__path__ = []  # type: ignore[attr-defined]
    registry = types.ModuleType("kiro_crew.apps.route_registry")
    registry.AppRoute = AppRoute  # type: ignore[attr-defined]
    context = types.ModuleType("kiro_crew.apps.context")
    context.AppContext = AppContext  # type: ignore[attr-defined]
    context.AppHealthStatus = AppHealthStatus  # type: ignore[attr-defined]

    sys.modules.setdefault("kiro_crew", pkg)
    sys.modules.setdefault("kiro_crew.apps", apps)
    sys.modules["kiro_crew.apps.route_registry"] = registry
    sys.modules["kiro_crew.apps.context"] = context
    return AppRoute, AppContext


APP_ROUTE_CLS, APP_CONTEXT_CLS = _load_gateway_types()


# ---------------------------------------------------------------------------
# Minimal desk data root
# ---------------------------------------------------------------------------

SECTORS_YAML = """\
# tmp desk root for tests -- not the real sectors.yaml
sectors:
  test-alpha:
    line_manager: line-manager
    analyst_copies: 2
    tickers:
      - AAPL
      - MSFT
      - GOOGL
      - ORCL
  test-beta:
    line_manager: line-manager
    analyst_copies: 2
    tickers:
      - XOM
"""

BOOKS_YAML = f"""\
# tmp desk root for tests -- synthetic NAV, not the real books.yaml
account_constraints:
  broker: "Test Broker CASH"
  options_approval: long_single_leg_only
  can_sell_or_write_a_leg: false
  spreads_executable: false
  allowed_option_orders: [buy_to_open_long_call, buy_to_open_long_put]

books:
  A:
    name: "{TEST_BOOK_NAME}"
    nav_usd: 1000
    horizon_days_min: 90
    horizon_days_max: 365
    max_drawdown_pct: 15
    instruments_allowed: [stock]
    stop_loss_style: fundamental
    pod_weights:
      test-alpha: 60
      test-beta: 40
  B:
    name: "Test Book B (tmp desk root)"
    nav_usd: 2000
    horizon_days_min: 5
    horizon_days_max: 60
    max_drawdown_pct: 25
    instruments_allowed: [stock, option_long_call]
    stop_loss_style: technical
    pod_weights:
      test-alpha: 50
      test-beta: 50
"""

BAD_SECTORS_YAML = """\
sectors:
  test-alpha:
    line_manager: line-manager
    tickers: []
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def desk_root(tmp_path: Path) -> Path:
    """A minimal copy of the desk artifact tree (ARCHITECTURE.md §2 data sources).

    One run date (``SMOKE_DATE``), two pods, one CEO brief, per-analyst files
    under the pod's report directory, and an empty ``runs/`` so the /run route
    exercises the derive path rather than reading ``events.jsonl``.
    """
    root = tmp_path / "trading-desk"
    _write(root / "sectors.yaml", SECTORS_YAML)
    _write(root / "books.yaml", BOOKS_YAML)

    # The validator is invoked by /config/validate (§2); copy it so the tmp tree is
    # self-sufficient. It comes from this repository's own desk-root scaffold, not
    # from whatever desk the person running the tests happens to have -- a test that
    # reads a real desk passes or fails on that machine's data.
    reference_validator = REPO_ROOT / "config" / "engine" / "validate_config.py"
    if reference_validator.is_file():
        (root / "engine").mkdir(parents=True, exist_ok=True)
        shutil.copy2(reference_validator, root / "engine" / "validate_config.py")

    _write(root / "memory" / "briefs" / f"{SMOKE_DATE}.md", "# CEO brief (test)\n")
    for pod in TEST_PODS:
        _write(root / "teams" / pod / "reports" / f"{SMOKE_DATE}.md", f"# {pod} report (test)\n")
        for ticker in TEST_TICKERS[pod]:
            _write(
                root / "teams" / pod / "reports" / SMOKE_DATE / f"{ticker}.md",
                f"# {ticker} analyst note (test)\n",
            )
    _write(root / "teams" / "desk" / "reports" / f"{SMOKE_DATE}.md", "# desk rollup (test)\n")
    _write(root / "teams" / "risk-pod" / "reports" / f"{SMOKE_DATE}.md", "# risk review (test)\n")
    (root / "runs").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def outside_desk_root(tmp_path: Path) -> Path:
    """A file outside deskRoot, for the traversal / 403 checks (§2, §6)."""
    return _write(tmp_path / "outside" / "secret.md", "must never be served\n")


@pytest.fixture
def app_data_dir(tmp_path: Path, desk_root: Path) -> Path:
    """The app's data dir, carrying ``config.json`` (§1, §5).

    §1, cycle3: the file carries ``appRoot`` beside ``deskRoot`` -- the UI reads
    it to locate ``fixtures/*.json``, so the test copy mirrors both keys.
    """
    data_dir = tmp_path / "app-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text(
        json.dumps({"deskRoot": str(desk_root), "appRoot": str(REPO_ROOT)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return data_dir


@pytest.fixture
def app_ctx(app_data_dir: Path, desk_root: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """An AppContext pointed at the tmp desk root.

    deskRoot is offered through every channel §1/§5 allows -- ``config.json``
    in the data dir, ``ctx.config``, and the env -- so the test does not
    dictate which one the backend reads. The tmp tree carries sentinel values
    (see TEST_BOOK_NAME) so ignoring all three is still caught.
    """
    monkeypatch.setenv("TRADING_DESK_ROOT", str(desk_root))
    monkeypatch.setenv("DESK_ROOT", str(desk_root))
    return APP_CONTEXT_CLS(
        name=APP_NAME,
        data_dir=app_data_dir,
        config={"deskRoot": str(desk_root)},
    )


# ---------------------------------------------------------------------------
# Shared fixtures directory (infrastructure track, ARCHITECTURE.md §0/§5)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def app_route_cls() -> Any:
    return APP_ROUTE_CLS
