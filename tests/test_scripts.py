"""Script tests (ARCHITECTURE.md §6 -> §0/§2/§4).

Three modules under ``scripts/`` are cross-track interfaces, because
``backend/routes.py`` imports them in-process:

* ``desk_events.py``  -- derive/append the §4 run events behind GET /run
* ``config_io.py``    -- read, validate and write back the two YAMLs
* ``members.py``      -- aggregate the member state GET /org serves

Everything runs against the tmp desk root from ``conftest.desk_root``; the real
desk is never read or written.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import schema
from conftest import TEST_PODS
from helpers import REPO_ROOT, SMOKE_DATE, require_module, require_path

#: Files apply() is allowed to leave behind: the two YAMLs plus the timestamped
#: backups it documents (a safe_load/safe_dump round trip drops comments).
ALLOWED_DESK_FILES = ("books.yaml", "sectors.yaml")


def _run_cli(script: Path, argv: list[str], desk_root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["TRADING_DESK_ROOT"] = str(desk_root)
    env["DESK_ROOT"] = str(desk_root)
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT), env=env,
    )


def _temp_residue(desk_root: Path) -> list[str]:
    """Temp-file leftovers only -- ``.bak.<ts>`` copies are a documented output."""
    return sorted(
        p.name for p in desk_root.iterdir()
        if p.is_file()
        and p.name not in ALLOWED_DESK_FILES
        and (".tmp" in p.name or p.name.endswith("~") or p.name.startswith(".#"))
    )


def _yaml_bytes(desk_root: Path) -> dict[str, bytes]:
    return {name: (desk_root / name).read_bytes() for name in ALLOWED_DESK_FILES}


def _parsed(desk_root: Path) -> dict[str, Any]:
    yaml = pytest.importorskip("yaml")
    return {
        name.removesuffix(".yaml"): yaml.safe_load((desk_root / name).read_text(encoding="utf-8"))
        for name in ALLOWED_DESK_FILES
    }


# ---------------------------------------------------------------------------
# desk_events.py -- §2 GET /run data source, §4 event schema
# ---------------------------------------------------------------------------

@pytest.fixture
def desk_events() -> Any:
    require_path("scripts/desk_events.py", "§0/§2 scripts track")
    return require_module("scripts/desk_events.py", "scripts.desk_events", "§2 GET /run")


def test_derived_events_match_the_event_schema(desk_events: Any, desk_root: Path) -> None:
    events = desk_events.derive_events(desk_root, SMOKE_DATE)
    assert isinstance(events, list) and events, (
        "[ARCHITECTURE.md §2] derive found no events for the tmp desk root, which holds "
        f"{SMOKE_DATE} reports for {list(TEST_PODS)} plus a CEO brief"
    )
    for i, ev in enumerate(events):
        schema.assert_event_record(ev, where=f"derive_events[{i}]")
    for ev in events:
        assert ev["run_date"] == SMOKE_DATE, (
            f"[ARCHITECTURE.md §4] every derived event must carry run_date={SMOKE_DATE}, "
            f"got {ev['run_date']!r}"
        )


def test_derive_is_idempotent(desk_events: Any, desk_root: Path) -> None:
    """§6: re-deriving an unchanged run must produce the same events."""
    first = desk_events.derive_events(desk_root, SMOKE_DATE)
    second = desk_events.derive_events(desk_root, SMOKE_DATE)
    assert [dict(e, at="") for e in second] == [dict(e, at="") for e in first], (
        "[ARCHITECTURE.md §6] derive is not idempotent -- a second derive of an unchanged run "
        "returned different events"
    )


def test_append_is_idempotent(desk_events: Any, desk_root: Path) -> None:
    """§6: appending the same derived events twice must not duplicate a line."""
    events = desk_events.derive_events(desk_root, SMOKE_DATE)
    desk_events.append_events(desk_root, SMOKE_DATE, events)
    path = Path(desk_events.events_path(desk_root, SMOKE_DATE))
    assert path.is_file(), f"[ARCHITECTURE.md §2] append_events wrote no {path.name}"
    after_first = path.read_text(encoding="utf-8")

    desk_events.append_events(desk_root, SMOKE_DATE, events)
    assert path.read_text(encoding="utf-8") == after_first, (
        "[ARCHITECTURE.md §6] a second append of the same events grew "
        "runs/<date>/events.jsonl -- append must be identity-deduped"
    )

    lines = [ln for ln in after_first.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        schema.assert_event_record(json.loads(line), where=f"events.jsonl[{i}]")
    read_back = desk_events.read_events(desk_root, SMOKE_DATE)
    assert len(read_back) == len(lines), (
        f"[ARCHITECTURE.md §2] read_events returned {len(read_back)} of {len(lines)} written events"
    )


def test_derive_cli_emits_jsonl(desk_events: Any, desk_root: Path) -> None:
    script = REPO_ROOT / "scripts" / "desk_events.py"
    proc = _run_cli(script, ["derive", "--date", SMOKE_DATE, "--desk-root", str(desk_root)], desk_root)
    assert proc.returncode == 0, (
        f"[ARCHITECTURE.md §2] `desk_events.py derive --date {SMOKE_DATE}` exited "
        f"{proc.returncode}: {proc.stderr[:400]}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "[ARCHITECTURE.md §2] derive printed nothing for a date with artifacts on disk"
    for i, line in enumerate(lines):
        schema.assert_event_record(json.loads(line), where=f"derive stdout[{i}]")


def test_derive_cli_writes_nothing_without_write_flag(desk_events: Any, desk_root: Path) -> None:
    """§2: plain derive is a read -- only ``--write`` persists."""
    script = REPO_ROOT / "scripts" / "desk_events.py"
    _run_cli(script, ["derive", "--date", SMOKE_DATE, "--desk-root", str(desk_root)], desk_root)
    path = Path(desk_events.events_path(desk_root, SMOKE_DATE))
    assert not path.exists(), (
        f"[ARCHITECTURE.md §2] derive without --write created {path}; derive must not persist"
    )


def test_derive_cli_write_is_idempotent(desk_events: Any, desk_root: Path) -> None:
    script = REPO_ROOT / "scripts" / "desk_events.py"
    argv = ["derive", "--date", SMOKE_DATE, "--desk-root", str(desk_root), "--write"]
    first = _run_cli(script, argv, desk_root)
    assert first.returncode == 0, f"[ARCHITECTURE.md §2] derive --write failed: {first.stderr[:300]}"
    path = Path(desk_events.events_path(desk_root, SMOKE_DATE))
    after_first = path.read_text(encoding="utf-8")

    second = _run_cli(script, argv, desk_root)
    assert second.returncode == 0, f"[ARCHITECTURE.md §2] derive --write failed: {second.stderr[:300]}"
    assert path.read_text(encoding="utf-8") == after_first, (
        "[ARCHITECTURE.md §6] `derive --write` is not idempotent -- the second run grew events.jsonl"
    )


def test_append_rejects_an_unknown_kind(desk_events: Any, desk_root: Path) -> None:
    """§4 fixes the kind vocabulary."""
    script = REPO_ROOT / "scripts" / "desk_events.py"
    proc = _run_cli(
        script,
        ["append", "--run-date", SMOKE_DATE, "--who", "fund", "--kind", "started",
         "--msg", "should be refused", "--desk-root", str(desk_root)],
        desk_root,
    )
    assert proc.returncode != 0, (
        "[ARCHITECTURE.md §4] append accepted kind='started', which is outside "
        "dispatched|stage|delivered|failed|note"
    )


# ---------------------------------------------------------------------------
# config_io.py -- §2 GET /config, POST /config/validate, POST /config/apply
# ---------------------------------------------------------------------------

@pytest.fixture
def config_io() -> Any:
    require_path("scripts/config_io.py", "§0/§2 scripts track")
    return require_module("scripts/config_io.py", "scripts.config_io", "§2 GET /config")


def test_load_matches_config_schema(config_io: Any, desk_root: Path) -> None:
    schema.assert_config(config_io.load(desk_root))


def test_validate_accepts_the_tmp_config(config_io: Any, desk_root: Path) -> None:
    body = _parsed(desk_root)
    before = _yaml_bytes(desk_root)
    result = config_io.validate(body["books"], body["sectors"], desk_root)
    schema.assert_validate_result(result, expect_ok=True)
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §2] validate must not write to deskRoot"
    )


@pytest.mark.parametrize(
    "name,mutate",
    [
        ("empty tickers", lambda b: b["sectors"]["sectors"]["test-alpha"].__setitem__("tickers", [])),
        ("negative nav", lambda b: b["books"]["books"]["A"].__setitem__("nav_usd", -1)),
        ("bad stop style", lambda b: b["books"]["books"]["A"].__setitem__("stop_loss_style", "vibes")),
        ("analyst_copies 0",
         lambda b: b["sectors"]["sectors"]["test-alpha"].__setitem__("analyst_copies", 0)),
        ("unknown pod weight",
         lambda b: b["books"]["books"]["A"]["pod_weights"].__setitem__("no-such-pod", 5)),
    ],
    ids=["empty-tickers", "negative-nav", "bad-stop-style", "analyst-copies-0", "unknown-pod"],
)
def test_validate_rejects_a_bad_config_without_writing(
    config_io: Any, desk_root: Path, name: str, mutate: Any
) -> None:
    body = _parsed(desk_root)
    mutate(body)
    before = _yaml_bytes(desk_root)

    result = config_io.validate(body["books"], body["sectors"], desk_root)
    schema.assert_validate_result(result, expect_ok=False)
    assert _yaml_bytes(desk_root) == before, (
        f"[ARCHITECTURE.md §6] validate({name}) wrote to deskRoot; validate must never persist"
    )
    assert not _temp_residue(desk_root), (
        f"[ARCHITECTURE.md §6] validate({name}) left temp residue: {_temp_residue(desk_root)}"
    )


def test_apply_refuses_an_invalid_config(config_io: Any, desk_root: Path) -> None:
    body = _parsed(desk_root)
    body["sectors"]["sectors"]["test-alpha"]["analyst_copies"] = 0
    before = _yaml_bytes(desk_root)

    try:
        result: Any = config_io.apply(body["books"], body["sectors"], desk_root)
    except Exception as exc:  # refusing by raising is fine
        result = {"ok": False, "errors": [repr(exc)]}
    assert result.get("ok") is not True, (
        f"[ARCHITECTURE.md §2] apply must validate first and refuse; got {result!r}"
    )
    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §6] a failed validate must leave both YAMLs untouched"
    )


def test_apply_writes_a_valid_config(config_io: Any, desk_root: Path) -> None:
    yaml = pytest.importorskip("yaml")
    body = _parsed(desk_root)
    body["books"]["books"]["A"]["max_drawdown_pct"] = 11

    result = config_io.apply(body["books"], body["sectors"], desk_root)
    assert result.get("ok") is True, f"[ARCHITECTURE.md §2] apply must answer ok=true, got {result!r}"

    written = yaml.safe_load((desk_root / "books.yaml").read_text(encoding="utf-8"))
    assert written["books"]["A"]["max_drawdown_pct"] == 11, (
        "[ARCHITECTURE.md §2] apply reported ok but books.yaml was not updated"
    )
    assert written["account_constraints"]["broker"] == "Test Broker CASH", (
        "[ARCHITECTURE.md §2] apply dropped books.yaml's account_constraints block"
    )
    assert not _temp_residue(desk_root), (
        f"[ARCHITECTURE.md §6] atomic write left temp residue: {_temp_residue(desk_root)}"
    )
    schema.assert_config(config_io.load(desk_root))


def test_apply_is_atomic(config_io: Any, desk_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§6 原子写: a failure at the rename must leave the original intact."""
    body = _parsed(desk_root)
    body["books"]["books"]["A"]["max_drawdown_pct"] = 9
    before = _yaml_bytes(desk_root)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("injected: rename failed mid-write")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(Exception):
        config_io.apply(body["books"], body["sectors"], desk_root)

    assert _yaml_bytes(desk_root) == before, (
        "[ARCHITECTURE.md §6] apply must write a temp file and os.replace it into place: with "
        "os.replace failing, the YAML on disk changed anyway (an in-place truncating write "
        "loses the config on any mid-write failure)"
    )
    assert not _temp_residue(desk_root), (
        f"[ARCHITECTURE.md §6] a failed atomic write left its temp file behind: {_temp_residue(desk_root)}"
    )


# ---------------------------------------------------------------------------
# members.py -- §2 GET /org data source
# ---------------------------------------------------------------------------

def test_aggregate_state_returns_org_shaped_members(desk_root: Path) -> None:
    module = require_module("scripts/members.py", "scripts.members", "§0/§2 scripts track")
    roster = require_path("crews/members.json", "§4 crews/members.json")
    members = module.aggregate_state(desk_root, roster)
    schema.assert_org({"members": members})

    root = desk_root.resolve()
    for member in members:
        for out in member["recent_outputs"]:
            resolved = (root / out["path"]).resolve()
            assert resolved.is_relative_to(root), (
                f"[ARCHITECTURE.md §2] member {member['id']} recent_output {out['path']!r} "
                "escapes deskRoot"
            )
            assert resolved.exists(), (
                f"[ARCHITECTURE.md §2] member {member['id']} recent_output {out['path']!r} does not "
                "exist under the tmp deskRoot -- the aggregator is reading another path"
            )


def test_aggregate_state_reads_tickers_from_the_desk_root(desk_root: Path, tmp_path: Path) -> None:
    """§2: a line-manager's tickers come from deskRoot/sectors.yaml.

    The committed roster is generated from the example config (pods
    example-megacap/example-energy), which is deliberately different from the temp
    desk's sentinel pods (test-alpha/test-beta) -- so reading the committed roster
    here would prove nothing. Generate a roster FOR the temp desk instead, by
    running gen_members.py with DESK_ROOT pointed at it and writing to a temp path,
    then check the aggregated tickers come from that desk's sectors.yaml.
    """
    module = require_module("scripts/members.py", "scripts.members", "§0/§2 scripts track")
    gen_members = require_path("crews/gen_members.py", "§4 crews/members.json")

    roster = tmp_path / "members.json"
    proc = _run_cli(gen_members, ["--out", str(roster)], desk_root)
    assert proc.returncode == 0, (
        f"[ARCHITECTURE.md §4] gen_members.py --out failed for the temp desk root: "
        f"{proc.stderr[:400]}"
    )
    assert roster.is_file(), (
        f"[ARCHITECTURE.md §4] gen_members.py --out wrote no roster at {roster}"
    )

    members = module.aggregate_state(desk_root, roster)
    by_id = {m["id"]: m for m in members}
    lm = by_id.get("lm-test-alpha")
    assert lm is not None, (
        "[ARCHITECTURE.md §4] a roster generated from the temp desk (pods "
        f"{list(TEST_PODS)}) must carry lm-test-alpha; got {sorted(by_id)}"
    )
    assert lm["tickers"] == ["AAPL", "MSFT", "GOOGL", "ORCL"], (
        "[ARCHITECTURE.md §2] lm-test-alpha tickers must come from the tmp deskRoot sectors.yaml, "
        f"got {lm['tickers']}"
    )
