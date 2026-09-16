"""The shared mock data must already satisfy the backend contract.

``fixtures/`` is the infrastructure track's first deliverable and every other
track reads it (ARCHITECTURE.md §0), so its schema IS §2's schema -- the UI built
against a fixture that drifts from §2 breaks the moment the real route answers.
Each test skips until the file lands; ``TD_REQUIRE_ALL=1`` turns those skips
into failures for the acceptance run.

``crews/members.json`` is checked here too: the backend reads it directly for
/org (§2 data source), so its shape is a cross-track interface (§4).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import schema
from helpers import FIXTURE_DATE, SMOKE_DATE, require_json, require_path

FORBIDDEN_DUTY_TOKENS = schema.FORBIDDEN_DUTY_TOKENS


def test_org_fixture_matches_contract() -> None:
    schema.assert_org(require_json("fixtures/org.json", "§3 + §2 GET /org"))


def _run_fixture(fixtures_dir: Path) -> Path | None:
    """The run fixture the UI would land on: §3's name, the smoke date, then the fallback."""
    for name in (f"run-{FIXTURE_DATE}.json", f"run-{SMOKE_DATE}.json", "run.json"):
        candidate = fixtures_dir / name
        if candidate.exists():
            return candidate
    return None


def test_run_fixture_matches_contract(fixtures_dir: Path) -> None:
    require_path("fixtures", "§0 fixtures are the shared read-only dependency")
    path = _run_fixture(fixtures_dir)
    if path is None:
        pytest.skip(
            f"no run fixture yet -- expected fixtures/run-{FIXTURE_DATE}.json (ARCHITECTURE.md §3) "
            "or the run.json fallback the UI reads"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = path.stem.removeprefix("run-") if path.stem.startswith("run-") else None
    schema.assert_run(payload, expect_date=expected)


def test_config_fixture_matches_contract() -> None:
    schema.assert_config(require_json("fixtures/config.json", "§3 + §2 GET /config"))


def test_artifacts_fixture_matches_contract() -> None:
    schema.assert_artifacts(require_json("fixtures/artifacts.json", "§3 + §2 GET /artifacts"))


def test_every_run_fixture_matches_contract(fixtures_dir: Path) -> None:
    """Every ``run*.json`` on disk is held to §2, including the fallback copy."""
    require_path("fixtures", "§0 fixtures are the shared read-only dependency")
    found = sorted(fixtures_dir.glob("run*.json"))
    if not found:
        pytest.skip("no fixtures/run*.json yet (ARCHITECTURE.md §3)")
    for path in found:
        date = path.stem.removeprefix("run-") if path.stem.startswith("run-") else None
        schema.assert_run(json.loads(path.read_text(encoding="utf-8")), expect_date=date)


def test_every_artifacts_fixture_matches_contract(fixtures_dir: Path) -> None:
    require_path("fixtures", "§0 fixtures are the shared read-only dependency")
    found = sorted(fixtures_dir.glob("artifacts*.json"))
    if not found:
        pytest.skip("no fixtures/artifacts*.json yet (ARCHITECTURE.md §3)")
    for path in found:
        schema.assert_artifacts(json.loads(path.read_text(encoding="utf-8")))


def test_ui_fixture_fallbacks_exist(fixtures_dir: Path) -> None:
    """§3: the mock names the UI falls back to must actually be on disk.

    Only the literal names are checkable -- a templated ``run-${date}.json`` is
    resolved at runtime and is covered by the fallback that follows it.
    """
    entry = require_path("ui/index.mjs", "§3 mock development")
    source = entry.read_text(encoding="utf-8")
    literals = sorted(set(re.findall(r"""['"]([A-Za-z0-9_-]+\.json)['"]""", source)))
    referenced = [
        name for name in literals
        if name in {"org.json", "config.json", "artifacts.json", "run.json"}
        or name.startswith(("run-", "artifacts-", "org-", "config-"))
    ]
    if not referenced:
        pytest.skip("ui/index.mjs names no literal fixture file (ARCHITECTURE.md §3)")
    missing = [name for name in referenced if not (fixtures_dir / name).exists()]
    assert not missing, (
        f"[ARCHITECTURE.md §3] ui/index.mjs reads fixtures/{missing} but the infrastructure track "
        f"delivered {sorted(p.name for p in fixtures_dir.glob('*.json'))}"
    )


def test_fixtures_agree_with_each_other(fixtures_dir: Path) -> None:
    """A pod named by /run must be a pod some /org member manages."""
    org_path = fixtures_dir / "org.json"
    run_path = _run_fixture(fixtures_dir)
    if not (org_path.exists() and run_path is not None):
        pytest.skip("org.json + a run fixture not both delivered yet (ARCHITECTURE.md §3)")

    org = json.loads(org_path.read_text(encoding="utf-8"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    org_pods = {m["pod"] for m in org["members"] if m.get("pod")}
    run_pods = {p["pod"] for p in run["pods"]}
    unknown = sorted(run_pods - org_pods)
    assert not unknown, (
        f"[ARCHITECTURE.md §2] run fixture reports pod(s) {unknown} that no /org member manages; "
        f"/org pods = {sorted(org_pods)}"
    )

    member_ids = {m["id"] for m in org["members"]}
    chain_ids = {link["member"] for link in run["chain"]}
    dangling = sorted(chain_ids - member_ids)
    assert not dangling, (
        f"[ARCHITECTURE.md §2] run fixture chain names member(s) {dangling} absent from /org"
    )


def test_threads_fixture_matches_contract() -> None:
    """§8.2 GET /threads shape, including the no-session-key red line."""
    schema.assert_threads(require_json("fixtures/threads.json", "§8.2 fixtures"))


def test_thread_detail_fixture_matches_contract() -> None:
    """§8.2 GET /thread/{id} shape, including the no-session-key red line."""
    schema.assert_thread_detail(require_json("fixtures/thread-detail.json", "§8.2 fixtures"))


def test_thread_fixtures_agree_with_each_other(fixtures_dir: Path) -> None:
    """The detail fixture must be one of the listed threads, told consistently."""
    listing = require_path("fixtures/threads.json", "§8.2 fixtures")
    detail = require_path("fixtures/thread-detail.json", "§8.2 fixtures")

    threads = json.loads(listing.read_text(encoding="utf-8"))["threads"]
    one = json.loads(detail.read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in threads}
    assert one["id"] in by_id, (
        f"[ARCHITECTURE.md §8.2] thread-detail.json is {one['id']!r}, absent from threads.json "
        f"{sorted(by_id)}"
    )
    listed = by_id[one["id"]]

    # rev6 (§11.2): the detail is the listing item, re-derived and picked by id --
    # the backend states it cannot drift, and these two files are built
    # independently, so equality is the cross-check. The load-bearing pair is
    # named first so a red points at the field the UI breaks on: slot_key is the
    # session the panel opens and the composer posts to, and kind is how the chip
    # and the panel label it. Disagreeing means the chip and the drawer describe
    # two different sessions.
    assert one["slot_key"] == listed["slot_key"], (
        f"[ARCHITECTURE.md §11.2] thread {one['id']} points at two sessions: "
        f"{one['slot_key']!r} in the detail fixture, {listed['slot_key']!r} in the listing"
    )
    assert one["kind"] == listed["kind"], (
        f"[ARCHITECTURE.md §11.1] thread {one['id']} is a {one['kind']!r} in the detail fixture and a "
        f"{listed['kind']!r} in the listing"
    )
    diverged = sorted(k for k in set(one) | set(listed) if one.get(k) != listed.get(k))
    assert not diverged, (
        f"[ARCHITECTURE.md §11.2] thread {one['id']} disagrees between the two fixtures on "
        f"{diverged} -- the detail is the same object the listing publishes, so any difference "
        "is one of the two being stale"
    )


def test_thread_anchors_hold_the_rev2_shape(fixtures_dir: Path) -> None:
    """§8.2 rev2: every anchor in either fixture is null or the message shape.

    The shape itself lives in ``schema.assert_anchor`` and is already applied by
    the two fixture tests; this walks the anchors that are actually present so a
    listing whose entries all carry null -- which the shape check passes -- does
    not read as evidence that the anchored form was ever exercised.
    """
    listing = require_path("fixtures/threads.json", "§8.2 fixtures")
    detail = require_path("fixtures/thread-detail.json", "§8.2 fixtures")

    anchors = [
        (t["id"], t["anchor"])
        for t in json.loads(listing.read_text(encoding="utf-8"))["threads"]
    ]
    one = json.loads(detail.read_text(encoding="utf-8"))
    anchors.append((one["id"], one["anchor"]))

    for thread_id, anchor in anchors:
        schema.assert_anchor(anchor, where=f"{thread_id}.anchor")

    anchored = [(i, a) for i, a in anchors if a is not None]
    if not anchored:
        pytest.skip(
            "no fixture thread carries a message-level anchor yet (§8.2 rev2 allows the null "
            "downgrade, so this is data, not a fault)"
        )
    for thread_id, anchor in anchored:
        assert anchor["ts"] != anchor["main_msg"], (
            f"[ARCHITECTURE.md §8.2] {thread_id} anchor collapses its two keys into one value"
        )


def test_thread_fixtures_name_real_members(fixtures_dir: Path) -> None:
    """§11.1: a thread's participants, owner and agent all exist in the roster."""
    roster_path = require_path("crews/members.json", "§4 crews/members.json")
    listing = require_path("fixtures/threads.json", "§8.2 fixtures")
    detail = require_path("fixtures/thread-detail.json", "§8.2 fixtures")

    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    members = roster["members"] if isinstance(roster, dict) and "members" in roster else roster
    known = {m["id"] for m in members}
    agents = {str(m.get("agent")) for m in members if m.get("agent")}

    threads = json.loads(listing.read_text(encoding="utf-8"))["threads"]
    one = json.loads(detail.read_text(encoding="utf-8"))

    for thread in threads + [one]:
        unknown = sorted(set(thread["participants"]) - known)
        assert not unknown, (
            f"[ARCHITECTURE.md §8.2] thread {thread['id']} names participant(s) {unknown} absent "
            "from crews/members.json"
        )
        member = schema.THREAD_ID_RE.match(thread["id"]).group("member")
        assert member in known, (
            f"[ARCHITECTURE.md §8.1] thread id {thread['id']!r} hangs off {member!r}, "
            "which is not a roster member"
        )
        # rev6 (§11.1): whose session it is, and the agent that session runs.
        # Null owner is the documented downgrade; a named one must be real.
        assert thread["member"] is None or thread["member"] in known, (
            f"[ARCHITECTURE.md §11.1] thread {thread['id']} belongs to {thread['member']!r}, "
            "which is not a roster member"
        )
        # Classification is BY AGENT, so an agent no member runs cannot have been
        # classified as either kind -- it would have failed the agent test.
        assert thread["agent"] in agents, (
            f"[ARCHITECTURE.md §11.1] thread {thread['id']} runs {thread['agent']!r}, which no roster "
            f"member declares -- classification is by agent, so this session is not the desk's"
        )
        # §11.1: the conductor's own clone runs the conductor's own agent.
        if thread["kind"] == "thread":
            owner = next((m for m in members if m["id"] == member), None)
            assert owner is not None and thread["agent"] == owner.get("agent"), (
                f"[ARCHITECTURE.md §11.1] {thread['id']} is a clone of {member!r} but runs "
                f"{thread['agent']!r}, not that member's own agent "
                f"{(owner or {}).get('agent')!r} -- a different agent makes it a dispatch"
            )


def test_members_json_matches_contract() -> None:
    """crews/members.json is what the backend reads for /org (§2 + §4).

    §4 as amended 2026-09-16: six standing roles, one ``lm-<pod>`` per pod, and
    that pod's ten ``ic-<pod>-<role>`` rows -- the /org identity fields plus
    ``agent`` and the five adjudicated extras. ``slot_hint`` is required of every
    row that HAS a standing session; an IC is spawned per ticker per round and
    carries none. ``duty_template`` is scoped to ``desk`` and the line-managers,
    which is where a rendered duty needs pod and tickers substituted in.

    The count is derived from the pod list rather than pinned to a literal, so
    adding a pod to sectors.yaml does not fail here -- what IS pinned is the
    shape of each layer, which is the drift worth catching.
    """
    data: Any = require_json("crews/members.json", "§4 crews/members.json")
    members = data["members"] if isinstance(data, dict) and "members" in data else data
    assert isinstance(members, list) and members, (
        "[ARCHITECTURE.md §4] crews/members.json must define a non-empty member list"
    )
    standing = [m for m in members if not str(m.get("id", "")).startswith(("lm-", "ic-"))]
    line_managers = [m for m in members if str(m.get("id", "")).startswith("lm-")]
    ics = [m for m in members if str(m.get("id", "")).startswith("ic-")]
    assert len(standing) == 6, (
        "[ARCHITECTURE.md §4] six standing roles (fund macro desk risk trader scrum), "
        f"got {len(standing)}: {[m.get('id') for m in standing]}"
    )
    # How MANY roles a pod carries is configuration (config/roles.yaml), so it is
    # not asserted. What is asserted is that every pod carries the SAME ones: a
    # roster where one pod is missing a role is a generator bug, and pinning a
    # number here would instead refuse a desk that legitimately runs five.
    per_pod: dict[str, set[str]] = {}
    for member in ics:
        parent = str(member.get("parent", ""))
        role = str(member.get("id", ""))[len(f"{parent.replace('lm-', 'ic-')}-"):]
        per_pod.setdefault(parent, set()).add(role)
    assert set(per_pod) == {str(m["id"]) for m in line_managers}, (
        "[ARCHITECTURE.md §4] every IC parents to a line-manager and every pod has ICs; "
        f"pods with ICs {sorted(per_pod)} vs line-managers "
        f"{sorted(str(m['id']) for m in line_managers)}"
    )
    role_sets = {frozenset(roles) for roles in per_pod.values()}
    assert len(role_sets) <= 1, (
        "[ARCHITECTURE.md §4] every pod carries the same roles from config/roles.yaml; "
        f"found {len(role_sets)} different sets: "
        f"{ {pod: sorted(r) for pod, r in per_pod.items()} }"
    )
    assert len(members) == len(standing) + len(line_managers) + len(ics), (
        "[ARCHITECTURE.md §4] the roster holds only standing roles, line-managers and ICs"
    )

    ids: list[str] = []
    for i, m in enumerate(members):
        at = f"crews/members.json[{i}]"
        assert isinstance(m, dict), f"[ARCHITECTURE.md §4] {at} must be an object"
        required = ["id", "name", "title", "duty", "parent", "group", "pod",
                    "tickers", "agent",
                    "alias", "avatar_letter", "reports_label", "output_sources"]
        if not str(m.get("id", "")).startswith("ic-"):
            required.append("slot_hint")
        for key in required:
            assert key in m, f"[ARCHITECTURE.md §4] {at} missing required key {key!r}"
        mid = m["id"]
        assert isinstance(mid, str) and schema.MEMBER_ID_RE.match(mid), (
            f"[ARCHITECTURE.md §2/§4] {at}.id must be fund|macro|desk|risk|trader|scrum"
            f"|lm-<pod>|ic-<pod>-<role>, got {mid!r}"
        )
        ids.append(mid)

        for field in ("duty", "duty_template"):
            text = m.get(field)
            if text is None:
                continue
            assert isinstance(text, str) and text.strip(), (
                f"[ARCHITECTURE.md §4] {at}.{field} must be text"
            )
            leaked = [t for t in FORBIDDEN_DUTY_TOKENS if t in text.lower()]
            assert not leaked, (
                f"[ARCHITECTURE.md §4] {at}.{field} leaks orchestration-internal vocabulary "
                f"{leaked} -- duty is the outward-facing job description"
            )

        agent = m["agent"]
        assert isinstance(agent, str) and agent.startswith("tada-"), (
            f"[ARCHITECTURE.md §4] {at}.agent must name a tada-* agent, got {agent!r}"
        )
        assert isinstance(m["tickers"], list), f"[ARCHITECTURE.md §4] {at}.tickers must be a list"

        sources = m["output_sources"]
        assert isinstance(sources, list), (
            f"[ARCHITECTURE.md §4] {at}.output_sources must be a list of {{label, dir}}"
        )
        for j, src in enumerate(sources):
            assert isinstance(src, dict) and isinstance(src.get("label"), str), (
                f"[ARCHITECTURE.md §4] {at}.output_sources[{j}] needs a string label"
            )
            directory = src.get("dir")
            assert isinstance(directory, str) and directory and not directory.startswith("/"), (
                f"[ARCHITECTURE.md §4] {at}.output_sources[{j}].dir must be relative to deskRoot, "
                f"got {directory!r}"
            )
            assert ".." not in directory.split("/"), (
                f"[ARCHITECTURE.md §4] {at}.output_sources[{j}].dir must not escape deskRoot"
            )

        if mid.startswith("lm-") or mid == "desk":
            assert m.get("duty_template"), (
                f"[ARCHITECTURE.md §4] {at} needs duty_template (desk and every line-manager "
                "render duty from pod/tickers)"
            )
        if mid.startswith("lm-"):
            assert m["pod"] and m["group"] and m["tickers"], (
                f"[ARCHITECTURE.md §2/§4] {at} is a line-manager and must carry pod, group and tickers"
            )
        else:
            assert not m["tickers"], (
                f"[ARCHITECTURE.md §2/§4] {at}: only a line-manager carries tickers"
            )

    line_managers = [i for i in ids if i.startswith("lm-")]
    # The pod COUNT comes from config/sectors.yaml, so it is not pinned -- only
    # that there is at least one, since a desk with no pods has no research chain.
    assert line_managers, (
        "[ARCHITECTURE.md §4] at least one line-manager expected; the roster has none, "
        "which means sectors.yaml defined no pods"
    )
    assert len(set(ids)) == len(ids), (
        f"[ARCHITECTURE.md §4] duplicate member id(s) in crews/members.json: "
        f"{sorted({i for i in ids if ids.count(i) > 1})}"
    )
    roots = [m["id"] for m in members if m["parent"] is None]
    assert roots == ["fund"], (
        f"[ARCHITECTURE.md §2] exactly one parent-less member, 'fund', expected; got {roots}"
    )
    known = set(ids)
    for m in members:
        if m["parent"] is not None:
            assert m["parent"] in known, (
                f"[ARCHITECTURE.md §2] member {m['id']!r} has parent {m['parent']!r} "
                "which is not a member id"
            )
