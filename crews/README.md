# crews/ — the roster

Two files. One is generated, one generates it.

| File | Role |
|---|---|
| `members.json` | The roster the backend reads directly for `/org`. **Generated — do not hand-edit.** |
| `gen_members.py` | Builds it from `sectors.yaml` + `roles.yaml` (+ `books.yaml` for labels). |

```bash
python3 crews/gen_members.py            # regenerate
python3 crews/gen_members.py --check    # exit 1 if the committed file is stale
```

Config is looked up in `$DESK_ROOT` first, and falls back to this repository's
`config/*.example.yaml`, so a fresh clone generates a working roster before anyone
has a desk root.

## Composing a team

The roster is not written anywhere. It is the cross product of two files:

- `sectors.yaml` — how many pods there are and what each covers. One line manager
  per entry.
- `roles.yaml` — what a pod is made of. One row per entry, under every line
  manager.

So `roles.yaml` is where you change the shape of a team. Cut the bull/bear debate,
add a macro hedger, drop four analysts to two — edit that file, re-run the
generator, and the org chart, the Desk page and the per-role progress columns all
follow. Nothing about team composition lives in code, and nothing in the test suite
pins a role count.

Two things the app requires of a role, both enforced by the generator:

`title` must be English. The display language is mapped in `ui/i18n.mjs`
(`memberTitle`), so a title stored in another language survives the language switch
and prints the wrong language to half your readers.

`letter` must be unique across the file. The avatar hue is derived from the
monogram, so two roles sharing one share a colour and stop being tellable apart.

## The three layers

```
CEO (you — not a member)
└── fund-manager ──── macro-strategist
    └── desk-manager
        └── line-manager · <pod>        one per sectors.yaml entry
            └── <role> · <pod>          one per roles.yaml entry
    risk-pod / trader / scrum-master    standing, alongside desk-manager
```

The six standing roles are the chain of command and are fixed. Everything below
`desk-manager` is generated.

## Why a line manager has a session and a role does not

A line manager is a standing conversation: it has a `slot_hint`
(`{folder, title}`) that the backend resolves to a live session key, or `null` when
that session does not exist yet.

A role is spawned per ticker per round and never persists, so it carries no
`slot_hint` at all. Its state is folded from the files it writes — `artifacts`
globs plus `per_ticker` — which is why the Desk page can show `6/8` for a role that
has no session to inspect. That table mirrors the stage table in
`scripts/desk_events.py`; keep the two in step.

## Fields

`id` `name` `title` `duty` `parent` `group` `pod` `tickers` carry the meanings in
the `/org` contract. `state`, `state_msg`, `slot_key` and `recent_outputs` are
deliberately **absent**: they are runtime, computed by the backend from session
state and artifacts on disk.

Beyond the contract:

- `alias` — the handle on the hero card. A role's is `<role>@<pod>`, because every
  pod draws the same roles and the pod is what makes the handle address one person.
- `avatar_letter` — one or two letters. Line managers are all `L`; roles use their
  configured monogram.
- `reports_label` — the "direct reports" value on the hero card.
- `output_sources` — `[{label, dir}]`, directories relative to the desk root. The
  backend takes the newest file in each and folds them into `recent_outputs`.
  Directories rather than files because filenames carry dates.
- `artifact_globs` / `per_ticker` — role rows only. What this role owes per ticker.
  `per_ticker: null` scales with that pod's `analyst_copies`.
- `duty_template` — `desk` and the line managers only. See below.

## duty is job description, never orchestration

`duty` is what this member does for a reader. Sentinel strings, tool names, command
names and session mechanics are prompt material and are rejected by the test suite
if they appear here.

`desk` and the line managers carry a `duty_template` as well, because their duty
text embeds live data — the pod name, its ticker list, the pod count. The backend
renders the template against a fresh read of `sectors.yaml`, so a ticker moving pods
updates the text; the flat `duty` field is a generation-time snapshot for consumers
that do not render.

That is the whole reason this generator exists. Hand-written, near-identical pod
entries go stale silently the moment a ticker moves.
