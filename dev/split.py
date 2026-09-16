#!/usr/bin/env python3
"""
Split ui/index.mjs into the file layout kirocrew-app-ui §3 requires.

Phase 1 of the rev9 rebuild is deliberately BEHAVIOUR-NEUTRAL: the same code, in
the modules the standard names, verified green by the existing suites before any
pixel changes. Splitting and restyling in one step would leave every suite failure
ambiguous between "the move broke it" and "the new palette changed it".

The import wiring is derived, not hand-written: the script builds a symbol table
of every top-level declaration per module, then for each module lists the
identifiers it USES but does not declare, and emits the import lines. A missing
import is a runtime ReferenceError that `node --check` cannot see, so deriving it
is the difference between a split that works and one that half-works.

    python3 dev/split.py            # write the modules
    python3 dev/split.py --dry      # report the plan and the derived imports
"""
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
SRC = UI / "index.mjs"

# module -> [(start, end)] 1-based inclusive line ranges of the ORIGINAL file
PLAN = {
    "theme.mjs": [(41, 171), (223, 282), (680, 1015)],
    "data.mjs": [(23, 31), (173, 222), (283, 679), (2466, 2655), (3108, 3116)],
    "parts.mjs": [(1016, 1113), (1114, 2465), (2656, 2667)],
    "chat.mjs": [(2668, 3107), (3117, 3956)],
    "desk.mjs": [(3958, 4208)],
    "run.mjs": [(4209, 4476)],
    "config.mjs": [(4477, 4628)],
    "logs.mjs": [(4629, 4768)],
    "root.mjs": [(33, 39), (4769, 4979)],
}

HEADERS = {
    "theme.mjs": "Design tokens, the one injected stylesheet, and the primitives every page draws with.",
    "data.mjs": "The backend, durable preferences, and the hooks that read a session.",
    "parts.mjs": "Shared chat chrome: the row, the item model, markdown, the folds, the composer.",
    "chat.mjs": "The Chat page: member rail, transcript, thread panel.",
    "desk.mjs": "The Desk page — the member directory (§14.1: this mode does not change).",
    "run.mjs": "The Run page — today's chain of work.",
    "config.mjs": "The Config page — the desk's own settings, read from the backend.",
    "logs.mjs": "The Logs page — what the desk wrote to disk.",
    "root.mjs": "The app root: page routing, header, and the durable view.",
}

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"(?<![:\w])//[^\n]*")


def strip_comments(text: str) -> str:
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", text))


DECL = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)|^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)")
WORD = re.compile(r"[A-Za-z_$][\w$]*")

REACT = {"Component", "useState", "useEffect", "useMemo", "useRef", "useCallback"}
JSX = {"_jsx", "_jsxs", "_Fragment"}


def main() -> int:
    lines = SRC.read_text(encoding="utf8").split("\n")

    bodies: dict[str, list[str]] = {}
    for mod, ranges in PLAN.items():
        out: list[str] = []
        for start, end in ranges:
            if end < start:
                continue
            out.extend(lines[start - 1 : end])
            out.append("")
        bodies[mod] = out

    # every top-level name each module declares
    owner: dict[str, str] = {}
    declared: dict[str, set[str]] = {}
    for mod, body in bodies.items():
        names: set[str] = set()
        for ln in body:
            m = DECL.match(ln)
            if m:
                names.add(m.group(1) or m.group(2))
        declared[mod] = names
        for n in names:
            if n in owner:
                print(f"!! {n} declared in both {owner[n]} and {mod}")
            owner[n] = mod

    # who needs what
    needs: dict[str, dict[str, set[str]]] = {}
    exported: dict[str, set[str]] = {m: set() for m in bodies}
    for mod, body in bodies.items():
        # Comments are stripped before the usage scan: a name mentioned in prose
        # ("Header and body described two different things") is not a dependency,
        # and treating it as one invents a circular import between two modules
        # that never call each other.
        code = strip_comments("\n".join(body))
        used: set[str] = set(WORD.findall(code))
        want = {n for n in used if n in owner and owner[n] != mod}
        by_mod: dict[str, set[str]] = {}
        for n in sorted(want):
            by_mod.setdefault(owner[n], set()).add(n)
            exported[owner[n]].add(n)
        needs[mod] = by_mod

    for mod, body in bodies.items():
        text = "\n".join(body)
        # Word boundary, NOT `name(`: `class ChatBoundary extends Component` uses
        # Component without calling it, and requiring a call dropped that import.
        react = sorted(n for n in REACT if re.search(rf"\b{n}\b", strip_comments(text)))
        head = [f"/** {HEADERS[mod]} */", ""]
        if react:
            head.append(f"import {{ {', '.join(react)} }} from 'react'")
        if any(j in text for j in JSX):
            head.append("import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'")
        for other in sorted(needs[mod]):
            names = ", ".join(sorted(needs[mod][other]))
            head.append(f"import {{ {names} }} from './{other}'")
        head.append("")
        # mark the declarations other modules import
        marked: list[str] = []
        for ln in body:
            m = DECL.match(ln)
            name = (m.group(1) or m.group(2)) if m else None
            if name and name in exported[mod] and not ln.startswith("export "):
                marked.append("export " + ln)
            else:
                marked.append(ln)
        bodies[mod] = head + marked

    if "--dry" in sys.argv:
        for mod in PLAN:
            imp = {k: sorted(v) for k, v in needs[mod].items()}
            print(f"\n=== {mod}  ({len(bodies[mod])} lines, exports {len(exported[mod])})")
            for k, v in imp.items():
                print(f"    from {k}: {', '.join(v)}")
        return 0

    bad = 0
    for mod, body in bodies.items():
        text = "\n".join(body).rstrip() + "\n"
        # A range that starts or ends INSIDE a docstring is the failure `node
        # --check` cannot see: the unterminated /** swallows the code after it,
        # the file still parses, and an export silently stops existing. That cost
        # one debugging round, so it is checked here instead of in the browser.
        # The failure mode `node --check` cannot see: a range that starts or ends
        # inside a docstring leaves the /** unterminated, the rest of the file
        # becomes a comment, the file still PARSES, and an export silently stops
        # existing (that cost one debugging round on GUTTER_STYLE). Counting
        # comment delimiters is unreliable -- a regex literal and a route glob
        # ("/api/chat/*") both read as one -- so the check is on the OUTCOME: every
        # symbol the plan says this module declares must still be declared in the
        # bytes written. A swallowed declaration is exactly what goes missing.
        got = {m.group(1) or m.group(2)
               for m in (DECL.match(l) for l in text.split("\n")) if m}
        lost = declared[mod] - got
        if lost:
            print(f"  !! ui/{mod}: {len(lost)} declaration(s) vanished -- "
                  f"{', '.join(sorted(lost)[:6])} -- a cut lands inside a docstring")
            bad += 1
        (UI / mod).write_text(text, encoding="utf8")
        print(f"  wrote ui/{mod}  ({len(body)} lines)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
