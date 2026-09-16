"""The i18n contract (ARCHITECTURE.md §14).

English is canonical at the source. Every string the app itself authors is written
in English where it lives, and Chinese exists only as the two tables in
``ui/i18n.mjs``. Four things have to hold for that to be true on screen rather
than only in intent, and each has been broken at least once by hand:

* No source file outside the tables may hold a Chinese STRING. A Chinese
  *pattern* is fine and sometimes required -- ``ui/parts.mjs`` matches the receipt
  line a Chinese-speaking crew member wrote -- so the check looks inside string
  literals, not at the line.
* Every key the UI asks for must exist in BOTH tables. A missing key renders as
  its own name, which is a visible defect and an invisible test pass.
* Every phrase the BACKEND authors must have a Chinese reading. This is the one
  that leaks: the backend hands over finished text, so a gap shows up as English
  sitting inside a Chinese screen and no key lookup ever fails.
* Text a crew member wrote must survive both languages byte for byte. The same
  function carries it, and translating someone's analysis would put words in
  their mouth.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import require_json, require_module, require_path

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")

#: The one file allowed to hold Chinese strings: it *is* the Chinese table.
TABLE_FILE = "ui/i18n.mjs"

#: Phrases the backend hands over as finished display text. Kept here as literals
#: rather than scraped from the Python, because the point of the check is to
#: notice when the two sides drift -- a scraper would follow the drift silently.
#: Grouped by the shape that has to survive translation.
BACKEND_PHRASES = [
    # plain state messages
    "on station",
    "not started",
    "not started today",
    "stuck, needs a look",
    "working on today's tasks",
    "today's work is delivered",
    "no tickers for this pod today",
    "pod report delivered today",
    "a new session is ready, waiting for your first message",
    # a leading count
    "8/8 delivered",
    "3/8 in progress",
    "0/8 not started",
    # a trailing count, with and without a tail word
    "Analysis 6/8",
    "Debate 2/2 back",
    # a trailing date
    "macro brief 2026-09-14",
    "Latest pod report 2026-09-09",
    # a value in the middle
    "3 outputs in, rolling up",
    "the last one stalled at 14:52",
    "dispatched, 4 tickers assigned",
    "brief delivered (memory/briefs/2026-09-14.md)",
    # a slot holding another phrase, which must translate one level down
    "4 of 9 pods delivered, waiting on the rest",
    "today's macro brief delivered",
    # duty prose
    "Turns reviewed views into concrete plans: ticker, direction, size, timing.",
    "Runs the example-megacap pod (AAPL MSFT): converges the pod's conclusions into one pod report.",
    # run-view words
    "dispatched",
    "delivered",
    "pod report not written",
    "CEO brief written",
]

#: Sentences a crew member could write. They must come back unchanged in every
#: language. The last two are deliberately shaped like our own phrases -- one
#: opens with a count, one contains a phrase we do translate -- because that is
#: where a careless matcher starts rewriting someone's words.
CREW_TEXT = [
    "Cut the October calls; delta 0.049 needs a 22% month to break even.",
    "Supply only loosens in 2027, so the thesis survives a weak quarter.",
    "6/8 files in but the sentiment copy is thin",
    "pod report delivered, and I would add on weakness",
    # Shaped like our own SHORT templates on purpose. `{pod} pod` and
    # `{stage} {a}/{b}` are the two entries whose literal text is nearly nothing,
    # so a matcher without the literal floor turns each of these into a sentence
    # with a Chinese word spliced into the middle of someone's analysis.
    "I would trim the semi pod",
    "the read-through is Analysis 6/8",
    "moving risk out of Book A · example-megacap pod",
]


def _string_literals(text: str) -> list[tuple[int, str]]:
    """Every quoted literal in a JS/Python source, as ``(line, body)``.

    Deliberately simple: it finds the quoted runs on a line and ignores regex
    literals, which is the whole distinction the first check rests on. It does not
    try to parse the language, so a quote inside a comment counts -- which is the
    safe direction, since a Chinese comment is also something this repo does not
    want.
    """
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r"'([^'\\\n]*)'|\"([^\"\\\n]*)\"|`([^`\\]*)`", line):
            body = next(g for g in match.groups() if g is not None)
            if body:
                found.append((lineno, body))
    return found


def _sources() -> list[Path]:
    root = require_path(".", "repo root")
    out: list[Path] = []
    for pattern in ("ui/*.mjs", "backend/*.py", "scripts/*.py", "crews/*.py", "dev/*.py"):
        out.extend(sorted(root.glob(pattern)))
    return out


def test_no_chinese_strings_outside_the_table() -> None:
    """A Chinese STRING outside `ui/i18n.mjs` is text the switch cannot reach."""
    offenders: list[str] = []
    for path in _sources():
        rel = path.relative_to(require_path(".", "repo root")).as_posix()
        if rel == TABLE_FILE:
            continue
        for lineno, body in _string_literals(path.read_text(encoding="utf-8")):
            if CJK.search(body):
                offenders.append(f"{rel}:{lineno}  {body[:70]}")
    assert not offenders, (
        "[ARCHITECTURE.md §14] Chinese string literals outside "
        f"{TABLE_FILE} -- move the words into its tables:\n" + "\n".join(offenders)
    )


def test_no_chinese_in_comments_or_docstrings() -> None:
    """A public repo reads in one language, comments included."""
    offenders: list[str] = []
    root = require_path(".", "repo root")
    for path in _sources():
        rel = path.relative_to(root).as_posix()
        if rel == TABLE_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            is_comment = stripped.startswith(("#", "//", "*", "/*"))
            # A regex literal may hold Chinese on purpose: it matches what someone
            # else wrote. A comment may not.
            if is_comment and CJK.search(line) and "/" not in stripped.lstrip("/*# "):
                offenders.append(f"{rel}:{lineno}  {stripped[:70]}")
    assert not offenders, (
        "[ARCHITECTURE.md §14] Chinese in comments -- this repo reads in English:\n"
        + "\n".join(offenders)
    )


def _run_node_probe(tmp_path: Path, body: str) -> dict:
    """Import the real `ui/i18n.mjs` under Node and return the probe's JSON.

    The module imports `react` for its store subscription and there is no
    `node_modules` here, so a resolve hook points that one specifier at a stub.
    The module under test is the real file on disk, not a copy.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH -- run tests/test_i18n.py manually (ARCHITECTURE.md §14)")
    i18n = require_path(TABLE_FILE, "§14 the translation tables")
    ui_dir = require_path("ui", "§0 ui track deliverable")

    (tmp_path / "react-stub.mjs").write_text(
        "export function useSyncExternalStore(sub, get) { return get() }\n"
        "export default { useSyncExternalStore }\n",
        encoding="utf-8",
    )
    (tmp_path / "hooks.mjs").write_text(
        "import { pathToFileURL } from 'node:url'\n"
        f"const STUB = pathToFileURL({json.dumps(str(tmp_path / 'react-stub.mjs'))}).href\n"
        "export async function resolve(spec, ctx, next) {\n"
        "  if (spec === 'react' || spec === 'react/jsx-runtime') return { url: STUB, shortCircuit: true }\n"
        "  return next(spec, ctx)\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "register.mjs").write_text(
        "import { register } from 'node:module'\n"
        "import { pathToFileURL } from 'node:url'\n"
        f"register(pathToFileURL({json.dumps(str(tmp_path / 'hooks.mjs'))}).href)\n",
        encoding="utf-8",
    )
    preamble = (
        "globalThis.window = { localStorage: { getItem: () => null, setItem: () => {} } }\n"
        "Object.defineProperty(globalThis, 'navigator', "
        "{ value: { language: 'en-US', languages: ['en-US'] }, configurable: true })\n"
        f"const I18N = {json.dumps(str(i18n))}\n"
        f"const UI_DIR = {json.dumps(str(ui_dir))}\n"
        "const m = await import(I18N)\n"
    )
    probe = tmp_path / "probe.mjs"
    probe.write_text(preamble + body, encoding="utf-8")
    proc = subprocess.run(
        [node, "--import", str(tmp_path / "register.mjs"), str(probe)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_two_tables_carry_the_same_keys(tmp_path: Path) -> None:
    """A key present in one table and absent from the other is a silent gap.

    `t()` cannot find it: a missing Chinese key falls back to English on purpose,
    which is right on screen and invisible to a probe that only asks whether the
    key name came back. So the key sets are compared to each other.
    """
    result = _run_node_probe(tmp_path, """
const langs = m.tableLangs()
const sets = Object.fromEntries(langs.map((l) => [l, m.tableKeys(l)]))
const report = {}
for (const a of langs) {
  for (const b of langs) {
    if (a === b) continue
    report[`${a}_missing_from_${b}`] = sets[a].filter((k) => !sets[b].includes(k))
  }
}
console.log(JSON.stringify({ langs, counts: Object.fromEntries(langs.map((l) => [l, sets[l].length])), report }))
""")
    assert sorted(result["langs"]) == ["en", "zh-CN"], f"unexpected languages: {result['langs']}"
    assert min(result["counts"].values()) > 50, f"tables look empty: {result['counts']}"
    gaps = {name: keys for name, keys in result["report"].items() if keys}
    assert not gaps, (
        "[ARCHITECTURE.md §14] the two tables have drifted:\n"
        + "\n".join(f"  {name}: {', '.join(keys)}" for name, keys in gaps.items())
    )


def test_every_key_the_ui_asks_for_exists_in_both_tables(tmp_path: Path) -> None:
    """A key with no entry renders as its own name -- visible, and silently green."""
    result = _run_node_probe(tmp_path, """
import fs from 'node:fs'
import path from 'node:path'
const used = new Map()
for (const f of fs.readdirSync(UI_DIR).filter((n) => n.endsWith('.mjs'))) {
  const text = fs.readFileSync(path.join(UI_DIR, f), 'utf8')
  for (const re of [/\\bt\\(\\s*(['"`])([A-Za-z0-9_.]+)\\1/g, /\\bsay\\(\\s*(['"`])([A-Za-z0-9_.]+)\\1/g]) {
    for (const hit of text.matchAll(re)) {
      if (!used.has(hit[2])) used.set(hit[2], new Set())
      used.get(hit[2]).add(f)
    }
  }
}
const vars = { n: 1, N: 1, who: 'x', count: 1, name: 'x', total: 1, done: 1, status: 1, msg: 'x', which: 'x', key: 'x' }
const missing = {}
for (const lang of ['en', 'zh-CN']) {
  m.setLang(lang)
  missing[lang] = [...used].filter(([k]) => m.t(k, vars) === k).map(([k, w]) => `${k} (${[...w].join(', ')})`)
}
console.log(JSON.stringify({ count: used.size, missing }))
""")
    assert result["count"] > 50, f"only found {result['count']} t() call sites -- the scan is broken"
    for lang in ("en", "zh-CN"):
        assert not result["missing"][lang], (
            f"[ARCHITECTURE.md §14] keys missing from the {lang} table:\n"
            + "\n".join(result["missing"][lang])
        )


def test_every_backend_phrase_has_a_chinese_reading(tmp_path: Path) -> None:
    """The leak: the backend hands over finished text, so a gap never fails a lookup."""
    result = _run_node_probe(tmp_path, f"""
m.setLang('zh-CN')
const cjk = /[\\u4e00-\\u9fff]/
const cases = {json.dumps(BACKEND_PHRASES, ensure_ascii=False)}
const untranslated = cases.filter((c) => !cjk.test(m.phrase(c)))
console.log(JSON.stringify({{ untranslated }}))
""")
    assert not result["untranslated"], (
        "[ARCHITECTURE.md §14] backend phrases with no Chinese reading -- these show "
        "English inside a Chinese screen:\n" + "\n".join(result["untranslated"])
    )


def test_crew_text_survives_both_languages(tmp_path: Path) -> None:
    """Translating someone's analysis would put words in their mouth."""
    result = _run_node_probe(tmp_path, f"""
const cases = {json.dumps(CREW_TEXT, ensure_ascii=False)}
const changed = []
for (const lang of ['en', 'zh-CN']) {{
  m.setLang(lang)
  for (const c of cases) {{
    const out = m.phrase(c)
    if (out !== c) changed.push(`[${{lang}}] ${{c}} -> ${{out}}`)
  }}
}}
console.log(JSON.stringify({{ changed }}))
""")
    assert not result["changed"], (
        "[ARCHITECTURE.md §14] crew-authored text was rewritten by the switch:\n"
        + "\n".join(result["changed"])
    )


def test_neither_group_label_producer_bakes_in_the_word_pod(desk_root: Path) -> None:
    """The pod noun belongs to the reader, so neither producer may write it.

    Two places build a pod row's `group`: `_group_label` in `backend/org.py`, used
    when a roster row carries none, and `crews/gen_members.py`, used when it does.
    They shipped disagreeing once -- one wrote `Book A - x pod`, the other `Core -
    x` -- and the row carrying the English noun kept it in a Chinese screen,
    because `groupLabel()` in the UI had nothing left to append.

    Checked by CALLING them, not by reading them: the words `pod` and `"pod"`
    appear all over both files as an argument name and a JSON key, so a text scan
    reports those and misses a label built by concatenation.
    """
    org = require_module("backend/org.py", "backend.org", "§2 GET /org")
    pods = [p for p in (org.deskdata.pods(desk_root) or {})]
    assert pods, "the desk_root fixture grew no pods -- this test proves nothing"

    produced: dict[str, str] = {}
    for pod in pods:
        produced[f"_group_label({pod})"] = org._group_label(desk_root, pod)

    # The generator's side is read from what it actually WROTE. `crews/` is not on
    # `sys.path`, and the committed roster is its output, so this checks the real
    # artifact rather than a re-derivation of the rule under test.
    roster = require_json("crews/members.json", "§4 the roster")
    rows = roster["members"] if isinstance(roster, dict) else roster
    for row in rows:
        label = row.get("group")
        if label:
            produced[f"roster({row['id']})"] = str(label)

    offenders = {
        where: value
        for where, value in produced.items()
        if re.search(r"\bpods?\b", str(value), re.IGNORECASE)
    }
    assert not offenders, (
        "[ARCHITECTURE.md §14] a group label carries the word for \"pod\" -- leave "
        "it out and let groupLabel() append the reader's own:\n"
        + "\n".join(f"  {k} -> {v!r}" for k, v in offenders.items())
    )
    # And the two agree on the shape, which is the failure that actually shipped.
    # `+` sits inside the token class on purpose: a pod held by two books reads
    # `A+B - pod`, the same shape carrying more data rather than a second shape.
    shapes = {re.sub(r"[\w.+-]+", "X", v) for v in produced.values()}
    assert len(shapes) == 1, f"the producers disagree on shape: {sorted(shapes)}\n{produced}"


def test_the_group_label_gets_the_readers_own_pod_noun(tmp_path: Path) -> None:
    """Whatever the producers wrote, the row ends in a word the reader knows."""
    result = _run_node_probe(tmp_path, """
const cases = ['Core · example-megacap', 'example-megacap', 'Core+Tactical · x',
               'Core · example-megacap pod']
const out = {}
for (const lang of ['en', 'zh-CN']) {
  m.setLang(lang)
  out[lang] = cases.map((c) => m.groupLabel(c))
}
m.setLang('zh-CN')
out.empty = [m.groupLabel(''), m.groupLabel(null), m.groupLabel(undefined)]
console.log(JSON.stringify(out))
""")
    assert result["en"] == [
        "Core · example-megacap pod",
        "example-megacap pod",
        "Core+Tactical · x pod",
        # a legacy label that already carried the noun is not doubled
        "Core · example-megacap pod",
    ], result["en"]
    assert all(row.endswith("\u7ec4") for row in result["zh-CN"]), result["zh-CN"]
    assert all("pod" not in row for row in result["zh-CN"]), result["zh-CN"]
    assert result["empty"] == ["", "", ""], result["empty"]


def test_the_app_opens_in_english_unless_the_browser_asks_for_chinese(tmp_path: Path) -> None:
    """A public app opens in English; a Chinese browser is met in Chinese."""
    result = _run_node_probe(tmp_path, """
const read = (code) => {
  const src = fs.readFileSync(I18N, 'utf8')
  return src
}
import fs from 'node:fs'
const src = read()
const detect = /function detect\\(\\)[\\s\\S]*?\\n}/.exec(src)[0]
console.log(JSON.stringify({
  defaults_to_en: /return 'en'/.test(detect),
  reads_browser: /navigator/.test(detect) && /zh/.test(detect),
  honours_saved: /getItem/.test(detect),
}))
""")
    assert result["defaults_to_en"], "[§14] detect() must fall back to English, not Chinese"
    assert result["reads_browser"], "[§14] detect() must meet a Chinese browser in Chinese"
    assert result["honours_saved"], "[§14] a saved preference must still win"
