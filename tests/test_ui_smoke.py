"""UI smoke test (ARCHITECTURE.md §6): ``node --check ui/index.mjs``.

Parse-only. It cannot render the app, but a syntax error in the ESM entry makes
the whole sidebar page blank, and that is exactly the failure a parse check
catches for free.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from helpers import require_path


def test_ui_entry_parses() -> None:
    entry = require_path("ui/index.mjs", "§0 ui track deliverable")
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH -- run `node --check ui/index.mjs` manually (ARCHITECTURE.md §6)")
    proc = subprocess.run(
        [node, "--check", str(entry)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, (
        f"[ARCHITECTURE.md §6] node --check ui/index.mjs failed:\n{proc.stdout}\n{proc.stderr}"
    )


def _ui_source() -> str:
    """The UI's live source, whole (rev9 split one file into nine).

    Versioned deploy copies (index-0201.mjs …) are byte-copies of index.mjs and
    excluded, so a stale copy can neither satisfy nor fail a contract check.
    """
    root = require_path("ui", "§0 ui track deliverable")
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(root.glob("*.mjs"))
        if not re.match(r"index-\d+\.mjs$", p.name)
    )


def test_ui_calls_backend_under_its_app_prefix() -> None:
    """§3: every backend fetch goes to ``/api/apps/trading-desk/<route>``."""
    source = _ui_source()
    # The prefix is assembled from a constant since the rev9 split
    # (`const API = `/api/apps/${APP}``), so both spellings satisfy §3.
    assert "/api/apps/trading-desk" in source or (
        re.search(r"/api/apps/\$\{APP\}", source) and "APP = 'trading-desk'" in source
    ), (
        "[ARCHITECTURE.md §3] the UI must call the backend under "
        "/api/apps/trading-desk/<route>; no such path found in ui/*.mjs"
    )


def test_ui_does_not_fetch_the_gateway_shadowed_config_route() -> None:
    """§2, cycle3: the app's config GET is ``/deskconfig``.

    ``/api/apps/{name}/config`` belongs to the gateway (it serves
    data/config.json), so a UI fetch of ``/config`` reads that file instead of
    the desk's books/sectors -- a wrong-payload bug with no error to notice.
    """
    source = _ui_source()
    shadowed = re.findall(r"""load\(\s*['"`]/config['"`]""", source)
    assert not shadowed, (
        "[ARCHITECTURE.md §2] the UI fetches the app route '/config', which the gateway "
        "shadows; the desk config GET is '/deskconfig'"
    )
    assert re.search(r"""['"`]/deskconfig['"`]""", source), (
        "[ARCHITECTURE.md §2] the UI never fetches '/deskconfig', so the Config page has "
        "no live data source"
    )
