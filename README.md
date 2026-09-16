# Trading Desk

A Slack-shaped console for a research desk staffed by agents. You are the CEO: you
talk to the fund manager, and a chain of agents below it does the work and reports
back.

This repository is the **console and the skeleton**. It ships no positions, no
account, no securities picks, and no research. Those live in a separate directory
you own — the desk root — and the app only ever reads it.

## What it gives you

**A chat surface, not a dashboard.** Sector pods and their people are an org chart;
the thing you actually use is a conversation. Sessions on the left, transcript in
the middle, threads on the right.

**A real org chart.** Four levels, generated from two config files: fund manager,
desk manager, one line manager per sector pod, and every role inside a pod. Roles
have no standing session — they are spawned per ticker per round — so their progress
is folded from the files they write rather than from a session that does not exist.

**Threads that keep the main conversation readable.** Ask something big and the
manager opens a thread, works in it, and comes back with one line. The panel shows
the message the thread came from and the brief it was given.

**Config editing with a gate in front of it.** `/config` reads your `books.yaml`
and `sectors.yaml`, shows a diff of what a change would write, and runs your own
validator against the proposed version in a sandbox. A config that fails is never
written.

**A daily run view.** The four-stage chain — research, debate, proposal, risk
review — with per-pod progress derived from artifacts on disk, so it is honest even
when nothing emitted an event.

## Two directories, and why

| | What it is | Who owns it |
|---|---|---|
| this repository | the app: routes, UI, roster generator, tests | shared, public |
| `$DESK_ROOT` | your desk: config, positions, research output | you, private |

The split is the point. The desk root names your broker and states how much money is
at stake. Nothing in this repository hardcodes a path into it — resolution is
`deskRoot` in the app's own config, then `$DESK_ROOT`, then `~/trading-desk`.

The layout the app expects:

```
$DESK_ROOT/
  sectors.yaml                              pods, coverage, book membership
  books.yaml                                capital and account constraints
  roles.yaml                                what a pod is made of
  engine/validate_config.py                 your config gate
  runs/<date>/events.jsonl                  run events, when your engine writes them
  memory/briefs/<date>.md                   the desk brief
  teams/<team>/reports/<date>.md            pod / macro / risk rollups
  teams/<pod>/reports/<date>/<TICKER>/*.md  per-role output
```

Only the first two are required to boot. Everything else fills in as the desk runs;
a missing directory reads as "nothing yet", never as an error.

## Setup

Requires a KiroCrew gateway, Python 3.11+ and PyYAML.

```bash
# 1. Pick a desk root and scaffold it from the shipped examples.
export DESK_ROOT="$HOME/trading-desk"
mkdir -p "$DESK_ROOT/engine"
cp config/sectors.example.yaml "$DESK_ROOT/sectors.yaml"
cp config/books.example.yaml   "$DESK_ROOT/books.yaml"
cp config/roles.example.yaml   "$DESK_ROOT/roles.yaml"
cp config/engine/validate_config.py "$DESK_ROOT/engine/"

# 2. Check it.
(cd "$DESK_ROOT" && python3 engine/validate_config.py)

# 3. Generate the roster for your pods and roles.
python3 crews/gen_members.py

# 4. Install the app into your gateway, then enable it in the dashboard.
kirocrew app install .
```

The example config defines two pods and four large-cap tickers. That is a **shape to
copy, not a recommendation** — replace it with your own coverage. Nothing here picks
securities.

`scripts/install.sh` is optional; the app's self-heal cron does the same work within
15 minutes of install.

## Changing the team

`config/roles.yaml` is the entry point. It lists the roles every pod gets, in
pipeline order, and the roster is the cross product of it and `sectors.yaml`. Cut the
bull/bear debate, add a macro hedger, drop four analysts to two — edit that file and
re-run the generator. No code changes, and the test suite pins no role count.

The shipped example runs ten roles per pod: four analysts working independently, a
bull and a bear arguing over their findings, a pod trader turning that into a
proposal, and three risk reviewers — aggressive, conservative and neutral — arguing
over the proposal.

See `crews/README.md` for the field-by-field contract.

## Tests

```bash
KIROCREW_SRC=/path/to/kirocrew/src python3 -m pytest tests/ -q
```

`KIROCREW_SRC` points at a gateway checkout so the tests can use the real
`AppRoute` / `AppContext`; without it the gateway-dependent tests skip and the rest
still run. Every test builds its own temp desk root — none reads yours.

## Not included

**Agents.** The roster names an agent per role (`tada-technicals` and friends). The
prompts are yours: this app reads what they produce and never runs them.

**An orchestrator.** Something has to walk the pods each day and write into
`teams/<pod>/reports/...`. The app derives state from those files rather than
requiring a particular engine, so any runner works.

**Market data or execution.** The trader row means an agent that proposes orders for
your approval. Nothing here talks to a broker.

## Safety

Read-only against your desk by default. The two writing paths are `/config/apply`,
which is gated by your validator and writes atomically after taking a backup, and
`/thread`, which creates gateway sessions. Every path is contained to the desk root:
both sides are resolved before comparison, so a symlink pointing out of the tree is
refused.

Nothing here gives financial advice. It is a console for reading what a set of agents
wrote.

## Licence

MIT. See `LICENSE`.
