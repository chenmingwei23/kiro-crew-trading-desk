"""Mutation proof for ``tests/schema.py``.

A schema assertion that accepts everything is worse than none, so each §2
payload is checked twice: the contract's own example must pass, and a list of
single-field mutations must each be rejected. This runs with no dependency on
any other track, so the assertions are trustworthy before the first fixture or
route exists.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import pytest

import schema
from schema import ContractError


# --- ARCHITECTURE.md §2 examples, expanded to complete payloads ----------------

ORG: dict[str, Any] = {
    "members": [
        {
            "id": "fund", "name": "fund-manager", "title": "Fund Manager",
            "duty": "Runs the desk's day-to-day operations, breaking the day's intent into research and allocation actions, and owns the final conclusion.",
            "parent": None, "group": None,
            "pod": None, "tickers": [], "state": "working",
            "state_msg": "organizing today's research", "slot_key": "chat-1001-1700000001",
            "recent_outputs": [{"label": "Yesterday's brief", "path": "memory/briefs/2026-09-08.md"}],
        },
        {
            "id": "lm-test-alpha", "name": "line-manager", "title": "Line Manager",
            "duty": "Runs the test-alpha pod (AAPL, MSFT, GOOGL, ORCL): converges the pod's conclusions into one pod report.",
            "parent": "desk",
            "group": "Book A · test-alpha pod", "pod": "test-alpha",
            "tickers": ["AAPL", "MSFT", "GOOGL", "ORCL"], "state": "idle",
            "state_msg": "pod report delivered today", "slot_key": None,
            "recent_outputs": [{"label": "pod report", "path": "teams/test-alpha/reports/2026-09-07.md"}],
        },
        {
            "id": "desk", "name": "desk-manager", "title": "Desk Manager",
            "duty": "Rolls each pod's conclusions into one executable desk view, resolving conflicts and priorities across pods.",
            "parent": "fund", "group": None,
            "pod": None, "tickers": [], "state": "blocked",
            "state_msg": "waiting on risk review", "slot_key": None, "recent_outputs": [],
        },
    ]
}

RUN: dict[str, Any] = {
    "date": "2026-09-09", "live": True,
    "chain": [{"member": "fund", "steps": [{"label": "brief received", "state": "done", "at": "08:58"},
                                           {"label": "brief", "state": "todo", "at": None}]}],
    "pods": [{"pod": "test-alpha", "state": "done",
              "stages": [{"name": "Analysis", "done": 32, "total": 32}],
              "delivered_at": "09:41", "fail_reason": None}],
    "events": [{"at": "09:41", "who": "test-alpha", "msg": "pod report delivered", "hot": True}],
}

CONFIG: dict[str, Any] = {
    "books": {"account_constraints": {"broker": "Test"}, "books": {"A": {"name": "Core", "nav_usd": 1000}}},
    "sectors": {"sectors": {"test-alpha": {"line_manager": "line-manager",
                                           "analyst_copies": 2, "tickers": ["AAPL"]}}},
    "constraints": {"broker": "Test", "options_approval": "long_single_leg_only"},
}

VALIDATE_OK: dict[str, Any] = {"ok": True, "errors": [], "diff": ""}

ARTIFACTS: dict[str, Any] = {
    "dates": ["2026-09-09", "2026-09-07"],
    "tree": [
        {"group": "CEO brief", "files": [{"label": "brief", "path": "memory/briefs/2026-09-09.md"}]},
        {"group": "test-alpha", "files": [{"label": "pod report", "path": "teams/test-alpha/reports/2026-09-09.md"}]},
    ],
}

EVENT: dict[str, Any] = {
    "at": "2026-09-09T09:41:00Z", "run_date": "2026-09-09", "who": "test-alpha",
    "kind": "delivered", "msg": "pod report delivered",
}

# --- §11.2 rev6 threads (a thread is the session the conductor opened) ------

THREADS: dict[str, Any] = {
    "threads": [
        {
            "id": "th-fund-2026-09-07-1", "kind": "dispatch", "title": "macro brief",
            "member": "macro", "state": "done",
            "opened_at": "2026-09-07T16:24:06.270955Z",
            "participants": ["fund", "macro"],
            "last_msg": "today's macro brief delivered",
            "anchor": None,
            "entry_count": 2,
            "last_ts": "2026-09-07T16:24:06.270955Z",
            "slot_key": "chat-9002-1757260800",
            "agent": "tada-macro-strategist",
            "refs": {"run_date": "2026-09-07",
                     "artifacts": ["teams/macro/reports/2026-09-07.md"]},
        },
        {
            "id": "th-fund-2026-09-07-2", "kind": "thread", "title": "test-alpha pod research",
            "member": "fund", "state": "running",
            "opened_at": "2026-09-07T16:43:30.607782Z",
            "participants": ["fund", "desk", "lm-test-alpha"],
            "last_msg": "risk review in progress",
            "anchor": None,
            "entry_count": 3,
            "last_ts": "2026-09-07T17:10:00.000000Z",
            "slot_key": "chat-9001-1757260800",
            "agent": "tada-fund-manager",
            "refs": {"run_date": "2026-09-07", "artifacts": []},
        },
    ]
}

#: A listing for a line-manager, whose id carries hyphens of its own -- the
#: case a greedy thread-id pattern gets wrong.
THREADS_LINE_MANAGER: dict[str, Any] = {
    "threads": [
        {
            "id": "th-lm-test-alpha-2026-09-07-1", "kind": "thread", "title": "AAPL deep dive",
            "member": "lm-test-alpha", "state": "running",
            "opened_at": "2026-09-07T16:50:00.000000Z",
            "participants": ["lm-test-alpha"],
            "last_msg": "four angles under research in parallel",
            "anchor": None,
            "entry_count": 0,
            "last_ts": None,
            "slot_key": "chat-9003-1757260800",
            "agent": "tada-line-manager",
            "refs": {"run_date": "2026-09-07", "artifacts": []},
        },
    ]
}

#: §11.2: the detail IS the listing item, re-derived and picked by id -- so the
#: example is literally the second listed thread, and a field the two payloads
#: disagree about cannot hide behind two separate examples.
THREAD_DETAIL: dict[str, Any] = copy.deepcopy(THREADS["threads"][1])

SAY_RESULT: dict[str, Any] = {"ok": True, "delivered_to": "lm-test-alpha"}

#: §8.2 rev2: the message-level anchor. Both keys are carried because the SPA
#: matches a rendered row on ts while mid is the authoritative identity.
ANCHOR: dict[str, Any] = {
    "main_msg": "m-fba3291fbb0b4b2b",
    "ts": "2026-09-07T16:19:06.270955Z",
    "preview": "Research the test-alpha pod, focus on HBM supply",
}

ANCHOR_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("missing main_msg", lambda d: d.pop("main_msg")),
    ("missing ts", lambda d: d.pop("ts")),
    ("missing preview", lambda d: d.pop("preview")),
    ("extra key", lambda d: d.__setitem__("slot_key", "chat-1-2")),
    ("mid equals ts", lambda d: d.__setitem__("main_msg", d["ts"])),
    ("main_msg not a string", lambda d: d.__setitem__("main_msg", 17)),
    ("preview over 60 characters", lambda d: d.__setitem__("preview", "x" * 61)),
    ("session key in preview",
     lambda d: d.__setitem__("preview", "see chat-1001-1700000001")),
    ("session key in main_msg",
     lambda d: d.__setitem__("main_msg", "dashboard_chat-1-2")),
]


def _mutate(base: dict[str, Any], apply: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    clone = copy.deepcopy(base)
    apply(clone)
    return clone


# --- the examples must pass ------------------------------------------------

def test_contract_examples_pass() -> None:
    schema.assert_org(ORG)
    schema.assert_run(RUN, expect_date="2026-09-09")
    schema.assert_config(CONFIG)
    schema.assert_validate_result(VALIDATE_OK, expect_ok=True)
    schema.assert_artifacts(ARTIFACTS)
    schema.assert_event_record(EVENT)
    schema.assert_event_record(
        dict(EVENT, kind="stage", stage={"name": "Analysis", "done": 3, "total": 32})
    )


def test_not_started_is_a_pod_state() -> None:
    """§2, cycle1 adjudication: a pod that has not started the day."""
    payload = _mutate(RUN, lambda d: d["pods"][0].update(
        {"state": "not_started", "stages": [], "delivered_at": None}
    ))
    schema.assert_run(payload)
    assert "not_started" not in schema.STEP_STATES, (
        "not_started is a pod state, not a chain-step state"
    )


# --- and every single-field violation must be caught ----------------------

ORG_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("member id off-vocabulary", lambda d: d["members"][0].__setitem__("id", "ceo")),
    ("state not in enum", lambda d: d["members"][0].__setitem__("state", "running")),
    ("duty leaks internals", lambda d: d["members"][0].__setitem__("duty", "run plan-all then write sentinel")),
    ("missing key", lambda d: d["members"][0].pop("state_msg")),
    ("extra key", lambda d: d["members"][0].__setitem__("cost_usd", 3)),
    ("tickers on a non-line-manager", lambda d: d["members"][0].__setitem__("tickers", ["AAPL"])),
    ("line-manager without tickers", lambda d: d["members"][1].__setitem__("tickers", [])),
    ("line-manager without pod", lambda d: d["members"][1].__setitem__("pod", None)),
    ("lower-case ticker", lambda d: d["members"][1].__setitem__("tickers", ["nvda"])),
    ("two roots", lambda d: d["members"][2].__setitem__("parent", None)),
    ("dangling parent", lambda d: d["members"][2].__setitem__("parent", "nobody")),
    ("parent cycle", lambda d: d["members"][0].__setitem__("parent", "desk")),
    ("duplicate ids", lambda d: d["members"][2].__setitem__("id", "fund")),
    ("absolute artifact path",
     lambda d: d["members"][0]["recent_outputs"][0].__setitem__("path", "/etc/passwd")),
    ("traversal artifact path",
     lambda d: d["members"][0]["recent_outputs"][0].__setitem__("path", "../../etc/passwd")),
    ("empty members", lambda d: d.__setitem__("members", [])),
    ("multi-line state_msg", lambda d: d["members"][0].__setitem__("state_msg", "a\nb")),
]

RUN_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("bad date", lambda d: d.__setitem__("date", "09/09/2026")),
    ("live not bool", lambda d: d.__setitem__("live", "yes")),
    ("step state off-enum", lambda d: d["chain"][0]["steps"][0].__setitem__("state", "running")),
    ("step clock not HH:MM", lambda d: d["chain"][0]["steps"][0].__setitem__("at", "9:41am")),
    ("pod state off-enum", lambda d: d["pods"][0].__setitem__("state", "todo")),
    ("stage done > total", lambda d: d["pods"][0]["stages"][0].__setitem__("done", 33)),
    ("stage total not int", lambda d: d["pods"][0]["stages"][0].__setitem__("total", "32")),
    ("event hot not bool", lambda d: d["events"][0].__setitem__("hot", 1)),
    ("event missing who", lambda d: d["events"][0].pop("who")),
    ("chain link missing steps", lambda d: d["chain"][0].pop("steps")),
    ("pods not a list", lambda d: d.__setitem__("pods", {})),
]

CONFIG_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("books unwrapped", lambda d: d.__setitem__("books", {"A": {}})),
    ("sectors unwrapped", lambda d: d.__setitem__("sectors", {"test-alpha": {}})),
    ("pod missing tickers", lambda d: d["sectors"]["sectors"]["test-alpha"].pop("tickers")),
    ("constraints empty", lambda d: d.__setitem__("constraints", {})),
    ("constraints missing", lambda d: d.pop("constraints")),
]

ARTIFACT_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("dates not newest-first", lambda d: d.__setitem__("dates", ["2026-09-07", "2026-09-09"])),
    ("duplicate date", lambda d: d.__setitem__("dates", ["2026-09-09", "2026-09-09"])),
    ("bad date format", lambda d: d.__setitem__("dates", ["2026-9-9"])),
    ("absolute file path", lambda d: d["tree"][0]["files"][0].__setitem__("path", "/tmp/x.md")),
    ("traversal file path",
     lambda d: d["tree"][0]["files"][0].__setitem__("path", "teams/../../secret.md")),
    ("group missing files", lambda d: d["tree"][0].pop("files")),
    ("file missing label", lambda d: d["tree"][0]["files"][0].pop("label")),
]

EVENT_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("kind off-enum", lambda d: d.__setitem__("kind", "started")),
    ("at not ISO", lambda d: d.__setitem__("at", "09:41")),
    ("run_date not a date", lambda d: d.__setitem__("run_date", "today")),
    ("extra key", lambda d: d.__setitem__("tokens", 12)),
    ("stage total missing", lambda d: d.__setitem__("stage", {"name": "Analysis", "done": 1})),
]

VALIDATE_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("ok false with no errors", lambda d: d.__setitem__("ok", False)),
    ("errors not strings", lambda d: (d.__setitem__("ok", False), d.__setitem__("errors", [{"m": 1}]))),
    ("diff missing", lambda d: d.pop("diff")),
    ("ok not bool", lambda d: d.__setitem__("ok", "true")),
]


@pytest.mark.parametrize("name,mutate", ORG_MUTATIONS, ids=[n for n, _ in ORG_MUTATIONS])
def test_org_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_org(_mutate(ORG, mutate))


@pytest.mark.parametrize("name,mutate", RUN_MUTATIONS, ids=[n for n, _ in RUN_MUTATIONS])
def test_run_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_run(_mutate(RUN, mutate))


@pytest.mark.parametrize("name,mutate", CONFIG_MUTATIONS, ids=[n for n, _ in CONFIG_MUTATIONS])
def test_config_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_config(_mutate(CONFIG, mutate))


@pytest.mark.parametrize("name,mutate", ARTIFACT_MUTATIONS, ids=[n for n, _ in ARTIFACT_MUTATIONS])
def test_artifacts_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_artifacts(_mutate(ARTIFACTS, mutate))


@pytest.mark.parametrize("name,mutate", EVENT_MUTATIONS, ids=[n for n, _ in EVENT_MUTATIONS])
def test_event_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_event_record(_mutate(EVENT, mutate))


@pytest.mark.parametrize("name,mutate", VALIDATE_MUTATIONS, ids=[n for n, _ in VALIDATE_MUTATIONS])
def test_validate_result_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_validate_result(_mutate(VALIDATE_OK, mutate))


def test_run_date_echo_is_enforced() -> None:
    with pytest.raises(ContractError):
        schema.assert_run(RUN, expect_date="2026-09-07")


def test_validate_expect_ok_is_enforced() -> None:
    with pytest.raises(ContractError):
        schema.assert_validate_result(VALIDATE_OK, expect_ok=False)


THREADS_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("thread id not th-<member>-<date>-<seq>",
     lambda d: d["threads"][0].__setitem__("id", "thread-1")),
    ("thread id member not a member id",
     lambda d: d["threads"][0].__setitem__("id", "th-ceo-2026-09-07-1")),
    ("state off-enum", lambda d: d["threads"][0].__setitem__("state", "blocked")),
    ("opened_at not ISO", lambda d: d["threads"][0].__setitem__("opened_at", "16:24")),
    ("participant not a member id",
     lambda d: d["threads"][0].__setitem__("participants", ["ceo"])),
    ("no participants", lambda d: d["threads"][0].__setitem__("participants", [])),
    ("last_msg multi-line", lambda d: d["threads"][0].__setitem__("last_msg", "a\nb")),
    ("refs missing run_date", lambda d: d["threads"][0]["refs"].pop("run_date")),
    ("artifact path absolute",
     lambda d: d["threads"][0]["refs"].__setitem__("artifacts", ["/etc/passwd"])),
    ("artifact path traverses",
     lambda d: d["threads"][0]["refs"].__setitem__("artifacts", ["teams/../../x.md"])),
    ("duplicate thread id",
     lambda d: d["threads"][1].__setitem__("id", d["threads"][0]["id"])),
    ("missing key", lambda d: d["threads"][0].pop("title")),
    ("anchor key absent", lambda d: d["threads"][0].pop("anchor")),
    ("entry_count absent", lambda d: d["threads"][0].pop("entry_count")),
    ("last_ts absent", lambda d: d["threads"][0].pop("last_ts")),
    ("entry_count negative", lambda d: d["threads"][0].__setitem__("entry_count", -1)),
    ("entry_count not an int", lambda d: d["threads"][0].__setitem__("entry_count", "2")),
    ("entry_count is a bool", lambda d: d["threads"][0].__setitem__("entry_count", True)),
    ("last_ts set while entry_count is 0",
     lambda d: d["threads"][0].update({"entry_count": 0})),
    ("last_ts not a string", lambda d: d["threads"][0].__setitem__("last_ts", 1788796746)),
    ("session key in last_ts",
     lambda d: d["threads"][0].__setitem__("last_ts", "chat-1001-1700000001")),
    ("extra key", lambda d: d["threads"][0].__setitem__("session", "x")),
    ("session key in last_msg",
     lambda d: d["threads"][0].__setitem__("last_msg", "dispatched chat-1001-1700000001")),
    ("session key in title",
     lambda d: d["threads"][0].__setitem__("title", "td-fund-1788796788")),
    ("qualified session key in title",
     lambda d: d["threads"][0].__setitem__("title", "dashboard_fund")),
    # rev6 (§11.2): the four fields that make a thread openable. slot_key and
    # agent are what the panel and the composer are built from, so a thread
    # missing or misspelling either is a dead chip, not a cosmetic fault.
    ("kind absent", lambda d: d["threads"][0].pop("kind")),
    ("kind off-enum", lambda d: d["threads"][0].__setitem__("kind", "clone")),
    ("kind null", lambda d: d["threads"][0].__setitem__("kind", None)),
    ("member absent", lambda d: d["threads"][0].pop("member")),
    ("member not a member id", lambda d: d["threads"][0].__setitem__("member", "analyst")),
    ("member absent from participants",
     lambda d: d["threads"][0].__setitem__("member", "trader")),
    ("slot_key absent", lambda d: d["threads"][0].pop("slot_key")),
    ("slot_key null", lambda d: d["threads"][0].__setitem__("slot_key", None)),
    ("slot_key empty", lambda d: d["threads"][0].__setitem__("slot_key", "")),
    ("slot_key not a key shape", lambda d: d["threads"][0].__setitem__("slot_key", "fund")),
    ("slot_key carries the dashboard: prefix",
     lambda d: d["threads"][0].__setitem__("slot_key", "dashboard:chat-9002-1757260800")),
    ("slot_key carries the dashboard_ prefix",
     lambda d: d["threads"][0].__setitem__("slot_key", "dashboard_chat-9002-1757260800")),
    ("slot_key is a reset-minted main key",
     lambda d: d["threads"][0].__setitem__("slot_key", "td-fund-1788796788")),
    ("two threads share one slot_key",
     lambda d: d["threads"][1].__setitem__("slot_key", d["threads"][0]["slot_key"])),
    ("agent absent", lambda d: d["threads"][0].pop("agent")),
    ("agent null", lambda d: d["threads"][0].__setitem__("agent", None)),
    ("agent not a desk agent", lambda d: d["threads"][0].__setitem__("agent", "gpu-dev")),
    # The exemption is by PATH, not by value: the very key slot_key legitimately
    # carries is still a leak anywhere else in the payload.
    ("slot_key's own key repeated in the title",
     lambda d: d["threads"][0].__setitem__("title", d["threads"][0]["slot_key"])),
    ("slot_key's own key repeated in anchor preview",
     lambda d: d["threads"][0].__setitem__(
         "anchor", dict(ANCHOR, preview=f"opened {d['threads'][0]['slot_key']}"))),
]

THREAD_DETAIL_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("anchor neither null nor an object", lambda d: d.__setitem__("anchor", "msg-7")),
    ("anchor missing a key",
     lambda d: d.__setitem__("anchor", {k: v for k, v in ANCHOR.items() if k != "ts"})),
    ("anchor preview too long",
     lambda d: d.__setitem__("anchor", dict(ANCHOR, preview="x" * 61))),
    ("anchor leaks a session key",
     lambda d: d.__setitem__("anchor", dict(ANCHOR, preview="see chat-1001-1700000001"))),
    ("state off-enum", lambda d: d.__setitem__("state", "open")),
    ("session key in id", lambda d: d.__setitem__("id", "th-fund-2026-09-07-1-chat-1-2")),
    # rev6 deleted entries: the panel renders the clone's own transcript, so a
    # detail still folding a timeline is carrying a field the contract dropped.
    ("entries still present", lambda d: d.__setitem__("entries", [])),
    ("kind absent", lambda d: d.pop("kind")),
    ("kind off-enum", lambda d: d.__setitem__("kind", "message")),
    ("member not a member id", lambda d: d.__setitem__("member", "analyst")),
    ("slot_key absent", lambda d: d.pop("slot_key")),
    ("slot_key carries the dashboard: prefix",
     lambda d: d.__setitem__("slot_key", "dashboard:chat-9001-1757260800")),
    ("agent absent", lambda d: d.pop("agent")),
    ("agent not a desk agent", lambda d: d.__setitem__("agent", "kirocrew")),
    ("session key in last_msg",
     lambda d: d.__setitem__("last_msg", "see chat-1001-1700000001")),
]

SAY_MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("ok not bool", lambda d: d.__setitem__("ok", "yes")),
    ("delivered_to not a member", lambda d: d.__setitem__("delivered_to", "ceo")),
    ("delivered_to is a session key",
     lambda d: d.__setitem__("delivered_to", "chat-1001-1700000001")),
    ("missing delivered_to", lambda d: d.pop("delivered_to")),
]


def test_anchor_accepts_both_states() -> None:
    """§8.2 rev2: a message-level anchor, or null as the documented downgrade."""
    schema.assert_anchor(None)
    schema.assert_anchor(ANCHOR)
    schema.assert_anchor(dict(ANCHOR, preview=""))          # an empty first line is not a fault
    schema.assert_anchor(dict(ANCHOR, preview="x" * 60))    # exactly at the bound
    schema.assert_anchor(dict(ANCHOR, ts="1788796746.27"))  # ts is the transcript's own string

    anchored_detail = _mutate(THREAD_DETAIL, lambda d: d.__setitem__("anchor", dict(ANCHOR)))
    schema.assert_thread_detail(anchored_detail, expect_id="th-fund-2026-09-07-2")
    schema.assert_thread_detail(THREAD_DETAIL)  # anchor: null still legal

    anchored_listing = _mutate(
        THREADS, lambda d: [t.__setitem__("anchor", dict(ANCHOR)) for t in d["threads"]]
    )
    schema.assert_threads(anchored_listing)
    schema.assert_threads(THREADS)  # every thread anchored null

    # rev2 (06c486a): the key itself is required, so absence is now a fault.
    with pytest.raises(ContractError):
        schema.assert_threads(_mutate(THREADS, lambda d: d["threads"][0].pop("anchor")))


def test_entry_summary_lets_the_ui_skip_a_fetch_per_thread() -> None:
    """§11.2: entry_count and last_ts are required on the listing.

    They exist so the chip reads "N updates · latest hh:mm" from one request. rev6
    moved their source: entry_count counts the clone's visible rows, last_ts
    takes the latest row that HAS a ts. Rows without one therefore give a count
    with no stamp -- measured against ``backend.threads._build``, which returns
    ``entry_count=2, last_ts=None`` for two untimed rows -- so that pair is now
    legal and the chip simply renders no clock. The reverse still cannot happen:
    no rows means nothing to report.
    """
    schema.assert_threads(THREADS)                 # rows, with a last_ts
    schema.assert_threads(THREADS_LINE_MANAGER)    # entry_count 0, last_ts null
    schema.assert_threads(_mutate(
        THREADS, lambda d: d["threads"][0].update({"entry_count": 0, "last_ts": None})
    ))
    # rev6: rows that carry no ts of their own
    schema.assert_threads(_mutate(
        THREADS, lambda d: d["threads"][0].__setitem__("last_ts", None)
    ))
    # last_ts is the row's own string carried through, like anchor.ts
    schema.assert_threads(_mutate(
        THREADS, lambda d: d["threads"][0].__setitem__("last_ts", "1788796746.27")
    ))


@pytest.mark.parametrize("name,mutate", ANCHOR_MUTATIONS, ids=[n for n, _ in ANCHOR_MUTATIONS])
def test_anchor_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_anchor(_mutate(ANCHOR, mutate))


@pytest.mark.parametrize("name,mutate", ANCHOR_MUTATIONS, ids=[n for n, _ in ANCHOR_MUTATIONS])
def test_anchor_mutation_rejected_through_a_listed_thread(
    name: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    """The same faults must fail through /threads, not only the bare assertion."""
    bad = _mutate(ANCHOR, mutate)
    with pytest.raises(ContractError):
        schema.assert_threads(
            _mutate(THREADS, lambda d: d["threads"][0].__setitem__("anchor", bad))
        )


def test_thread_examples_pass() -> None:
    schema.assert_threads(THREADS)
    schema.assert_threads(THREADS, expect_member="fund")
    schema.assert_threads(THREADS_LINE_MANAGER, expect_member="lm-test-alpha")
    schema.assert_thread_detail(THREAD_DETAIL, expect_id="th-fund-2026-09-07-2")
    schema.assert_say_result(SAY_RESULT)


def test_shapes_without_a_fixture_sample_are_pinned_here() -> None:
    """Contract shapes no fixture happens to carry, pinned in the enum instead.

    The cycle1 ``blocked`` precedent: the enum is contract, a fixture is data,
    and data is not fabricated to fill an enum. ``failed`` is a thread whose
    session the gateway has since dropped; a null ``member`` is the documented
    downgrade when one agent serves several members and the title does not say
    which -- better unattributed than wrong.
    """
    schema.assert_threads(_mutate(THREADS, lambda d: d["threads"][0].__setitem__("state", "failed")))
    schema.assert_threads(_mutate(THREADS, lambda d: d["threads"][0].__setitem__("member", None)))
    schema.assert_thread_detail(_mutate(THREAD_DETAIL, lambda d: d.__setitem__("member", None)))
    assert "failed" in schema.THREAD_STATES
    assert schema.THREAD_KINDS == {"thread", "dispatch"}


def test_both_thread_kinds_are_accepted() -> None:
    """§11.1: the conductor's own clone and a session it opened for someone else.

    Classification is by agent, and the two are labelled differently in the UI,
    so both spellings have to reach it -- and only those two.
    """
    for kind in sorted(schema.THREAD_KINDS):
        schema.assert_threads(
            _mutate(THREADS, lambda d, k=kind: d["threads"][0].__setitem__("kind", k))
        )
        schema.assert_thread_detail(
            _mutate(THREAD_DETAIL, lambda d, k=kind: d.__setitem__("kind", k))
        )


@pytest.mark.parametrize("name,mutate", THREADS_MUTATIONS, ids=[n for n, _ in THREADS_MUTATIONS])
def test_threads_mutation_rejected(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    with pytest.raises(ContractError):
        schema.assert_threads(_mutate(THREADS, mutate))


@pytest.mark.parametrize("name,mutate", THREAD_DETAIL_MUTATIONS,
                         ids=[n for n, _ in THREAD_DETAIL_MUTATIONS])
def test_thread_detail_mutation_rejected(
    name: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    with pytest.raises(ContractError):
        schema.assert_thread_detail(_mutate(THREAD_DETAIL, mutate))


@pytest.mark.parametrize("name,mutate", SAY_MUTATIONS, ids=[n for n, _ in SAY_MUTATIONS])
def test_say_result_mutation_rejected(
    name: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    with pytest.raises(ContractError):
        schema.assert_say_result(_mutate(SAY_RESULT, mutate))


@pytest.mark.parametrize(
    "leak",
    ["chat-1001-1700000001", "td-lm-test-alpha-1788796788", "dashboard_chat-1-2"],
    ids=["slot-key", "reset-minted-key", "qualified-prefix"],
)
def test_every_session_key_shape_is_caught(leak: str) -> None:
    """§8.2 red line, one case per shape the regex covers."""
    with pytest.raises(ContractError):
        schema.assert_no_session_key({"entries": [{"text": f"see {leak}"}]})
    with pytest.raises(ContractError):
        schema.assert_no_session_key({"nested": {"deep": [[leak]]}})
    with pytest.raises(ContractError):
        schema.assert_no_session_key({leak: "as a key name"})
    schema.assert_no_session_key({"text": "dispatched test-alpha pod, output at teams/test-alpha/reports/"})


def test_thread_member_scope_is_enforced() -> None:
    with pytest.raises(ContractError):
        schema.assert_threads(THREADS, expect_member="desk")
    with pytest.raises(ContractError):
        schema.assert_thread_detail(THREAD_DETAIL, expect_id="th-fund-2026-09-07-9")


def test_org_profiles_map_is_checked_when_present() -> None:
    """§2 cycle9: profiles may be absent, but a present one is held to shape."""
    schema.assert_org(ORG)  # no profiles key at all
    good = _mutate(ORG, lambda d: d.__setitem__("profiles", {
        "fund": {"alias": "fund-manager", "avatar_letter": "F",
                 "reports_label": "brief", "agent": "tada-fund-manager"},
    }))
    schema.assert_org(good)
    for name, mutate in (
        ("agent not tada-*",
         lambda d: d["profiles"]["fund"].__setitem__("agent", "fund-manager")),
        ("missing key", lambda d: d["profiles"]["fund"].pop("alias")),
        ("unknown member id",
         lambda d: d["profiles"].__setitem__("nobody", d["profiles"]["fund"])),
        ("avatar_letter is a word",
         lambda d: d["profiles"]["fund"].__setitem__("avatar_letter", "fund")),
    ):
        with pytest.raises(ContractError):
            schema.assert_org(_mutate(good, mutate))


def test_allowlisted_extra_member_key_is_tolerated() -> None:
    """The named deviations pass; anything else undocumented still fails."""
    assert schema.ALLOWED_EXTRA_MEMBER_KEYS, "the allowlist must stay explicit"
    tolerated = _mutate(
        ORG,
        lambda d: [m.update({k: True for k in schema.ALLOWED_EXTRA_MEMBER_KEYS})
                   for m in d["members"]],
    )
    schema.assert_org(tolerated)
    with pytest.raises(ContractError):
        schema.assert_org(_mutate(tolerated, lambda d: d["members"][0].__setitem__("nonce", 1)))
