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
        # `i18n.mjs` needs only the store hook, but a probe that imports a RENDER
        # module (`parts.mjs`, `chat.mjs`) pulls in the jsx runtime and the hooks
        # too, and a missing named export fails ESM linking before a single line
        # runs. The extras are inert: they let the module load so its pure
        # functions can be called.
        "const noop = () => {}\n"
        "export function useSyncExternalStore(sub, get) { return get() }\n"
        "export function useState(v) { return [typeof v === 'function' ? v() : v, noop] }\n"
        "export function useEffect() {}\n"
        "export function useMemo(f) { return f() }\n"
        "export function useRef(v) { return { current: v } }\n"
        "export function useCallback(f) { return f }\n"
        "export function createElement(type, props) { return { type, props } }\n"
        "export function jsx(type, props) { return { type, props } }\n"
        "export function jsxs(type, props) { return { type, props } }\n"
        "export const Fragment = 'Fragment'\n"
        "export class Component { constructor(p) { this.props = p } render() { return null } }\n"
        "export default { useSyncExternalStore, useState, useEffect, useMemo, useRef,\n"
        "  useCallback, createElement, jsx, jsxs, Fragment, Component }\n",
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


# ─── The translator must not be shadowed ─────────────────────────────────────
#
# `parts.mjs` imports `t` at module level and calls it as `t('key')`. A local
# binding named `t` shadows that import for its whole scope, so the call site
# reaches whatever the local holds. `dayName` held a parsed timestamp -- a NUMBER --
# and the page died with `t is not a function`, taking the entire chat view with
# it. The two tests below come at it from both ends: one runs the real code on the
# real clock, the other reads every module for the shape that caused it.


def test_the_day_separator_names_today_and_yesterday_in_both_languages(tmp_path: Path) -> None:
    """The row separator must reach the translator, which needs today's clock.

    `dayName` only calls the translator on TODAY and YESTERDAY -- every other date
    takes a `toLocaleDateString` branch that touches nothing. Every fixture in this
    repo is dated in the past, so the whole suite passed while the live app crashed
    on open. The timestamps here are therefore computed from the clock at run time
    and must never be replaced with literals: a hard-coded date silently stops
    testing the branch that broke.
    """
    result = _run_node_probe(tmp_path, """
const parts = await import(UI_DIR + '/parts.mjs')
const now = new Date()
const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
const older = new Date(now); older.setDate(now.getDate() - 9)
const msgs = [
  { role: 'user', ts: older.toISOString(), content: 'an older day' },
  { role: 'user', ts: yesterday.toISOString(), content: 'yesterday' },
  { role: 'user', ts: now.toISOString(), content: 'today' },
]
const out = {}
for (const lang of ['en', 'zh-CN']) {
  m.setLang(lang)
  try {
    const rows = parts.chatItems(msgs, {}).filter((i) => i.kind === 'day')
    out[lang] = { labels: rows.map((r) => r.label), error: null }
  } catch (e) {
    out[lang] = { labels: null, error: String((e && e.message) || e) }
  }
}
console.log(JSON.stringify(out))
""")
    for lang in ("en", "zh-CN"):
        assert result[lang]["error"] is None, (
            f"[ARCHITECTURE.md §14] building the transcript threw in {lang}: "
            f"{result[lang]['error']} -- a local binding is shadowing the imported `t`"
        )

    expected = {"en": ("Yesterday", "Today"), "zh-CN": ("昨天", "今天")}
    for lang, (yst, today) in expected.items():
        labels = result[lang]["labels"]
        assert len(labels) == 3, (
            f"[§14] expected three day separators in {lang}, got {labels!r}"
        )
        assert labels[1] == yst, f"[§14] yesterday's separator in {lang}: {labels!r}"
        assert labels[2] == today, f"[§14] today's separator in {lang}: {labels!r}"

    # The third separator is any older day, and it is WORDS: a weekday and a month
    # name. Formatted on the host locale it read "Tuesday, September 8" in the
    # middle of a Chinese transcript, so it must carry the reader's language.
    older_en, older_zh = result["en"]["labels"][0], result["zh-CN"]["labels"][0]
    assert not CJK.search(older_en), (
        f"[§14] the older-day separator should be English for an English reader: {older_en!r}"
    )
    assert CJK.search(older_zh), (
        "[§14] the older-day separator is not in the reader's language -- it is "
        f"formatted on the host locale: {older_zh!r}"
    )


def _mask_js(text: str) -> str:
    """Blank comment and string BODIES, keeping offsets, so braces in them don't count."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        elif text[i] in "'\"`":
            quote, j = text[i], i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(text[i] + "".join(c if c == "\n" else " " for c in text[i + 1 : j]))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


#: A local binding named `t`: a declaration, or a parameter on its own.
_T_BINDING = re.compile(
    r"(?:(?:const|let|var)\s+t\s*=)"
    r"|(?:\(\s*t\s*\)\s*=>)"
    r"|(?:\(\s*t\s*,)"
    r"|(?:function\s+\w+\s*\(\s*t\s*[,)])"
)
#: A translator call. `.t(` and `foo_t(` are other things and must not match.
_T_CALL = re.compile(r"(?<![A-Za-z0-9_.$])t\(\s*['\"]")


def test_no_local_binding_shadows_the_translator_where_it_is_called(tmp_path: Path) -> None:
    """A local `t` in a scope that also calls `t('key')` is the crash, statically.

    Scope is found by matching braces to the INNERMOST block containing the
    binding. Scanning forward for the next `{` instead lands on whatever block the
    binding's own statement opens, which blames an unrelated function and misses
    the real one -- that mistake pointed at `rowTime` while `dayName` was the bug.

    A shadow in a scope with no translator call is allowed: `t` for a thread object
    reads fine in a list callback. This check is what makes that safe, because the
    day a translator call joins one of those scopes, it fails here.
    """
    ui_dir = require_path("ui", "§0 ui track deliverable")
    live: list[str] = []
    for path in sorted(Path(ui_dir).glob("*.mjs")):
        if path.as_posix().endswith(TABLE_FILE):
            continue  # the table defines `t`; it does not consume it
        text = path.read_text(encoding="utf-8")
        masked = _mask_js(text)

        stack: list[int] = []
        pairs: list[tuple[int, int]] = []
        for idx, ch in enumerate(masked):
            if ch == "{":
                stack.append(idx)
            elif ch == "}" and stack:
                pairs.append((stack.pop(), idx))

        for bind in _T_BINDING.finditer(masked):
            inner = None
            for lo, hi in pairs:
                if lo < bind.start() < hi and (inner is None or lo > inner[0]):
                    inner = (lo, hi)
            if inner is None:
                continue
            body = masked[inner[0] : inner[1]]
            calls = [
                masked[: inner[0] + c.start()].count("\n") + 1
                for c in _T_CALL.finditer(body)
            ]
            if calls:
                line = text[: bind.start()].count("\n") + 1
                src = text.splitlines()[line - 1].strip()
                live.append(
                    f"{path.name}:{line}  {src}\n"
                    f"      but the same scope calls the translator at line(s) {calls}"
                )

    assert not live, (
        "[ARCHITECTURE.md §14] a local binding named `t` shadows the imported "
        "translator in a scope that calls it -- that scope's `t('key')` will call "
        "the local instead and throw `t is not a function`:\n" + "\n".join(live)
    )


def test_the_row_draws_only_actions_that_can_act(tmp_path: Path) -> None:
    """A permanent refusal is not drawn; a temporary one is drawn and explained.

    Two reasons stop the Thread button, and they are different KINDS of fact. A row
    inside a thread panel can never nest a thread, and a message that already has
    one gets in through its reply bar -- neither will change, so a greyed button
    there only invites the reader to find a dead end. A gateway whose build has no
    `POST /thread` may gain one, and the reader did nothing to cause it, so that
    refusal is drawn and carries a sentence.

    It shipped the other way round: the panel drew a greyed button whose tooltip
    read "This backend cannot open threads yet", accusing the gateway of missing a
    feature it has. Hiding it is what the codebase already does for the
    already-has-a-thread case, so the two agree now.

    The counts are asserted exactly, which is what holds the row to the actions of
    the surface it replicates. A copy-the-text button was the third one here; the
    platform already copies a selection, and ours could only report success in its
    own tooltip, so a click looked like nothing happening -- the row read as
    buttons that open nothing.

    `RowActions` is called rather than mounted: what a reader hovers is the
    `title` on the button, so that is what is read back.
    """
    result = _run_node_probe(tmp_path, """
const parts = await import(UI_DIR + '/parts.mjs')

const buttons = (node, out = []) => {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { node.forEach((n) => buttons(n, out)); return out }
  const p = node.props || {}
  if (p['aria-label']) out.push({ label: p['aria-label'], title: p.title || '', disabled: !!p.disabled })
  for (const v of Object.values(p)) if (v && typeof v === 'object') buttons(v, out)
  return out
}
const probe = (props) => buttons(parts.RowActions({ onQuote: () => {}, ...props }))

const out = {}
for (const lang of ['en', 'zh-CN']) {
  m.setLang(lang)
  out[lang] = {
    thread_word: m.t('act_thread'),
    quote_word: m.t('act_quote'),
    in_a_panel: probe({ nested: true, onOpenThread: null }),
    already_has_one: probe({ hasThread: true, onOpenThread: () => {} }),
    route_missing: probe({ unavailable: true, onOpenThread: null }),
    live: probe({ onOpenThread: () => {} }),
  }
}
console.log(JSON.stringify(out))
""")

    for lang in ("en", "zh-CN"):
        case = result[lang]
        word = case["thread_word"]
        thread_of = lambda rows: [r for r in rows if r["label"] == word]

        # Permanent: not drawn at all.
        assert not thread_of(case["in_a_panel"]), (
            f"[ARCHITECTURE.md §11] in {lang} a row inside a thread panel still draws "
            f"a Thread button: {case['in_a_panel']!r} -- a thread cannot nest, so "
            "there is nothing for the reader to do with it"
        )
        assert not thread_of(case["already_has_one"]), (
            f"[§11] in {lang} a message that already has a thread still draws a "
            f"Thread button: {case['already_has_one']!r}"
        )
        # Quote survives both cases -- hiding one action must not hide the row --
        # and it is the ONLY thing left, which is what keeps a third button from
        # reappearing here.
        for name in ("in_a_panel", "already_has_one"):
            assert [r["label"] for r in case[name]] == [case["quote_word"]], (
                f"[§11] in {lang} the {name} row should hold Quote and nothing "
                f"else, got {case[name]!r}"
            )

        # Temporary: drawn, dead, and explained.
        missing = thread_of(case["route_missing"])
        assert len(missing) == 1, (
            f"[§11] in {lang} a gateway without the route should still draw the "
            f"button so its reason can be read: {case['route_missing']!r}"
        )
        assert missing[0]["disabled"], f"[§11] in {lang} that button must be dead"
        assert missing[0]["title"] and missing[0]["title"] != word, (
            f"[§11] in {lang} the dead button carries no reason: {missing[0]!r}"
        )

        # Live: drawn, alive, and describing the action rather than a refusal.
        live = thread_of(case["live"])
        assert len(live) == 1 and not live[0]["disabled"], (
            f"[§11] in {lang} the live Thread button is missing or dead: {case['live']!r}"
        )
        assert live[0]["title"] != missing[0]["title"], (
            f"[§11] in {lang} a live button reads as a refusal: {live[0]!r}"
        )
        assert [r["label"] for r in case["live"]] == [case["quote_word"], word], (
            f"[§11] in {lang} the full row should read Quote then Thread, got "
            f"{case['live']!r}"
        )

    # A tooltip string nothing renders is a promise to the reader never kept, and
    # it also hides which refusals the product actually has. Both of these used to
    # sit in the tables unrendered -- `act_thread_nested` because the panel showed
    # the wrong one, `act_thread_open` because that button is hidden, not labelled.
    table = Path(require_path(TABLE_FILE, "§14 the translation tables")).read_text(encoding="utf-8")
    for gone in ("act_thread_nested", "act_thread_open", "act_copy"):
        assert gone not in table, (
            f"[§14] {gone} is back in the tables; if something now renders it, assert "
            "that here instead of leaving it unreachable"
        )

    # The row reads the message body for the quote only. Reaching the clipboard
    # from here is the button that was removed, so its absence is the check --
    # counting buttons cannot see a handler wired to an existing one.
    render = Path(require_path("ui/parts.mjs", "§11 the row actions")).read_text(encoding="utf-8")
    assert "clipboard" not in render, (
        "[§11] the row reaches for the clipboard again; the platform copies a "
        "selection, and a control that can only report success in its own tooltip "
        "reads as a button that does nothing"
    )

    # RowActions is exercised by calling it, which cannot see whether the CALLER
    # still reports the two causes apart. It did not: one flag carried
    # `!onStartThread || threadRouteMissing()`, so no rendering choice could tell a
    # panel from a gateway without the route.
    chat = Path(require_path("ui/chat.mjs", "§10 the chat surface")).read_text(encoding="utf-8")
    call = chat.split("RowActions, {", 1)
    assert len(call) == 2, "[§10] could not find the RowActions call site in ui/chat.mjs"
    props = call[1][: call[1].find("children:")]
    assert re.search(r"^\s*nested:", props, re.M), (
        "[§11] the RowActions call site no longer reports `nested`, so a thread "
        "panel draws a Thread button again"
    )
    folded = re.search(r"^\s*unavailable:.*onStartThread\s*\|\|", props, re.M)
    assert not folded, (
        "[§11] `unavailable` again folds the panel case together with the missing "
        f"route, which makes the two indistinguishable: {folded.group(0).strip()!r}"
    )
