"""Schema assertions for the Trading Desk App backend contract.

One function per ARCHITECTURE.md §2 payload, plus the §4 run-event record. Every
failure message names the clause it enforces so a red points at the contract,
not at this file. Used by both ``test_fixtures.py`` (fixtures/*.json, the
shared mock data) and ``test_routes.py`` (live handler output) so the two can
never disagree about the shape.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOCK_RE = re.compile(r"^\d{2}:\d{2}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
#: §2, 2026-09-16 adjudication: the tree reaches the IC layer. `ic-<pod>-<role>`
#: is one of the execution roles inside a pod, parented to that pod's `lm-<pod>`.
#: The suffix is NOT enumerated here: the roles are configuration
#: (``config/roles.yaml``), so a fixed list would refuse a role someone added.
#: What catches a typo is the generator, which validates every role against that
#: file and names the offending entry.
MEMBER_ID_RE = re.compile(
    r"^(fund|macro|desk|risk|trader|scrum"
    r"|lm-[a-z0-9][a-z0-9-]*"
    r"|ic-[a-z0-9][a-z0-9-]*)$"
)

MEMBER_KEYS = {
    "id", "name", "title", "duty", "parent", "group", "pod",
    "tickers", "state", "state_msg", "slot_key", "recent_outputs",
}
MEMBER_STATES = {"idle", "working", "blocked"}
STEP_STATES = {"done", "work", "todo", "fail"}
#: §2, cycle1 adjudication: a pod that has not started the day reads not_started.
POD_STATES = {"done", "work", "fail", "not_started"}
EVENT_KINDS = {"dispatched", "stage", "delivered", "failed", "note"}

# --- §8 M2 threaded crew chat ----------------------------------------------

#: §8.2 thread lifecycle. ``failed`` has no fixture sample by adjudication
#: (the cycle1 ``blocked`` precedent: no fabricated data), so the enum is
#: pinned here and exercised by the self-check instead.
THREAD_STATES = {"running", "done", "failed"}

#: §11.1 rev6: what a listed session IS. The conductor's own clone of itself
#: (``thread``), or a session it opened for another member (``dispatch``).
#: Classification is by AGENT, so these two exhaust the vocabulary -- the UI's
#: label map tolerates a third spelling (``clone``) defensively, which is
#: exactly why the payload side is pinned to two.
THREAD_KINDS = {"thread", "dispatch"}

#: §8.1: ``th-{member}-{date}-{seq}``, stable for the same input. The member
#: segment itself carries hyphens (``lm-test-alpha``), so it is matched lazily
#: and then checked against the member vocabulary.
THREAD_ID_RE = re.compile(r"^th-(?P<member>.+?)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<seq>\d+)$")

#: §8.2 rev2: the anchor preview is the message's first 60 characters.
ANCHOR_PREVIEW_MAX = 60

#: A gateway session key, in any spelling. The shapes are the dashboard slot
#: key, the reset-minted key from §2 ``POST /member/{id}/reset``, and the
#: qualified ``dashboard_`` prefix.
#:
#: §11.2 rev6 REVERSED the M2 red line that kept every key out of a thread
#: payload: the panel reads ``/api/chat/slots/{slot_key}`` and the composer posts
#: ``{slot, agent}``, so the key is a required field. The narrower invariant that
#: replaces it -- and what ``assert_no_session_key`` now enforces -- is that a key
#: appears in ``slot_key`` and NOWHERE else, so a title, a folded line, a preview
#: or a ref carrying one is still a fault.
SESSION_KEY_RE = re.compile(r"chat-\d+-\d+|td-[a-z-]+-\d{10}|dashboard_")

#: §11.5.2: the scan accepts ``chat-N-TS`` bare and ``dashboard:``/``dashboard_``
#: prefixed, and NORMALISES to the bare key so one session is one thread. So the
#: emitted ``slot_key`` is the bare form -- a prefixed value there would both
#: build a wrong ``/api/chat/slots/{key}`` URL and mean the two spellings had
#: split into two threads. The reset-minted ``td-`` form is deliberately outside
#: this shape: that key is a member's own main conversation, never a thread.
SLOT_KEY_RE = re.compile(r"^chat-\d+-\d+$")

#: §2 cycle9 / §11.2: a desk agent name. The /org profiles map and a thread's
#: ``agent`` field are the same vocabulary -- ChatEmbed binds one and the thread
#: composer posts under the other -- so it is defined once here.
AGENT_RE = re.compile(r"^tada-[a-z0-9][a-z0-9-]*$")

#: §2 cycle9: /org's root-level profiles map, indexed by member id.
PROFILE_KEYS = ("alias", "avatar_letter", "reports_label", "agent")

#: §2 /org: duty is an outward-facing job description -- orchestration-internal
#: vocabulary must not leak into it.
FORBIDDEN_DUTY_TOKENS = (
    "sentinel", "plan-all", "plan_all", "orchestrate", "spawn_run",
    "subagent", "jsonl", "agent.md", "prompt",
)

#: Member keys §2 lists as OPTIONAL rather than part of the fixed shape. Kept
#: separate so the shape check stays a ratchet -- a NEW undocumented key fails.
#:
#: * ``slot_live`` -- §2, cycle2 adjudication: whether the bound session is
#:   currently running. The backend may omit it and the UI must not depend on
#:   it, so it is tolerated but never required.
ALLOWED_EXTRA_MEMBER_KEYS = frozenset({"slot_live"})


class ContractError(AssertionError):
    """A payload violates ARCHITECTURE.md."""


def _fail(clause: str, where: str, msg: str) -> None:
    raise ContractError(f"[ARCHITECTURE.md {clause}] {where}: {msg}")


def _dict(value: Any, clause: str, where: str) -> dict:
    if not isinstance(value, dict):
        _fail(clause, where, f"must be an object, got {type(value).__name__}")
    return value


def _list(value: Any, clause: str, where: str) -> list:
    if not isinstance(value, list):
        _fail(clause, where, f"must be an array, got {type(value).__name__}")
    return value


def _str(value: Any, clause: str, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(clause, where, f"must be a string, got {type(value).__name__}")
    if not allow_empty and not value.strip():
        _fail(clause, where, "must be a non-empty string")
    return value


def _opt_str(value: Any, clause: str, where: str) -> str | None:
    if value is None:
        return None
    return _str(value, clause, where)


def _bool(value: Any, clause: str, where: str) -> bool:
    if not isinstance(value, bool):
        _fail(clause, where, f"must be a boolean, got {type(value).__name__}")
    return value


def _int(value: Any, clause: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(clause, where, f"must be an integer, got {type(value).__name__}")
    return value


def _exact_keys(obj: dict, required: Iterable[str], clause: str, where: str) -> None:
    missing = sorted(set(required) - set(obj))
    if missing:
        _fail(clause, where, f"missing required key(s) {missing}")


def _date(value: Any, clause: str, where: str) -> str:
    text = _str(value, clause, where)
    if not DATE_RE.match(text):
        _fail(clause, where, f"must be YYYY-MM-DD, got {text!r}")
    return text


def _clock(value: Any, clause: str, where: str, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        _fail(clause, where, "must be HH:MM, got null")
    text = _str(value, clause, where)
    if not CLOCK_RE.match(text):
        _fail(clause, where, f"must be HH:MM, got {text!r}")
    return text


def _relpath(value: Any, clause: str, where: str) -> str:
    """A deskRoot-relative artifact path (§2 /artifacts tree)."""
    text = _str(value, clause, where)
    if text.startswith("/"):
        _fail(clause, where, f"must be relative to deskRoot, got absolute {text!r}")
    if text.startswith("~") or ".." in text.split("/"):
        _fail(clause, where, f"must not escape deskRoot, got {text!r}")
    if "\\" in text:
        _fail(clause, where, f"must use forward slashes, got {text!r}")
    return text


def _labelled_files(files: Any, clause: str, where: str) -> None:
    for i, entry in enumerate(_list(files, clause, where)):
        at = f"{where}[{i}]"
        obj = _dict(entry, clause, at)
        _exact_keys(obj, ("label", "path"), clause, at)
        _str(obj["label"], clause, f"{at}.label")
        _relpath(obj["path"], clause, f"{at}.path")


# ---------------------------------------------------------------------------
# GET /org
# ---------------------------------------------------------------------------

def assert_org(payload: Any) -> None:
    clause = "§2 GET /org"
    root = _dict(payload, clause, "/org")
    _exact_keys(root, ("members",), clause, "/org")
    members = _list(root["members"], clause, "/org.members")
    if not members:
        _fail(clause, "/org.members", "must not be empty -- the Desk page renders from it")
    ids: list[str] = []
    for i, entry in enumerate(members):
        at = f"/org.members[{i}]"
        m = _dict(entry, clause, at)
        _exact_keys(m, MEMBER_KEYS, clause, at)
        unknown = sorted(set(m) - MEMBER_KEYS - ALLOWED_EXTRA_MEMBER_KEYS)
        if unknown:
            _fail(clause, at, f"unexpected key(s) {unknown} -- §2 fixes the member shape")

        mid = _str(m["id"], clause, f"{at}.id")
        if not MEMBER_ID_RE.match(mid):
            _fail(clause, f"{at}.id",
                  "must be fund|macro|desk|risk|trader|scrum|lm-<pod>"
                  f"|ic-<pod>-<role>, got {mid!r}")
        ids.append(mid)

        _str(m["name"], clause, f"{at}.name")
        _str(m["title"], clause, f"{at}.title")
        duty = _str(m["duty"], clause, f"{at}.duty")
        low = duty.lower()
        for token in FORBIDDEN_DUTY_TOKENS:
            if token in low:
                _fail(clause, f"{at}.duty",
                      f"leaks orchestration-internal vocabulary {token!r} -- duty is the "
                      "outward-facing job description")

        _opt_str(m["parent"], clause, f"{at}.parent")
        _opt_str(m["group"], clause, f"{at}.group")
        _opt_str(m["pod"], clause, f"{at}.pod")
        _opt_str(m["slot_key"], clause, f"{at}.slot_key")

        state = _str(m["state"], clause, f"{at}.state")
        if state not in MEMBER_STATES:
            _fail(clause, f"{at}.state", f"must be one of {sorted(MEMBER_STATES)}, got {state!r}")
        msg = _str(m["state_msg"], clause, f"{at}.state_msg")
        if "\n" in msg:
            _fail(clause, f"{at}.state_msg", "must be one line")

        tickers = _list(m["tickers"], clause, f"{at}.tickers")
        for j, t in enumerate(tickers):
            sym = _str(t, clause, f"{at}.tickers[{j}]")
            if sym != sym.strip().upper():
                _fail(clause, f"{at}.tickers[{j}]", f"must be upper-case and stripped, got {sym!r}")
        is_lm = mid.startswith("lm-")
        is_ic = mid.startswith("ic-")
        if tickers and not is_lm:
            _fail(clause, f"{at}.tickers",
                  f"only a line-manager carries tickers, but {mid} has {tickers}")
        if is_lm:
            if not tickers:
                _fail(clause, f"{at}.tickers", "a line-manager must carry its pod's tickers")
            if m["pod"] is None or m["group"] is None:
                _fail(clause, at, "a line-manager must carry both pod and group")
        if is_ic:
            if m["pod"] is None or m["group"] is None:
                _fail(clause, at, "an IC must carry both pod and group")
            # An IC is spawned per ticker per round and has no standing session,
            # so a non-null key here would send the Chat page at a slot that can
            # never exist.
            if m["slot_key"] is not None:
                _fail(clause, f"{at}.slot_key",
                      f"an IC has no standing session, got {m['slot_key']!r}")
            if m["parent"] != f"lm-{m['pod']}":
                _fail(clause, f"{at}.parent",
                      f"an IC must hang off its own pod's line-manager "
                      f"(lm-{m['pod']}), got {m['parent']!r}")

        _labelled_files(m["recent_outputs"], clause, f"{at}.recent_outputs")

    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        _fail(clause, "/org.members", f"duplicate member id(s) {dupes}")

    roots = [m for m in members if m["parent"] is None]
    if len(roots) != 1:
        _fail(clause, "/org.members",
              f"expected exactly one parent-less member (fund), got {[m['id'] for m in roots]}")
    if roots[0]["id"] != "fund":
        _fail(clause, "/org.members", f"the parent-less member must be 'fund', got {roots[0]['id']!r}")

    known = set(ids)
    for m in members:
        if m["parent"] is not None and m["parent"] not in known:
            _fail(clause, f"/org.members[{m['id']}].parent",
                  f"{m['parent']!r} is not a member id")

    # No cycles: every member must reach the root by walking parents.
    parent_of = {m["id"]: m["parent"] for m in members}
    for mid in ids:
        seen = {mid}
        cur = parent_of[mid]
        while cur is not None:
            if cur in seen:
                _fail(clause, "/org.members", f"parent chain of {mid!r} cycles at {cur!r}")
            seen.add(cur)
            cur = parent_of[cur]

    # §2 cycle9: the hero card reads its display fields off a root-level
    # profiles map, which keeps the member object's own shape closed. Fixtures
    # may omit it (the UI tolerates absence), so it is checked when present.
    if "profiles" in root:
        profiles = _dict(root["profiles"], clause, "/org.profiles")
        known = set(ids)
        for mid, entry in profiles.items():
            at = f"/org.profiles[{mid}]"
            if mid not in known:
                _fail(clause, at, f"{mid!r} is not a member id in this payload")
            profile = _dict(entry, clause, at)
            for key in PROFILE_KEYS:
                if key not in profile:
                    _fail(clause, at, f"missing required key {key!r}")
                _str(profile[key], clause, f"{at}.{key}")
            agent = profile["agent"]
            if not AGENT_RE.match(agent):
                _fail(clause, f"{at}.agent",
                      f"must name a tada-* agent (ChatEmbed binds it), got {agent!r}")
            if len(profile["avatar_letter"]) > 2:
                _fail(clause, f"{at}.avatar_letter",
                      f"is an avatar glyph, got {profile['avatar_letter']!r}")


# ---------------------------------------------------------------------------
# GET /run
# ---------------------------------------------------------------------------

def assert_run(payload: Any, *, expect_date: str | None = None) -> None:
    clause = "§2 GET /run"
    root = _dict(payload, clause, "/run")
    _exact_keys(root, ("date", "live", "chain", "pods", "events"), clause, "/run")

    date = _date(root["date"], clause, "/run.date")
    if expect_date is not None and date != expect_date:
        _fail(clause, "/run.date", f"must echo the requested date {expect_date!r}, got {date!r}")
    _bool(root["live"], clause, "/run.live")

    for i, entry in enumerate(_list(root["chain"], clause, "/run.chain")):
        at = f"/run.chain[{i}]"
        link = _dict(entry, clause, at)
        _exact_keys(link, ("member", "steps"), clause, at)
        _str(link["member"], clause, f"{at}.member")
        for j, raw_step in enumerate(_list(link["steps"], clause, f"{at}.steps")):
            sat = f"{at}.steps[{j}]"
            step = _dict(raw_step, clause, sat)
            _exact_keys(step, ("label", "state", "at"), clause, sat)
            _str(step["label"], clause, f"{sat}.label")
            state = _str(step["state"], clause, f"{sat}.state")
            if state not in STEP_STATES:
                _fail(clause, f"{sat}.state", f"must be one of {sorted(STEP_STATES)}, got {state!r}")
            _clock(step["at"], clause, f"{sat}.at", optional=True)

    for i, entry in enumerate(_list(root["pods"], clause, "/run.pods")):
        at = f"/run.pods[{i}]"
        pod = _dict(entry, clause, at)
        _exact_keys(pod, ("pod", "state", "stages", "delivered_at", "fail_reason"), clause, at)
        _str(pod["pod"], clause, f"{at}.pod")
        state = _str(pod["state"], clause, f"{at}.state")
        if state not in POD_STATES:
            _fail(clause, f"{at}.state", f"must be one of {sorted(POD_STATES)}, got {state!r}")
        for j, raw_stage in enumerate(_list(pod["stages"], clause, f"{at}.stages")):
            gat = f"{at}.stages[{j}]"
            stage = _dict(raw_stage, clause, gat)
            _exact_keys(stage, ("name", "done", "total"), clause, gat)
            _str(stage["name"], clause, f"{gat}.name")
            done = _int(stage["done"], clause, f"{gat}.done")
            total = _int(stage["total"], clause, f"{gat}.total")
            if done < 0 or total < 0:
                _fail(clause, gat, f"done/total must be >= 0, got {done}/{total}")
            if done > total:
                _fail(clause, gat, f"done ({done}) must not exceed total ({total})")
        _clock(pod["delivered_at"], clause, f"{at}.delivered_at", optional=True)
        _opt_str(pod["fail_reason"], clause, f"{at}.fail_reason")

    for i, entry in enumerate(_list(root["events"], clause, "/run.events")):
        at = f"/run.events[{i}]"
        ev = _dict(entry, clause, at)
        _exact_keys(ev, ("at", "who", "msg", "hot"), clause, at)
        _clock(ev["at"], clause, f"{at}.at")
        _str(ev["who"], clause, f"{at}.who")
        _str(ev["msg"], clause, f"{at}.msg")
        _bool(ev["hot"], clause, f"{at}.hot")


# ---------------------------------------------------------------------------
# GET /config, POST /config/validate
# ---------------------------------------------------------------------------

def assert_config(payload: Any) -> None:
    clause = "§2 GET /config"
    root = _dict(payload, clause, "/config")
    _exact_keys(root, ("books", "sectors", "constraints"), clause, "/config")

    books = _dict(root["books"], clause, "/config.books")
    if "books" not in books:
        _fail(clause, "/config.books", "must be the parsed books.yaml, which carries a top-level `books:` key")
    _dict(books["books"], clause, "/config.books.books")

    sectors = _dict(root["sectors"], clause, "/config.sectors")
    if "sectors" not in sectors:
        _fail(clause, "/config.sectors",
              "must be the parsed sectors.yaml, which carries a top-level `sectors:` key")
    pods = _dict(sectors["sectors"], clause, "/config.sectors.sectors")
    if not pods:
        _fail(clause, "/config.sectors.sectors", "must define at least one pod")
    for name, cfg in pods.items():
        at = f"/config.sectors.sectors[{name}]"
        pod = _dict(cfg, clause, at)
        for key in ("line_manager", "analyst_copies", "tickers"):
            if key not in pod:
                _fail(clause, at, f"missing required pod field {key!r}")
        _list(pod["tickers"], clause, f"{at}.tickers")

    constraints = _dict(root["constraints"], clause, "/config.constraints")
    if not constraints:
        _fail(clause, "/config.constraints", "must carry books.yaml's account_constraints as-is")


def assert_validate_result(payload: Any, *, expect_ok: bool | None = None) -> None:
    clause = "§2 POST /config/validate"
    root = _dict(payload, clause, "/config/validate")
    _exact_keys(root, ("ok", "errors", "diff"), clause, "/config/validate")
    ok = _bool(root["ok"], clause, "/config/validate.ok")
    errors = _list(root["errors"], clause, "/config/validate.errors")
    for i, err in enumerate(errors):
        _str(err, clause, f"/config/validate.errors[{i}]")
    _str(root["diff"], clause, "/config/validate.diff", allow_empty=True)
    if expect_ok is not None and ok is not expect_ok:
        _fail(clause, "/config/validate.ok", f"expected {expect_ok}, got {ok} (errors={errors})")
    if not ok and not errors:
        _fail(clause, "/config/validate", "ok=false must come with at least one error message")


# ---------------------------------------------------------------------------
# GET /artifacts
# ---------------------------------------------------------------------------

def assert_artifacts(payload: Any) -> None:
    clause = "§2 GET /artifacts"
    root = _dict(payload, clause, "/artifacts")
    _exact_keys(root, ("dates", "tree"), clause, "/artifacts")

    dates = _list(root["dates"], clause, "/artifacts.dates")
    for i, d in enumerate(dates):
        _date(d, clause, f"/artifacts.dates[{i}]")
    if len(set(dates)) != len(dates):
        _fail(clause, "/artifacts.dates", f"must not repeat a date, got {dates}")
    if dates != sorted(dates, reverse=True):
        _fail(clause, "/artifacts.dates", f"must be newest-first as in §2's example, got {dates}")

    groups = _list(root["tree"], clause, "/artifacts.tree")
    for i, entry in enumerate(groups):
        at = f"/artifacts.tree[{i}]"
        group = _dict(entry, clause, at)
        _exact_keys(group, ("group", "files"), clause, at)
        _str(group["group"], clause, f"{at}.group")
        _labelled_files(group["files"], clause, f"{at}.files")


# ---------------------------------------------------------------------------
# §4 run-event record (events.jsonl)
# ---------------------------------------------------------------------------

def assert_event_record(payload: Any, *, where: str = "event") -> None:
    clause = "§4 event schema"
    ev = _dict(payload, clause, where)
    for key in ("at", "run_date", "who", "kind", "msg"):
        if key not in ev:
            _fail(clause, where, f"missing required key {key!r}")
    at = _str(ev["at"], clause, f"{where}.at")
    if not ISO_RE.match(at):
        _fail(clause, f"{where}.at", f"must be an ISO timestamp, got {at!r}")
    _date(ev["run_date"], clause, f"{where}.run_date")
    _str(ev["who"], clause, f"{where}.who")
    kind = _str(ev["kind"], clause, f"{where}.kind")
    if kind not in EVENT_KINDS:
        _fail(clause, f"{where}.kind", f"must be one of {sorted(EVENT_KINDS)}, got {kind!r}")
    _str(ev["msg"], clause, f"{where}.msg")
    if "stage" in ev and ev["stage"] is not None:
        stage = _dict(ev["stage"], clause, f"{where}.stage")
        _exact_keys(stage, ("name", "done", "total"), clause, f"{where}.stage")
        _str(stage["name"], clause, f"{where}.stage.name")
        _int(stage["done"], clause, f"{where}.stage.done")
        _int(stage["total"], clause, f"{where}.stage.total")
    unknown = sorted(set(ev) - {"at", "run_date", "who", "kind", "msg", "stage"})
    if unknown:
        _fail(clause, where, f"unexpected key(s) {unknown} -- §4 fixes the event shape")


# ---------------------------------------------------------------------------
# §8.2 M2 threaded crew chat
# ---------------------------------------------------------------------------

def _iso(value: Any, clause: str, where: str) -> str:
    text = _str(value, clause, where)
    if not ISO_RE.match(text):
        _fail(clause, where, f"must be an ISO timestamp, got {text!r}")
    return text


def _member_id(value: Any, clause: str, where: str, *, allow_ceo: bool = False) -> str:
    text = _str(value, clause, where)
    if allow_ceo and text == "ceo":
        return text
    if not MEMBER_ID_RE.match(text):
        extra = ' or "ceo"' if allow_ceo else ""
        _fail(clause, where, f"must be a member id{extra}, got {text!r}")
    return text


def _slot_key(value: Any, clause: str, where: str) -> str:
    """§11.2: the clone session the panel opens -- bare ``chat-N-TS`` (§11.5.2)."""
    text = _str(value, clause, where)
    if not SLOT_KEY_RE.match(text):
        _fail(clause, where,
              f"must be a bare chat-<n>-<ts> session key, got {text!r} -- §11.5.2 normalises "
              "the dashboard: / dashboard_ spellings away before this is emitted")
    return text


def _agent(value: Any, clause: str, where: str) -> str:
    """§11.2: the agent the composer posts under -- a desk ``tada-*`` name."""
    text = _str(value, clause, where)
    if not AGENT_RE.match(text):
        _fail(clause, where, f"must be a tada-* desk agent, got {text!r}")
    return text


def assert_no_session_key(
    payload: Any, *, where: str = "payload", allow_at: Iterable[str] = ()
) -> None:
    """A gateway session key appears only where the contract puts one.

    Walks keys and string values, so a key smuggled into a title, a folded
    transcript line or a ref is caught wherever it sits.

    ``allow_at`` names the exact paths a key belongs at -- §11.2 rev6 makes
    ``slot_key`` a required thread field, so the M2 "no key at all" red line
    became "a key appears in ``slot_key`` and nowhere else" (§11.5), which is the
    same invariant the backend asserts. The exemption is by PATH, not by value,
    so the same key repeated in a title still fails, and it is not by field NAME,
    so a ``slot_key`` appearing somewhere the shape does not sanction is not
    quietly waved through either.
    """
    clause = "§11.5 session key only in slot_key"
    exempt = frozenset(allow_at)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and SESSION_KEY_RE.search(key):
                    _fail(clause, f"{path}.{key}", f"key name exposes a session key: {key!r}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            if path in exempt:
                return
            found = SESSION_KEY_RE.search(node)
            if found:
                _fail(clause, path,
                      f"exposes a gateway session key ({found.group(0)!r}) -- §11.5 puts a key in "
                      "slot_key and nowhere else")

    walk(payload, where)


#: §11.2 rev6: the listing item and ``GET /thread/{id}`` are the SAME object --
#: the detail is re-derived and picked by id, so the two cannot drift. Holding
#: the shape once is what makes that true on this side too: a field added to one
#: payload and not the other would otherwise pass.
THREAD_KEYS = (
    "id", "kind", "title", "member", "state", "opened_at", "participants",
    "last_msg", "anchor", "entry_count", "last_ts", "slot_key", "agent", "refs",
)


def _thread_object(
    value: Any, clause: str, at: str, *, expect_member: str | None = None
) -> str:
    """One thread, as both ``/threads`` and ``/thread/{id}`` publish it (§11.2).

    Returns its id. The caller is responsible for the session-key scan, because
    the exempt ``slot_key`` path is only knowable from where this object sits.
    """
    thread = _dict(value, clause, at)
    _exact_keys(thread, THREAD_KEYS, clause, at)
    unknown = sorted(set(thread) - set(THREAD_KEYS))
    if unknown:
        _fail(clause, at, f"unexpected key(s) {unknown} -- §11.2 fixes the thread shape")

    thread_id = _thread_id(thread["id"], clause, f"{at}.id", expect_member=expect_member)
    _str(thread["title"], clause, f"{at}.title")

    # rev6 (§11.1): what this session IS. The UI labels the two differently, and
    # the distinction is derived from the agent, never from a folder or a title.
    kind = _str(thread["kind"], clause, f"{at}.kind")
    if kind not in THREAD_KINDS:
        _fail(clause, f"{at}.kind", f"must be one of {sorted(THREAD_KINDS)}, got {kind!r}")

    # Whose session it is. Null is documented: one agent can serve several
    # members, and unattributed beats wrongly attributed.
    if thread["member"] is not None:
        member = _member_id(thread["member"], clause, f"{at}.member")
        if member not in _list(thread["participants"], clause, f"{at}.participants"):
            _fail(clause, f"{at}.member",
                  f"{member!r} owns the session but is absent from participants "
                  f"{thread['participants']}")

    # §11.2: the panel reads /api/chat/slots/{slot_key} and the composer posts
    # /api/chat {slot, agent}, so a thread is unusable without both.
    _slot_key(thread["slot_key"], clause, f"{at}.slot_key")
    _agent(thread["agent"], clause, f"{at}.agent")

    state = _str(thread["state"], clause, f"{at}.state")
    if state not in THREAD_STATES:
        _fail(clause, f"{at}.state",
              f"must be one of {sorted(THREAD_STATES)}, got {state!r}")
    _iso(thread["opened_at"], clause, f"{at}.opened_at")

    # rev2: the listing carries the anchor and the count so the UI can render
    # "🧵 N 条动态 · 最新 hh:mm" without one /thread/{id} call per thread.
    assert_anchor(thread["anchor"], where=f"{at}.anchor")

    count = _int(thread["entry_count"], clause, f"{at}.entry_count")
    if count < 0:
        _fail(clause, f"{at}.entry_count", f"must be >= 0, got {count}")

    # last_ts is a row's own ts carried through, so its format is not ours to
    # pin. rev6 moved the source: entry_count counts the clone's visible rows
    # while last_ts takes the latest row that HAS a ts, so rows without one give
    # a count with no stamp -- measured reachable, and it degrades the chip's
    # clock rather than contradicting the count. The other direction still holds
    # by construction: no rows means nothing to report.
    last_ts = thread["last_ts"]
    if count == 0:
        if last_ts is not None:
            _fail(clause, f"{at}.last_ts",
                  f"entry_count is 0, so there is no latest row, got {last_ts!r}")
    elif last_ts is not None:
        _str(last_ts, clause, f"{at}.last_ts")

    participants = _list(thread["participants"], clause, f"{at}.participants")
    if not participants:
        _fail(clause, f"{at}.participants",
              "must name at least the member the thread hangs off")
    for j, who in enumerate(participants):
        _member_id(who, clause, f"{at}.participants[{j}]")

    last = _str(thread["last_msg"], clause, f"{at}.last_msg")
    if "\n" in last:
        _fail(clause, f"{at}.last_msg", "must be one line")

    refs = _dict(thread["refs"], clause, f"{at}.refs")
    _exact_keys(refs, ("run_date", "artifacts"), clause, f"{at}.refs")
    _date(refs["run_date"], clause, f"{at}.refs.run_date")
    for j, artifact in enumerate(_list(refs["artifacts"], clause, f"{at}.refs.artifacts")):
        _relpath(artifact, clause, f"{at}.refs.artifacts[{j}]")

    return thread_id


def assert_threads(payload: Any, *, expect_member: str | None = None) -> None:
    clause = "§11.2 GET /threads"
    root = _dict(payload, clause, "/threads")
    _exact_keys(root, ("threads",), clause, "/threads")
    threads = _list(root["threads"], clause, "/threads.threads")

    ids = [
        _thread_object(entry, clause, f"/threads.threads[{i}]", expect_member=expect_member)
        for i, entry in enumerate(threads)
    ]

    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        _fail(clause, "/threads.threads", f"duplicate thread id(s) {dupes} -- §8.1 ids are stable")

    keys = sorted({t.get("slot_key") for t in threads if isinstance(t, dict)} - {None})
    if len(keys) != len(ids):
        _fail(clause, "/threads.threads",
              f"{len(ids)} threads but {len(keys)} distinct slot_key(s) {keys} -- §11.5.2 "
              "normalises the two spellings so one session is one thread")

    assert_no_session_key(
        root,
        where="/threads",
        allow_at={f"/threads.threads[{i}].slot_key" for i in range(len(threads))},
    )


def assert_anchor(value: Any, *, where: str = "/thread.anchor") -> None:
    """§8.2 rev2: ``anchor`` is null, or the main-conversation message it hangs off.

    Two keys by adjudication, each with its own job: ``main_msg`` is the
    transcript's ``meta.mid`` and the authoritative identity, while ``ts`` is
    what the SPA matches a rendered row on, because a ChatMessage carries no
    mid. ``ts`` is the transcript's own string verbatim, so its format is not
    ours to pin -- only that it is present, distinct from the mid, and leaks no
    session key. Null is the documented downgrade when no dispatch-triggering
    message can be found.
    """
    clause = "§8.2 anchor"
    if value is None:
        return
    anchor = _dict(value, clause, where)
    _exact_keys(anchor, ("main_msg", "ts", "preview"), clause, where)
    unknown = sorted(set(anchor) - {"main_msg", "ts", "preview"})
    if unknown:
        _fail(clause, where, f"unexpected key(s) {unknown} -- §8.2 fixes the anchor shape")

    mid = _str(anchor["main_msg"], clause, f"{where}.main_msg")
    ts = _str(anchor["ts"], clause, f"{where}.ts")
    if mid == ts:
        _fail(clause, where,
              "main_msg and ts carry two different keys (authoritative identity vs the row the "
              f"UI matches), both got {mid!r}")

    preview = _str(anchor["preview"], clause, f"{where}.preview", allow_empty=True)
    if len(preview) > ANCHOR_PREVIEW_MAX:
        _fail(clause, f"{where}.preview",
              f"is the first {ANCHOR_PREVIEW_MAX} characters of the message, got {len(preview)}")
    assert_no_session_key(anchor, where=where)


def _thread_id(value: Any, clause: str, where: str, *, expect_member: str | None = None) -> str:
    """§8.1: ``th-{member}-{date}-{seq}``."""
    text = _str(value, clause, where)
    match = THREAD_ID_RE.match(text)
    if not match:
        _fail(clause, where, f"must be th-<member>-<YYYY-MM-DD>-<seq>, got {text!r}")
    member = match.group("member")
    if not MEMBER_ID_RE.match(member):
        _fail(clause, where, f"member segment {member!r} is not a member id (in {text!r})")
    if expect_member is not None and member != expect_member:
        _fail(clause, where,
              f"belongs to member {member!r} but the request asked for {expect_member!r}")
    return text


def assert_thread_detail(payload: Any, *, expect_id: str | None = None) -> None:
    """``GET /thread/{id}`` -- the thread's metadata and its ``slot_key`` (§11.2).

    rev6 removed ``entries``. The panel is no longer a folded summary timeline:
    it renders the clone session's own live transcript through
    ``/api/chat/slots/{slot_key}``, so this payload is the SAME object the
    listing publishes, re-derived and picked by id.
    """
    clause = "§11.2 GET /thread/{id}"
    thread_id = _thread_object(payload, clause, "/thread")
    if expect_id is not None and thread_id != expect_id:
        _fail(clause, "/thread.id", f"must echo the requested id {expect_id!r}, got {thread_id!r}")

    assert_no_session_key(payload, where="/thread", allow_at={"/thread.slot_key"})


def assert_say_result(payload: Any) -> None:
    """§8.2 POST /thread/{id}/say -> ``{ok, delivered_to}``, no session key."""
    clause = "§8.2 POST /thread/{id}/say"
    root = _dict(payload, clause, "/thread/say")
    _exact_keys(root, ("ok", "delivered_to"), clause, "/thread/say")
    _bool(root["ok"], clause, "/thread/say.ok")
    _member_id(root["delivered_to"], clause, "/thread/say.delivered_to")
    assert_no_session_key(root, where="/thread/say")
