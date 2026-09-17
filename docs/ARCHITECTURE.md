# Trading Desk — Architecture

This is the design and contract document for the Trading Desk app. The
[`README.md`](../README.md) is the user-facing introduction — what the app is and
how to install it. This document is the other half: the shapes on the wire, the
rules the code enforces, and the reasons behind the layout.

The single authoritative source for every payload shape is
[`tests/schema.py`](../tests/schema.py). That file is executable: each `assert_*`
function raises a `ContractError` whose message names the clause it enforces, so a
failing test points at a contract clause rather than at the test. This document is
the prose of that file. Where the two ever appear to disagree, `tests/schema.py`
wins and this document is wrong.

Section numbers are stable anchors. Assertion messages and code comments across the
repository cite them (`ARCHITECTURE.md §2`, `§8.1`, `§11.5` and so on) so a reader
who lands on one from a test failure or a comment can find the clause. The numbers
do not renumber; a retired topic keeps its number and is marked reserved rather than
reused.

---

## §0 Tracks and the shared fixtures dependency

The repository is built as several parallel tracks, each with its own deliverable:

| Track | Deliverable | What it owns |
|---|---|---|
| Infrastructure | `fixtures/`, `tests/` | the shared mock payloads and the contract tests |
| Backend | `backend/` | the in-process HTTP routes (§2) |
| Scripts | `scripts/`, `crews/gen_members.py` | the derive and config tooling (§6) |
| UI | `ui/` | the single-page app (§9, §10) |

`fixtures/` is the infrastructure track's first deliverable and the one every other
track depends on. It is a **shared, read-only dependency**: the UI is built against
fixture payloads, and the backend's live output is checked against the same fixtures
by the same schema functions. Because both sides validate against
[`tests/schema.py`](../tests/schema.py), the fixture schema *is* the §2 schema — a
fixture that drifts from §2 breaks the UI the moment the real route answers, and a
route that drifts from §2 fails the fixture test. That shared check is what keeps
the tracks from disagreeing about a shape while they are built in parallel.

Cross-track delivery is staged. A test that reads another track's not-yet-delivered
file *skips* rather than fails, so a partially delivered repository still runs a
green subset. The final acceptance run sets `TD_REQUIRE_ALL=1`, which turns those
skips into failures — a green suite then cannot be green by omission. Fixtures are
cut for a single fixed smoke date (§3, §7) so every track lands on the same data.

The desk data root (`$DESK_ROOT`, §1) is a separate read-only dependency: it holds
the config, positions and research output the app reads but never authors, and it is
not part of this repository.

---

## §1 Install target and deskRoot resolution

The app installs into a KiroCrew gateway. Two roots matter, and they are different
things:

- **App root** — this repository's own tree, the parent of `backend/`. It is found
  the same way in the source checkout and in the installed copy under
  `<gateway home>/apps/trading-desk`, so sibling-track files (`crews/members.json`,
  `scripts/desk_events.py`) resolve either way. Code reaches it through
  `paths.app_root()`.
- **Desk root** — the private data tree the app reads. It is *data, not code*: it
  holds positions, research reports and account configuration, so nothing in this
  repository may hardcode one copy of it.

The gateway home is resolved from `KIROCREW_HOME`, falling back to `~/.kirocrew`
then `~/.kiro/crew`. The app's own installed state lives under it:
`<gateway home>/apps/trading-desk/data/config.json` and
`<gateway home>/workspace/trading-desk/state.json`.

### deskRoot resolution order

The desk root is resolved once per request, first hit wins:

1. `deskRoot` in the app's own `data/config.json` (written by the self-heal cron, so
   an installed copy pins the tree it was set up against).
2. the `DESK_ROOT` environment variable.
3. `~/trading-desk`.

The result is expanded and `resolve()`d; resolution does not require the path to
exist. `data/config.json` also carries `appRoot` and `statePath`, but the UI reads
its desk-relative data from the backend routes, not from those fields directly — the
config file's job is to pin the install target, not to be a second data source. A
missing or corrupt `data/config.json` reads as an empty config, which sends
resolution to step 2.

### Path containment

Every filesystem read is anchored at the resolved desk root. A caller-supplied path
is resolved against the root and refused if it lands outside — both sides are
`resolve()`d before comparison, so a symlink inside the tree that points out of it is
caught too. A path that escapes becomes a `403` (see §2, `GET /file`).

### Handler and manifest shape

Route handlers each take exactly `(request, ctx)`. The manifest wires them through
`backend.hooks.routes` only; it must **not** set `backend.routes` (a base-path
string there switches the gateway to the standalone-process proxy, whose stubs
shadow these handlers). See §5. An unauthenticated caller — one for whom the gateway
did not set `request["user"]` — gets a `401` on every route, with the standard error
body (§2). Duplicate route registration is a fault: the registry keeps the first
match, so a second handler on the same path ships dead.

---

## §2 The API contract

All routes are registered relative to `/api/apps/trading-desk`. Each is declared as
an `AppRoute(method, path, handler)` and dispatched in-process by the gateway.

| Method | Path | Purpose |
|---|---|---|
| GET | `/org` | desk roster, duty text, live state, chat slot |
| GET | `/run` | one run as a dispatch chain plus per-pod lanes |
| GET | `/deskconfig` | books + sectors + account constraints |
| POST | `/config/validate` | check a candidate config; nothing is written |
| POST | `/config/apply` | validated, atomic write-back |
| GET | `/artifacts` | produced-file tree, grouped |
| GET | `/file` | text of one file inside the desk root |
| POST | `/member/{id}/reset` | bind a member to a fresh session |
| GET | `/threads` | the threads a member's conversation mentions (§11) |
| GET | `/thread/{id}` | one thread's metadata and its `slot_key` |
| POST | `/thread` | open a thread on one message (§12) |
| POST | `/thread/{id}/say` | say one line into a thread's session (§8.2) |
| GET | `/health` | desk-root resolution and which data sources are present |

The config **read** is `/deskconfig`, not `/config`. The gateway owns
`/api/apps/{name}/config` (it serves `data/config.json`) and registers it before the
route-registry catch-all this app dispatches from, so a `/config` route here would
never be reached. The config **writes** sit on distinct paths (`/config/validate`,
`/config/apply`) and are not shadowed.

### Error body

A failing request returns a JSON object `{"error": "<message>"}` with an HTTP status:

| Status | Meaning |
|---|---|
| 400 | malformed input — a bad `?date=`, a missing required field, an undecodable JSON body |
| 401 | the caller is unauthenticated |
| 403 | a requested path resolves outside the desk root |
| 404 | no such member, thread, or file |
| 413 | a requested file is too large to return |

The config write paths are the exception: `POST /config/validate` and
`POST /config/apply` report failure as `{"ok": false, "errors": [...]}` (validate
also carries `"warnings": []` and `"diff": ""` on its `400` path) rather than the
`{"error": ...}` envelope, because the caller needs the per-clause error list.

### Date validation

Anywhere a date is accepted (`?date=`) or emitted, it is a literal `YYYY-MM-DD`
(`^\d{4}-\d{2}-\d{2}$`). A `?date=` that does not match is rejected as `400` before
it can reach the filesystem, because the value becomes a path segment (`runs/{date}`).
Clock times are `HH:MM` (`^\d{2}:\d{2}$`). Event and session timestamps are ISO
(`^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?`).

---

### GET /org

Returns the desk roster the Desk page renders. The response is
`{"members": [...], "profiles": {...}, "deskRoot": "...", "source": "..."}`. The
schema pins `members` and the optional `profiles` map; `deskRoot` and `source` are
informational.

`members` must be a non-empty array — the Desk page renders from it. Each member is
an object with exactly this shape:

| Field | Type | Rule |
|---|---|---|
| `id` | string | matches the member-id grammar (below) |
| `name` | string | non-empty |
| `title` | string | non-empty |
| `duty` | string | non-empty; must not leak orchestration vocabulary (below) |
| `parent` | string \| null | another member's `id`, or null for the single root |
| `group` | string \| null | pod display label |
| `pod` | string \| null | pod id |
| `tickers` | string[] | upper-cased and stripped; line-manager only (below) |
| `state` | string | one of `idle`, `working`, `blocked` |
| `state_msg` | string | one line (no newline) |
| `slot_key` | string \| null | the bound session key, or null when none exists |
| `recent_outputs` | object[] | labelled files (below) |

One optional key is tolerated but never required: `slot_live` (boolean) — whether the
bound session is currently running. The backend may omit it and the UI must not
depend on it. Any *other* unexpected key is a fault: §2 fixes the member shape, so the
check is a ratchet against undocumented fields.

**Member-id grammar.** `id` matches:

```
fund | macro | desk | risk | trader | scrum | lm-<pod> | ic-<pod>-<role>
```

The six bare names are the standing roles. `lm-<pod>` is a pod's line manager.
`ic-<pod>-<role>` is one execution role inside a pod. The `<role>` suffix is *not*
enumerated in the contract — roles are configuration (`roles.yaml`), so a fixed list
would reject a role someone added; a typo is caught by the roster generator, which
validates every role against that file, not here.

**duty.** `duty` is the outward-facing job description a reader sees. Orchestration
internals never belong in it. The following tokens are rejected outright:

```
sentinel   plan-all   plan_all   orchestrate   spawn_run
subagent   jsonl      agent.md   prompt
```

**tickers and the pod roles.**

- Only a line manager (`lm-`) carries tickers; a non-line-manager with a non-empty
  `tickers` is a fault.
- A line manager must carry its pod's tickers *and* both `pod` and `group`.
- An IC (`ic-`) must carry both `pod` and `group`. Its `slot_key` must be null — an
  IC is spawned per ticker per round and holds no standing session, so a non-null key
  would point the Chat page at a slot that can never exist. Its `parent` must be its
  own pod's line manager, `lm-<pod>`.

**recent_outputs.** An array of `{"label": string, "path": string}`. Each `path` is
relative to the desk root: it must not start with `/`, must not contain `..` or start
with `~`, and must use forward slashes.

**Tree invariants.** Member ids are unique. Exactly one member is parent-less, and it
must be `fund`. Every non-null `parent` names a real member id. The parent chain of
every member reaches the root without a cycle.

**profiles.** An optional root-level map keyed by member id, holding the display
fields the Desk page's hero card needs without widening the closed member shape.
Fixtures may omit it; it is validated when present. Each entry has exactly:

| Field | Type | Rule |
|---|---|---|
| `alias` | string | the handle on the hero card |
| `avatar_letter` | string | an avatar glyph, at most two characters |
| `reports_label` | string | the "direct reports" value |
| `agent` | string | matches `^tada-[a-z0-9][a-z0-9-]*$` (ChatEmbed binds it) |

A profile key that is not a member id in the same payload is a fault.

```json
{
  "members": [
    {
      "id": "fund",
      "name": "fund-manager",
      "title": "Fund Manager",
      "duty": "Runs the desk's day-to-day operations, breaking the day's intent into research and allocation actions, and owns the final conclusion.",
      "parent": null,
      "group": null,
      "pod": null,
      "tickers": [],
      "state": "idle",
      "state_msg": "on station",
      "slot_key": "dashboard_chat-9305-1700004005",
      "recent_outputs": [
        { "label": "Yesterday's brief 2026-09-07", "path": "memory/briefs/2026-09-07.md" }
      ]
    },
    {
      "id": "lm-example-megacap",
      "name": "line-manager · example-megacap",
      "title": "Line Manager",
      "duty": "Owns the example-megacap pod (AAPL MSFT). Delivers this pod's conclusion on every ticker it covers.",
      "parent": "desk",
      "group": "Book A · example-megacap",
      "pod": "example-megacap",
      "tickers": ["AAPL", "MSFT"],
      "state": "working",
      "state_msg": "working on today's tasks",
      "slot_key": null,
      "recent_outputs": []
    },
    {
      "id": "ic-example-megacap-technicals",
      "name": "technicals · example-megacap",
      "title": "Technicals Analyst",
      "duty": "Runs technical analysis on this pod's tickers.",
      "parent": "lm-example-megacap",
      "group": "Book A · example-megacap",
      "pod": "example-megacap",
      "tickers": [],
      "state": "idle",
      "state_msg": "2/2 delivered",
      "slot_key": null,
      "recent_outputs": []
    }
  ],
  "profiles": {
    "ic-example-megacap-technicals": {
      "alias": "technicals@example-megacap",
      "avatar_letter": "T",
      "reports_label": "—",
      "agent": "tada-technicals"
    }
  }
}
```

---

### GET /run

Returns one day's run as a dispatch chain plus per-pod lanes. Accepts `?date=`
(defaults to today). The response has exactly:

| Field | Type | Rule |
|---|---|---|
| `date` | string | `YYYY-MM-DD`; echoes the requested date |
| `live` | boolean | whether this is today's in-progress run |
| `chain` | object[] | the dispatch chain (below) |
| `pods` | object[] | per-pod lanes (below) |
| `events` | object[] | the run event feed (below) |

**chain** — one link per member: `{"member": string, "steps": [...]}`. Each step is
`{"label": string, "state": string, "at": string|null}`. `state` is one of `done`,
`work`, `todo`, `fail`. `at` is `HH:MM` or null.

**pods** — one lane per pod:
`{"pod": string, "state": string, "stages": [...], "delivered_at": string|null, "fail_reason": string|null}`.
`state` is one of `done`, `work`, `fail`, `not_started` (a pod that has not started
the day reads `not_started`). Each stage is `{"name": string, "done": int, "total": int}`
with `0 <= done <= total`. `delivered_at` is `HH:MM` or null; `fail_reason` is a
string or null.

**events** — the feed: `{"at": string, "who": string, "msg": string, "hot": boolean}`,
`at` a required `HH:MM`.

```json
{
  "date": "2026-09-07",
  "live": false,
  "chain": [
    { "member": "fund", "steps": [ { "label": "opening brief", "state": "done", "at": "09:05" } ] }
  ],
  "pods": [
    {
      "pod": "example-megacap",
      "state": "done",
      "stages": [
        { "name": "Analysis", "done": 8, "total": 8 },
        { "name": "Debate", "done": 4, "total": 4 },
        { "name": "Proposal", "done": 2, "total": 2 },
        { "name": "Risk", "done": 6, "total": 6 }
      ],
      "delivered_at": "15:40",
      "fail_reason": null
    }
  ],
  "events": [
    { "at": "09:05", "who": "fund", "msg": "set out today's research", "hot": false }
  ]
}
```

Pod stage denominators are computed, not hand-set: the stage vocabulary, the filename
globs that mark a stage done, and the denominator formula
(`n_tickers × 4 analyst roles × analyst_copies` for the analysis stage, or a
per-stage per-ticker count) come from the derive script's own stage table, loaded by
file path so the Run page reads the same numbers the derive produces. A local mirror
of that table stands in when the script module is absent, so an idle pod still gets
real `0/total` denominators instead of a blank lane.

---

### GET /deskconfig

Returns the desk configuration the Config page reads. (The schema function is named
for the config payload; the route is `/deskconfig`, since `/config` is gateway-owned.)
The response has exactly `books`, `sectors`, `constraints`:

| Field | Type | Rule |
|---|---|---|
| `books` | object | the parsed `books.yaml`; carries a top-level `books:` key that is itself an object |
| `sectors` | object | the parsed `sectors.yaml`; carries a top-level `sectors:` key |
| `constraints` | object | `books.yaml`'s `account_constraints`, as-is; non-empty |

`sectors.sectors` is the pod map and must define at least one pod. Each pod carries
`line_manager`, `analyst_copies` and `tickers` (a list).

```json
{
  "books": { "books": { "A": { "pod_weights": { "example-megacap": 0.6 } } } },
  "sectors": {
    "sectors": {
      "example-megacap": { "line_manager": "lm-example-megacap", "analyst_copies": 2, "tickers": ["AAPL", "MSFT"] }
    }
  },
  "constraints": { "max_gross": 1.5 }
}
```

YAML values that JSON cannot encode (an unquoted date parses as a `date` object) are
normalised to strings before the payload is returned, so one such value in the config
cannot 500 the route.

---

### POST /config/validate

Checks a candidate config without writing anything. Response has exactly:

| Field | Type | Rule |
|---|---|---|
| `ok` | boolean | whether the candidate validates |
| `errors` | string[] | validation errors; must be non-empty when `ok` is false |
| `diff` | string | a textual diff of what applying would change; may be empty |

A malformed body returns `400` with `{"ok": false, "errors": [...], "warnings": [], "diff": ""}`.

---

### POST /config/apply

Validates a candidate and, only if it validates, writes it back. The write is
**atomic** (a temporary file is `fsync`ed and renamed over the target in one step, so
a reader sees either the whole old file or the whole new one) and preserves the
target's existing permission bits, and it takes a **backup** first. A candidate that
fails validation is **never written**: the route returns `{"ok": false, "errors": [...]}`
with `400`. On success the handler returns the applier's payload and status. The
schema does not pin the success shape beyond the refuse-on-failure contract, so this
document does not assert more than the code guarantees.

---

### GET /artifacts

Returns the produced-file tree. Accepts `?date=`. Response has exactly `dates` and
`tree`:

| Field | Type | Rule |
|---|---|---|
| `dates` | string[] | `YYYY-MM-DD` values, no repeats, **newest first** |
| `tree` | object[] | groups of labelled files |

Each group is `{"group": string, "files": [...]}`; each file is
`{"label": string, "path": string}` with `path` relative to the desk root (same
containment rules as `recent_outputs`).

```json
{
  "dates": ["2026-09-07", "2026-09-06"],
  "tree": [
    {
      "group": "example-megacap",
      "files": [
        { "label": "pod report", "path": "teams/example-megacap/reports/2026-09-07.md" }
      ]
    }
  ]
}
```

---

### GET /file

Returns the text of one file inside the desk root. Accepts `?path=` (relative to the
root, or absolute within it). The response is `text/plain; charset=utf-8` with an
`X-Desk-Path` header carrying the desk-relative path — not a JSON payload. A path
outside the root is `403`; a missing file is `404`; a file too large to return is
`413`.

---

### POST /member/{id}/reset

Binds a member to a brand-new session, leaving the previous one as history. Returns a
payload carrying the newly minted `slot_key`. An unknown member is `404`; a member
that cannot be reset is `400`.

The minted key uses the `td-<name>-<10-digit>` form. That shape is deliberately
outside the thread `slot_key` shape (§8.2, §11.2): a reset key is a member's own main
conversation, never a thread session.

---

### GET /threads, GET /thread/{id}, POST /thread, POST /thread/{id}/say

These are the threaded-chat surface and are specified in §8 and §11 (shape) and §12
(creation). In brief:

- `GET /threads?member=` returns `{"threads": [...]}` — the threads that member's
  conversation mentions or has filed. `member` is required (`400` if absent); an
  unknown member is `404`. Omitting `?date=` returns every thread.
- `GET /thread/{id}` returns one thread object, the same shape a listing entry has,
  re-derived and picked by id; `404` if no such thread.
- `POST /thread` opens a thread on one message (§12).
- `POST /thread/{id}/say` delivers one line into the thread's session; response
  `{"ok": boolean, "delivered_to": <member id>}` (§8.2).

The full thread object and its invariants are in §11.2.

---

### GET /health

Reports what the backend resolved and which optional inputs are present. Not
schema-pinned; the handler returns:

```json
{
  "ok": true,
  "deskRoot": "$DESK_ROOT",
  "deskRootExists": true,
  "appRoot": "$KIROCREW_HOME/apps/trading-desk",
  "sources": {
    "sectors.yaml": true,
    "books.yaml": true,
    "engine/validate_config.py": false,
    "crews/members.json": true,
    "scripts/desk_events.py": true,
    "runs/2026-09-07/events.jsonl": false
  },
  "pods": ["example-megacap"],
  "dates": ["2026-09-07"]
}
```

`sources` reports the presence of each optional input by name, `pods` is the sorted
pod list, and `dates` is the ten most recent dates with any artifact.

---

## §3 The fixtures directory

`fixtures/` holds the shared mock payloads (§0). Every JSON file in it is a sample of
a §2 route response, and it is validated by the same `assert_*` functions that check
the live handlers — so a fixture cannot drift from the contract without turning a
test red.

The fixtures are **derived, never hand-written**. They are produced by
`fixtures/gen_fixtures.py`, cut from a real smoke run for the fixed fixture date
(§7). Hand-editing one would let it drift from what the route actually emits, which
is the exact drift §0 exists to prevent. The files the UI and tests expect include:

| Fixture | Validated by |
|---|---|
| `org.json` | `assert_org` |
| `run-<date>.json` (or `run.json`) | `assert_run` |
| `config.json` | `assert_config` |
| `artifacts.json` | `assert_artifacts` |
| thread listing / detail fixtures | `assert_threads` / `assert_thread_detail` |

Each fixture test skips until its file lands, and `TD_REQUIRE_ALL=1` turns those
skips into failures for the acceptance run (§0).

---

## §4 The roster and the run-event record

### The roster — crews/members.json

`crews/members.json` is the roster the backend reads directly for `/org`. It is
**generated** from `sectors.yaml` and `roles.yaml` (with `books.yaml` for labels) and
must not be hand-edited. The field-by-field contract lives in
[`crews/README.md`](../crews/README.md) — this document does not repeat it. What this
section states is the set of invariants the tests enforce, which are the cross-track
interface between the generator and the backend:

- **Six standing roles.** `fund`, `macro`, `desk`, `risk`, `trader`, `scrum` are the
  fixed chain of command.
- **One line manager per pod.** Each `sectors.yaml` entry produces exactly one
  `lm-<pod>`.
- **The same roles under every pod.** Every `roles.yaml` role appears as
  `ic-<pod>-<role>` under each pod's line manager — the roster is the cross product of
  the two config files. No role count is pinned anywhere in the test suite.
- **A single parent-less root.** Exactly one member has no parent, and it is `fund`.
- **duty is job description, never orchestration.** The generator rejects the
  orchestration tokens listed in §2 from any `duty` string.

The generated member object omits `state`, `state_msg`, `slot_key` and
`recent_outputs` — those are runtime, computed by the backend from session state and
artifacts on disk (§2). The display-only fields (`alias`, `avatar_letter`,
`reports_label`, `agent`) are surfaced by `/org` as the `profiles` map, keyed by id,
so the closed member shape stays closed.

### The run-event record — events.jsonl

`runs/<date>/events.jsonl` is the structured run source the Run page derives from
when it is present. It is append-only JSONL written by a live run; a torn final line
is expected and is skipped rather than treated as fatal. Each record has the required
keys `at`, `run_date`, `who`, `kind`, `msg`, with an optional `stage`:

| Field | Type | Rule |
|---|---|---|
| `at` | string | an ISO timestamp |
| `run_date` | string | `YYYY-MM-DD` |
| `who` | string | the member or pod the event is addressed to |
| `kind` | string | one of `dispatched`, `stage`, `delivered`, `failed`, `note` |
| `msg` | string | the event text |
| `stage` | object \| absent | when present: `{"name": string, "done": int, "total": int}` |

Any key beyond those six is a fault — §4 fixes the event shape. A `failed` event
drives a member's `blocked` state on the Desk page; a `delivered` event reads as
`idle` with a message saying so, rather than introducing a fourth state.

---

## §5 The app.json manifest

[`app.json`](../app.json) declares the app to the gateway.

**permissions.** `permissions` is an object. Its `api` list grants the host
endpoints the app calls:

```
/api/chat        /api/chat/*
/api/approvals   /api/approvals/*
/api/file-read
/api/apps/trading-desk/*
```

`cron` is `true`; `network` and `storage` are `false`. The app reads the desk root
through its own backend routes, so it needs no host storage grant, and it makes no
outbound network calls.

**backend hook.** `backend.hooks.routes` is `"backend.routes:register_routes"`, and
`backend.routes` (the base-path string) must be **absent**. Setting the string form
would switch the app to the standalone-process proxy, whose stubs shadow the
in-process `register_routes` (§1).

**ui entry.** `ui.entry` is `index.mjs`. `ui.pages` declares one page at route
`/trading-desk` with a label and icon.

**crons.** One cron, `trading-desk-heal`, runs every 900 seconds, `silent`, without a
persistent session. It is a self-heal job: it resolves the gateway home and desk
root, ensures the state directory and `state.json` exist, writes `data/config.json`
if missing (pinning `deskRoot`, `appRoot`, `statePath`), and ensures `runs/` exists on
the desk root. Every step is a no-op when already done, so the job produces no output
unless a command fails. It exists so the app self-heals without depending on the
install hook.

**setup hooks.** `setup.onInstall` is `scripts/install.sh` and `setup.onUninstall` is
`scripts/uninstall.sh`. The install work the hook does is the same work the heal cron
does, so an install is functional within one cron interval even if the hook did not
run.

---

## §6 The scripts track and the tests that guard it

The scripts track owns the tooling that produces and maintains desk data. The backend
reads its output but does not run it.

**desk_events.py — derive.** Turns a run's artifacts and any event log into the
`events.jsonl` record (§4) and owns the canonical stage table the Run page borrows
(§2). Two invariants the tests pin:

- **Idempotent.** A second derive of an unchanged run produces the same result — it
  does not grow `events.jsonl`, and a re-append of the same events does not duplicate
  them.
- **No persistence without `--write`.** The derive computes in memory and only writes
  when explicitly asked; a plain derive leaves the desk root untouched.

**config_io.py — load / validate / apply.** The config lifecycle behind the
`/config/*` routes:

- **Atomic write** — the applied config replaces the target in one step (§2,
  `/config/apply`).
- **Backup** — the previous config is backed up before a write.
- **Refuse on validation failure** — `validate` never persists, and `apply` writes
  nothing when validation fails. The tests assert that `validate` leaves the desk
  root byte-for-byte unchanged.

**members.py — aggregate_state.** Folds per-member runtime state from session state
and the artifacts on disk — the same aggregation `/org` performs, so the roster's
generated identity and the computed runtime state stay separable (§4).

**The tests that guard the tracks.** The `§6` clause also covers the suite's own
health checks: every required route is registered (§2), no route sits on a
gateway-owned path, there are no duplicate registrations, and `node --check ui/index.mjs`
parses the UI entry. The suite runs single-process (`pytest tests/ -x -q`, never
`-n auto`) and each test builds its own temporary desk root so none reads a real one.

---

## §7 Reserved — the smoke-test acceptance run

This section is reserved for the smoke-test acceptance run. The suite fixes one smoke
date, `2026-09-07`, and the shared fixtures (§3) are cut for exactly that date, so a
single known-good run anchors both the fixtures and the end-to-end replay. Beyond the
smoke-date anchor, no acceptance-run detail is pinned by the code in scope, so nothing
further is asserted here.

---

## §8 Threads

A thread is a side conversation hung off one message in a member's main
conversation. The threaded-chat surface is `GET /threads`, `GET /thread/{id}`,
`POST /thread` (§12) and `POST /thread/{id}/say`. The full thread object shape is in
§11.2; this section pins identity, the anchor, and the lifecycle.

### §8.1 Thread identity and the anchor

**Identity.** A thread id is `th-{member}-{date}-{seq}`:

```
th-<member id>-<YYYY-MM-DD>-<seq>
```

The member segment is itself a member id and may carry hyphens (`lm-example-megacap`), so it is
matched lazily and then checked against the member-id grammar (§2). `date` is the
anchor message's local date (a folder-only thread uses the session's creation date),
and `seq` is the session's place in **creation order within that date** — not its
place in mention order — so the same thread gets the same id whichever source found it,
and one reset does not renumber a member's whole list. Scoping `seq` per date keeps it
stable under rotation: dropping an old day removes that day's threads instead of
renumbering every later one. Ids are stable for the same input and unique within a
listing.

**The anchor.** A thread's `anchor` is either `null` or the main-conversation message
it hangs under, as three fields:

| Field | Type | Rule |
|---|---|---|
| `main_msg` | string | the message's `meta.mid` — the authoritative identity |
| `ts` | string | the row's own timestamp, passed through verbatim; distinct from `main_msg` |
| `preview` | string | the first 60 characters of the message; may be empty |

`main_msg` and `ts` do two different jobs and must differ: `main_msg` is the mid the
gateway mints, while `ts` is what the single-page app matches a rendered row on
(a rendered message carries no mid). `ts` is passed through unchanged for that reason —
reformatting it would silently stop the anchor matching the rendered row. `preview` is
scrubbed of any session key and then truncated to 60 characters (`ANCHOR_PREVIEW_MAX`);
a key never appears here (§11.5). Any key beyond the three is a fault. `null` is the
documented downgrade when no dispatch-triggering message can be found.

### §8.2 Lifecycle and the say payload

**Lifecycle.** A thread's `state` is one of:

| State | Meaning |
|---|---|
| `running` | a turn is in flight right now |
| `done` | the gateway holds the session and it is idle (the last turn finished) |
| `failed` | the gateway holds no open slot for it — the session existed but cannot be opened now |

`failed` has no fixture sample: there is no fabricated data for it, so the enum is
pinned in the schema and exercised by the self-check rather than by a fixture. Note
this is deliberately *not* `/org`'s rule for a member's main session, where a key is
honoured before its session exists so the chat embed can create it on the first
message. A thread's session was created when the thread was opened, so a missing slot
there is a session that went away, not one still to come.

**The say payload.** `POST /thread/{id}/say` delivers one typed line to the thread's
own session and returns:

| Field | Type | Rule |
|---|---|---|
| `ok` | boolean | whether the line was accepted |
| `delivered_to` | string | the member id the line went to |

The enforced contract is exactly `{ok, delivered_to}`, and no session key appears in
this body (§11.5). Talking in a thread is talking to the session in it, so the target
is the thread's own slot — not a search for whichever member looks busiest.

---

## §9 The UI

The UI is a single-page app (`ui/index.mjs`) mounted at `/trading-desk` (§5). It
presents the desk as a Slack-shaped console rather than a dashboard:

- **The Desk page** — the org chart (§10.1): the four-level tree of fund manager,
  desk manager, one line manager per pod, and the roles inside each pod, with live
  state and per-role progress.
- **The chat surface** — a left rail of sessions, a transcript in the middle, and a
  threads panel on the right. The app draws every pixel of the transcript, the
  process lines and the composer itself (TdChat), rather than reshaping the host's
  chat view from the outside — owning the DOM is what makes the intended Slack
  appearance reachable at all.
- **The Run page** — the daily research chain and per-pod lanes from `GET /run` (§2).
- **The Config page** — reads `GET /deskconfig`, shows a diff of a proposed change,
  and runs validation before any write (§2).
- **The Artifacts browser** — the produced-file tree from `GET /artifacts` (§2).

### §9.1 The approvals gate

The app renders the transcript, but it does **not** own the approval controls. The
approve/deny buttons, the `/command` menu, the `@file` mention picker and the model
picker belong to the host composer, and the app has no access to them. Rather than
imitate a capability it does not have, the app states the limit plainly: its composer
sends text only. Where an agent offers a set of choices, the app surfaces them as
inline chips — one click sends that choice's text — but a genuine approval decision is
the host's. The manifest's `/api/approvals` grants (§5) are read scope for surfacing
state, not a path to authoring an approval from this app.

### §9.2 What the foot of the transcript owes a reader

Pressing Enter raises two questions, and the transcript answers both at its foot
rather than in the composer. **Sent** appears under a message once the optimistic row
has been replaced by the real one, and is dropped as soon as anything comes back — a
reply is its own proof of delivery, so a mark under every past line would be noise.
**Working** is a row in the member's own name whose pulsing line stands in for a body
not written yet; it is suppressed while a `streaming` row exists, because text arriving
under that name says more than a line claiming text is coming.

The composer's placeholder is not a substitute for either. It describes the box you
type into rather than the message you already sent, and it reads the same whether you
have sent anything or not — which is how a delivered message came to look swallowed.

---

## §10 Layout

### §10.1 The Desk page and the chat rail

Two surfaces answer two different questions, and the layout keeps them apart.

The **chat rail** is the DM list — *who do I talk to*. A conversation is picked from
the rail, not from a separate page. It has two sections: the standing chain of
command, then the pods.

The **Desk page** is the org chart — *who reports to whom*. It keeps its own tree and
is no longer the only way to switch conversations.

IC rows (the per-role `ic-<pod>-<role>` members) belong in the **org chart, not in
the chat rail**. The reader is the CEO, who briefs the fund manager; a pod's sentiment
analyst is not someone they open a conversation with, and an IC holds no standing
session to open anyway (§2). Putting every IC in the rail would add dozens of rows
nobody messages. So an IC appears on the Desk page, where its folded per-role progress
is legible, and stays out of the rail.

### §10.2 Message typography

Message body text is rendered as markdown through the host's `MarkdownRenderer`, via
the app-sdk UI kit. Its appearance is guarded by CSS variables overridden on the app
root, so the app controls the reading size and leading without forking the renderer.

The message row is Slack's geometry, and it is **deliberately not aligned to the host
chat view**: a roughly 36px avatar in a 52px gutter, an author name at 15px / weight
900 on the timestamp's baseline, an inline timestamp, and same-author merging of
consecutive rows. The body itself reads at 14px on a 24px line, which is the size a
person actually reads a paragraph at; the author line keeps Slack's own 15px / 900 so
the two are distinct jobs rather than one shared size. The palette stays on the app's
theme tokens — the geometry is cloned, the colours are not.

---

## §11 The thread clone model

A thread is not a derived summary of a dispatch. It is **a session whose agent is the
conductor's own**: the conductor opens it, seeds the topic, and answers one line in
the main conversation. The threads surface therefore does not fold a timeline — it
finds those sessions and reports metadata about them, and the panel renders each
session's own live transcript through `/api/chat/slots/{slot_key}`.

### §11.1 Classification by agent

A listed session is classified **by its agent**, never by a folder or a title:

| Kind | Meaning |
|---|---|
| `thread` | the conductor's own clone of itself — its agent is the member's own agent |
| `dispatch` | a session the conductor opened for another member — its agent is that member's |

These two exhaust the payload vocabulary. (The UI's label map tolerates a third
spelling, `clone`, defensively, which is exactly why the payload side is pinned to the
two.) Classification comes from the roster's `{member: agent}` table — the same
`agent` the `/org` profiles map publishes — so a thread's kind can never disagree with
the agent the UI posts to. The agent gate is what makes the scan safe on a real
transcript: a main conversation mentions dozens of unrelated session keys (a pasted
session list, an injected memory block), and every one whose agent is not a desk agent
fails the test and is not listed. When one agent serves several members and the title
does not say which, the session's `member` is left `null` — unattributed beats wrongly
attributed.

### §11.2 One object, slot_key the only key

`GET /threads` returns `{"threads": [...]}` and `GET /thread/{id}` returns one such
object — they are the **same object**, re-derived and picked by id, so they cannot
drift. The object has exactly:

| Field | Type | Rule |
|---|---|---|
| `id` | string | `th-{member}-{date}-{seq}` (§8.1) |
| `kind` | string | `thread` or `dispatch` (§11.1) |
| `title` | string | non-empty |
| `member` | string \| null | the owning member id; if non-null, must appear in `participants` |
| `state` | string | `running`, `done`, `failed` (§8.2) |
| `opened_at` | string | ISO timestamp |
| `participants` | string[] | member ids; non-empty (at least the member the thread hangs off) |
| `last_msg` | string | one line |
| `anchor` | object \| null | the message it hangs under (§8.1) |
| `entry_count` | int | `>= 0` |
| `last_ts` | string \| null | the latest row's timestamp; null when `entry_count` is 0 |
| `slot_key` | string | the session key — the **only** place a key appears |
| `agent` | string | a `tada-*` desk agent |
| `refs` | object | `{"run_date": <date>, "artifacts": [<relpath>, ...]}` |

Any key beyond these is a fault — §11.2 fixes the thread shape.

`slot_key` and `agent` are fields because the panel reads
`/api/chat/slots/{slot_key}` and the composer posts `/api/chat {slot, agent}`, so a
thread is unusable without both. `slot_key` is the **bare** `chat-<n>-<ts>` form
(`^chat-\d+-\d+$`) — the dashboard prefixes are normalised away before it is emitted
(§11.5.2), because a prefixed value would both build a wrong slot URL and split one
session into two threads.

`entry_count` counts the session's visible rows (what the reply chip renders as
"🧵 N updates · latest hh:mm"); `last_ts` is the latest row that *has* a timestamp. Rows
without one give a count with no stamp, which degrades the chip's clock rather than
contradicting the count. With no rows there is nothing to report, so `entry_count` is
0 and `last_ts` is null.

Within a listing, thread ids are unique and the number of distinct `slot_key` values
equals the number of threads — one session is one thread (§11.5.2).

```json
{
  "threads": [
    {
      "id": "th-fund-2026-09-07-1",
      "kind": "thread",
      "title": "Review the AAPL proposal",
      "member": "fund",
      "state": "done",
      "opened_at": "2026-09-07T10:12:00",
      "participants": ["fund"],
      "last_msg": "Wrote the conclusion back to the main conversation",
      "anchor": {
        "main_msg": "mid-8842",
        "ts": "2026-09-07T10:11:40",
        "preview": "Put the bull and bear case for AAPL on one page"
      },
      "entry_count": 6,
      "last_ts": "2026-09-07T10:40:12",
      "slot_key": "chat-9306-1700004006",
      "agent": "tada-fund-manager",
      "refs": { "run_date": "2026-09-07", "artifacts": [] }
    }
  ]
}
```

### §11.5 The session-key invariant

A gateway session key appears in `slot_key` and **nowhere else**. This is the narrower
replacement for the earlier red line that kept every key out of a thread payload:
because the panel now reads `/api/chat/slots/{slot_key}`, the key is a required field,
so the invariant is not "no key" but "a key only in `slot_key`".

The check walks every key name and every string value of a payload, so a key smuggled
into a title, a folded line, a preview or a ref is caught wherever it sits. The
exemption is by **path**, not by value and not by field name: the same key repeated in
a title still fails, and a `slot_key`-named field somewhere the shape does not sanction
is not waved through either. `anchor.preview` (§8.1) and every `/say` and `/thread`
reply are scrubbed under this rule.

A session key is recognised in any of its spellings — the bare `chat-<n>-<ts>`, the
reset-minted `td-<name>-<10-digit>`, or a `dashboard_`-prefixed form.

**§11.5.2 — normalisation.** A mention is accepted bare or `dashboard:` / `dashboard_`
prefixed and normalised to the bare key, so the two spellings are one thread and the
emitted `slot_key` is always the bare form.

**§11.5.3 — the threads folder.** A conductor files its clones in a `threads`
subfolder under its own slot folder; that folder path is the whole locator for the
second derive source (§11.6).

### §11.6 The two derive sources

A thread must stay reachable in the app whatever the gateway has since done with its
tab, so the listing is built from two sources merged on `slot_key`, with the first
winning:

**§11.6.1 — S1, the main conversation's mentions.** The member's main conversation is
scanned for session keys: a visible row's own text, a tool call's addressing input,
and a session-creating tool's output (opening a session *is* opening a thread). Every
key is recorded the first time it is seen; the row it hangs under is the user message
that asked for the work, falling back to the nearest visible row. This source carries
the anchor.

**S2, the threads folder.** The member's `threads` folder (§11.5.3) is read for both
live and archived sessions filed there. The agent gate here is deliberately looser
than S1's: being filed in the folder is itself the declaration that this is that
member's thread, so a session whose agent cannot be resolved is still listed rather
than dropped. A folder-only thread has `anchor: null` — no reply bar under a row, but
it still reaches the user through the header's "In progress" entry (**§11.6.2**).

The merge is on `slot_key` with S1's copy — the one with the anchor — winning. That is
what survives a `/member/{id}/reset`: the new main conversation mentions nothing, so
S1 is empty, but every clone is still filed in the folder, so S2 keeps them reachable.

**§11.6.3 — stable seq.** `seq` is the session's place in creation order within its
date, so the same thread gets the same id whichever source found it and one reset does
not renumber a member's whole list (§8.1).

**§11.6.4 — no gateway paths.** Every gateway fact (the slot table, the folder tree, a
session's messages, its metadata header) arrives through the state object the gateway
injects; this surface resolves no gateway path of its own.

---

## §12 Opening a thread on a message

`POST /thread` opens a thread on one message the user picked. The body is
`{member_id, anchor: {mid, ts}, title?}`. Unlike the derived sources of §11.6, the
anchor is an **input** here — the user chose the row — matching Slack's own gesture of
starting a thread on a specific message.

The session is opened through the gateway's own session-control verb and filed in the
member's `threads` folder, so it is found by that folder source (§11.6) from the next
request on. The anchor is recorded in the app's own data directory, because no gateway
field holds "the message this session hangs under"; a recorded anchor is folded into
the S2 side of the derive rather than being a third source.

The call is **idempotent per anchor**: a second call on the same message returns the
thread already opened on it, so a double-click cannot fork one conversation into two.
The response carries the thread `id`, its `slot_key`, and a `created` flag.

---

## §13 Where a thread hangs

Two rules decide which message a thread hangs under, both about keeping the reply bar
on something the reader can actually see.

**§13.1 — intermediate prose folds away.** A manager's step-by-step narration of
doing the work folds into the collapsed process view, so a reply bar anchored there
would have no visible row to sit on. The anchor is chosen so it lands on a row the
reader sees.

**§13.2 — one anchor, on the message that asked.** A key is recorded the first time it
is seen and never again, so however many times one manager turn names the same session
— the create's output, the "Thread opened" line, the send's input, the closing receipt —
that thread hangs in exactly one place. And it hangs on the **user message that asked**
for the work, not on the manager's narration of carrying it out: a thread belongs to
the sentence the reader typed. When a tool call carries an addressee beside a
free-text body, only the addressing field is read, so a seed brief that merely quotes
another session's key does not mint a thread on it.

---

## §14 Internationalization

English is the canonical language of this codebase. Every string the app itself
authors is written in English at its source: the backend routes (§2) and the scripts
track (§6) emit English, and so do code comments and docstrings. No Python file
authors a non-English display string. The example payloads throughout this document
are the English the code actually produces.

Chinese is a translation layer that lives in exactly one file,
[`ui/i18n.mjs`](../ui/i18n.mjs), and nowhere else. That file holds two tables. UI
chrome — labels the app writes itself, like the "In progress" header entry (§11.6.2)
— is translated through a `t()` lookup. The backend's finished phrases are translated
through a `phrase()` map keyed on the English the backend now writes: a `state_msg`
like `not started` (§2, `GET /org`), an output label like `pod report`, a stage name
like `Analysis` (§11, the four pod stages `Analysis` / `Debate` / `Proposal` /
`Risk`). Where the backend glues a value onto a phrase, `phrase()` looks up the phrase
around the value and keeps the value: a leading count (`2/2 delivered`), a trailing
count (`Analysis 6/8`), a trailing date (`macro brief 2026-09-14`), and a value in the
middle (`the last one stalled at 14:52`). A slot holding another of our phrases is
translated one level down, so `4 of 9 pods delivered, waiting on the rest` comes back
whole rather than half.

The middle-of-sentence match is the one with a sharp edge, because a table entry
becomes a pattern and a pattern can match something it was not written for. Two things
hold it in: the pattern describes the WHOLE message, and an entry needs a floor of its
own literal words before it is compiled at all. A short entry compiles to a pattern
that matches almost anything and would rewrite the tail of a sentence someone
dictated. The one entry left below that floor is matched by shape instead: a stage
label arrives as `Analysis 6/8` and the trailing-count rule handles it.

The `group` field is not in the table at all, and that is the shape of the rule
generally. Both producers — `_group_label` in `backend/org.py`, used when a roster row
carries no group, and `crews/gen_members.py`, used when it does — build `<book> ·
<pod>` and deliberately leave out any word for "pod", because that word is the one
part of the label that changes with the reader. `groupLabel()` in `ui/i18n.mjs`
appends it. Naming the FIELD rather than writing a pattern is what makes this safe: as
a pattern the label is "anything at all". The two producers shipped disagreeing once —
one wrote `Book A · x pod`, the other `Core · x` — and the row carrying the English
noun kept it in a Chinese screen, because there was nothing left to append;
[`tests/test_i18n.py`](../tests/test_i18n.py) now calls both and compares them.

Text a crew member wrote is never translated. A brief, a regime call, a thread title,
an event `msg` typed by an agent is shown exactly as written; `phrase()` returns an
unknown string unchanged, and that pass-through is load-bearing rather than a fallback.
The same rule runs the other way in [`ui/parts.mjs`](../ui/parts.mjs): the receipt
patterns there match the Chinese a Chinese-speaking crew member writes, so Chinese
appears in that file as a PATTERN on purpose. A Chinese *string* anywhere outside the
tables is the defect; a Chinese *pattern* that reads someone else's words is not.

The app opens in English. A saved preference wins; failing that it switches to Chinese
only when the browser asks for it, so a reader with an English locale never sees the
translation layer at all. A key missing from the Chinese table falls back to English
rather than rendering as its own name — right on screen, and the reason the parity
check compares the two tables to each other instead of calling `t()`.

[`tests/test_i18n.py`](../tests/test_i18n.py) holds the whole contract as assertions:
no Chinese string or comment outside the tables, the two tables at key parity, every
key the UI asks for present in both, every backend phrase carrying a Chinese reading,
crew text surviving both languages byte for byte, the two group-label producers
agreeing and neither writing the pod noun, and the opening language. Each assertion was
confirmed to fail when the thing it guards is broken. Because
Chinese exists only in `ui/i18n.mjs`, the contract in §2 and the shapes in
[`tests/schema.py`](../tests/schema.py) are stated once, in English, and the UI is the
only place a second language is added.

---

## Coverage

Every section number cited by the code resolves here: §0, §1, §2, §3, §4, §5, §6, §7,
§8 (§8.1, §8.2), §9 (§9.1), §10 (§10.1, §10.2), §11 (§11.1, §11.2, §11.5 with §11.5.2
and §11.5.3, §11.6 with §11.6.1–§11.6.4), §12, §13 (§13.1, §13.2), and §14. Payload shapes
are stated as [`tests/schema.py`](../tests/schema.py) enforces them; where the code
guarantees less than a full shape — `POST /config/apply`'s success payload, `GET /health`,
`POST /member/{id}/reset` — this document says only what the code guarantees.
