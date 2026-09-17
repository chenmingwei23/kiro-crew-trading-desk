#!/usr/bin/env python3
"""
Offline harness for the Trading Desk UI (kirocrew-app-ui §8).

Serves `ui/` behind an import map, a stubbed `@kirocrew/app-sdk` on
`window.__kirocrew_modules`, and the app's API routes answered from the REAL desk:
the roster comes out of `backend/org.py`, the conversations out of the gateway's own
session files, the reports out of the directories the crews write to. A harness fed
invented records teaches nothing about a page whose whole job is showing real work.

The page's `:root` deliberately carries the DASHBOARD's dark tokens and a monospace
`--font-body`. That is not decoration: it reproduces the host the app is embedded
in, so anything of ours that still reads a host token shows up as a dark patch on a
white page instead of hiding until a reader finds it.

    python3 dev/harness.py            # http://127.0.0.1:8791
    python3 dev/harness.py --port N
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
UI = APP / "ui"
DESK = Path(os.environ.get("DESK_ROOT") or Path.home() / "trading-desk")
SESSIONS = Path.home() / ".kirocrew" / "sessions"

sys.path.insert(0, str(APP))

PROC_ROLES = {"tool", "tool_call", "tool_result", "thinking"}


# ── real data ────────────────────────────────────────────────────────────────

def roster() -> list[dict]:
    """The member list the Desk page draws, from the backend's own source."""
    from backend import org  # imported lazily so --help works without the desk

    return org.roster(DESK)


def read_session(path: Path) -> dict:
    """One session file as the gateway's slot-detail payload."""
    msgs: list[dict] = []
    meta: dict = {}
    for line in path.read_text(encoding="utf8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("_type") == "metadata":
            meta = row
            continue
        if not row.get("role"):
            continue
        msgs.append({k: row[k] for k in ("role", "content", "cls", "ts", "meta") if k in row})
    return {
        "messages": msgs,
        "total": len(msgs),
        "running": False,
        "title": meta.get("title", ""),
        "agent": str(meta.get("agent") or ""),
        "created_at": str(meta.get("created_at") or ""),
    }


_SESSION_CACHE: dict[str, Path] | None = None
_THREAD_CACHE: dict[str, dict] = {}


def head_meta(path: Path) -> dict:
    """Just the session's metadata line."""
    try:
        with path.open(encoding="utf8", errors="replace") as f:
            row = json.loads(f.readline() or "{}")
        return row if isinstance(row, dict) and row.get("_type") == "metadata" else {}
    except Exception:
        return {}


def within_hours(iso: str, hours: float) -> bool:
    try:
        born = datetime.fromisoformat(iso)
    except Exception:
        return False
    return (datetime.now(tz=timezone.utc) - born).total_seconds() <= hours * 3600


def sessions_by_key() -> dict[str, Path]:
    """Cached: the gateway keeps ~1,200 session files and parsing them per request
    made `/threads` slow enough that the page's first poll had not landed by the
    time a screenshot script looked for a reply bar -- a race that silently produced
    a run with no thread frame in it."""
    global _SESSION_CACHE
    if _SESSION_CACHE is not None:
        return _SESSION_CACHE
    out: dict[str, Path] = {}
    if not SESSIONS.is_dir():
        return out
    for p in SESSIONS.glob("dashboard_*.jsonl"):
        out[p.name[len("dashboard_"):-len(".jsonl")]] = p
    _SESSION_CACHE = out
    return out


def newest_desk_session() -> tuple[str, Path] | tuple[None, None]:
    """The fund manager's most recent conversation — the one the page opens on."""
    best: tuple[float, str, Path] | None = None
    for key, p in sessions_by_key().items():
        if not key.startswith("td-fund-"):
            continue
        stamp = p.stat().st_mtime
        if best is None or stamp > best[0]:
            best = (stamp, key, p)
    return (best[1], best[2]) if best else (None, None)


def threads_for(member: str) -> dict:
    """
    Threads derived from the real thread sessions on disk.

    Anchors are matched to the owning conversation the way the backend does — the
    mid of the message that opened the thread — by finding the receipt line that
    names the thread's own key. Nothing is invented: a thread whose receipt cannot
    be found comes back with `anchor: null`, which is the state the header entry
    exists for and the state the live desk is actually in.
    """
    if member in _THREAD_CACHE:
        return _THREAD_CACHE[member]
    keys = sessions_by_key()
    fund_key, fund_path = newest_desk_session()
    owner = read_session(fund_path) if fund_path else {"messages": []}

    threads = []
    for key, path in sorted(keys.items()):
        if not re.match(r"^chat-\d+-\d+$", key):
            continue
        # Decide from the METADATA LINE before parsing the file. The gateway keeps
        # ~1,200 sessions and some hold 2,000 messages; reading them all to then
        # discard 99% took long enough that the page's first /threads poll had not
        # answered when a screenshot script looked for a reply bar.
        head = head_meta(path)
        if not str(head.get("agent") or "").startswith("tada-"):
            continue
        if not within_hours(str(head.get("created_at") or ""), 36):
            continue
        detail = read_session(path)
        if not detail["messages"]:
            continue
        # The desk's OWN threads only. Every dashboard chat lives in the same
        # directory, so without this the page listed 143 "threads" -- other
        # people's work, which is worse than listing none.
        if not detail["agent"].startswith("tada-"):
            continue
        # Today's work, by when the session was OPENED. Modification time is not a
        # proxy for it: a 09-09 pod session that anything touched since looks new
        # and is not a thread of this conversation at all.
        try:
            born = datetime.fromisoformat(detail["created_at"])
        except Exception:
            continue
        if (datetime.now(tz=timezone.utc) - born).total_seconds() > 36 * 3600:
            continue
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        anchor = None
        for m in owner["messages"]:
            if m.get("role") != "assistant" or key not in str(m.get("content", "")):
                continue
            # The bar hangs under the QUESTION, not under the receipt (§13.2), so
            # walk back to the reader's own message.
            prior = [x for x in owner["messages"] if x.get("ts", "") < m.get("ts", "") and x.get("role") == "user"]
            src = prior[-1] if prior else m
            anchor = {
                "main_msg": (src.get("meta") or {}).get("mid", ""),
                "ts": src.get("ts", ""),
                "preview": str(src.get("content", ""))[:80],
            }
            break
        actors = sorted({str(m.get("role")) for m in detail["messages"]})
        threads.append({
            "id": f"th-{key}",
            "title": detail["title"] or key,
            "state": "running",
            "state_msg": "in progress",
            "slot_key": key,
            "kind": "thread" if detail["agent"] == "tada-fund-manager" else "dispatch",
            "agent": detail["agent"],
            "participants": ["fund", "macro", "risk"][: max(2, len(actors))],
            "entry_count": len([m for m in detail["messages"] if m.get("role") in ("user", "assistant")]),
            "last_ts": stamp.strftime("%H:%M"),
            "last_msg": str(detail["messages"][-1].get("content", ""))[:60],
            "anchor": anchor,
        })
    _THREAD_CACHE[member] = {"threads": threads, "member": member}
    return _THREAD_CACHE[member]


def latest_in(rel: str) -> str:
    d = DESK / rel
    if not d.is_dir():
        return ""
    files = sorted(p.name for p in d.glob("*.md"))
    return files[-1] if files else ""


def org_payload() -> dict:
    members = []
    fund_key, _ = newest_desk_session()
    for m in roster():
        row = dict(m)
        row["state"] = "working" if m["id"] == "fund" else ("done" if m["id"] == "macro" else "idle")
        row["state_msg"] = {"fund": "organizing today's research", "macro": "today's brief delivered"}.get(m["id"], "")
        row["slot_key"] = fund_key if m["id"] == "fund" else ""
        row["slot_exists"] = bool(row["slot_key"])
        row["outputs"] = [
            {"label": s.get("label", ""), "name": latest_in(s.get("dir", "")), "path": f"{s.get('dir','')}/{latest_in(s.get('dir',''))}"}
            for s in m.get("output_sources", [])
            if latest_in(s.get("dir", ""))
        ]
        members.append(row)
    profiles = {m["id"]: {"agent": m.get("agent", "")} for m in members}
    return {"members": members, "profiles": profiles, "pods": 9, "date": datetime.now().strftime("%Y-%m-%d")}


# ── the page ─────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Trading Desk · harness</title>
<script type="importmap">
{"imports": {
  "react": "https://esm.sh/react@18.3.1",
  "react/jsx-runtime": "https://esm.sh/react@18.3.1/jsx-runtime",
  "react-dom/client": "https://esm.sh/react-dom@18.3.1/client"
}}
</script>
<style>
  /* The DASHBOARD's tokens, dark, with a monospace body -- the host as it really
     is. Anything of ours that still reads one of these shows up immediately. */
  :root {
    --bg:#0f1115; --card:#181b22; --panel:#181b22; --border:#27272a; --text:#e4e4e7;
    --muted:#8b8b93; --accent:#7c3aed; --accent-fg:#fff; --ok:#22c55e; --warn:#eab308;
    --danger:#ef4444; --font-body: ui-monospace, Menlo, monospace;
  }
  html, body { margin:0; padding:0; height:100%; background:var(--bg); color:var(--text);
    font-family: var(--font-body); }
  #root { position:absolute; inset:0; display:flex; }
  #root > * { flex:1; min-width:0; }
</style>
</head><body>
<div id="root"></div>
<script type="module">
  import { createElement } from 'react'
  import { createRoot } from 'react-dom/client'
  // The host's module map. ChatEmbed is deliberately NOT provided: this app draws
  // its own transcript (§14.1), so a stub for it would test nothing real.
  window.__kirocrew_modules = { '@kirocrew/app-sdk': {
    parseOptions: null,
    appConfig: { appRoot: '__APP_ROOT__' },
  } }
  const mod = await import('./ui/index.mjs?v=' + Date.now())
  createRoot(document.getElementById('root')).render(createElement(mod.default))
</script>
</body></html>
"""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        # A send is accepted and does nothing: this harness is for looking at the
        # page, not for driving the desk.
        self._json({"queued": True})

    def _param(self, name: str) -> str:
        if "?" not in self.path:
            return ""
        from urllib.parse import parse_qs, urlparse

        return (parse_qs(urlparse(self.path).query).get(name) or [""])[0]

    def _date(self) -> str | None:
        return self._param("date") or None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        api = "/api/apps/trading-desk"

        if path in ("/", "/index.html"):
            root = str(APP)
            body = PAGE.replace("__APP_ROOT__", root).encode("utf8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/api/chat/slots/"):
            key = path[len("/api/chat/slots/"):]
            found = sessions_by_key().get(key)
            if not found:
                return self._json({"error": "not found"}, 404)
            return self._json(read_session(found))

        if path == f"{api}/org":
            return self._json(org_payload())
        if path == f"{api}/threads":
            member = ""
            if "?" in self.path:
                for pair in self.path.split("?", 1)[1].split("&"):
                    if pair.startswith("member="):
                        member = pair.split("=", 1)[1]
            return self._json(threads_for(member))
        if path.startswith(f"{api}/thread/"):
            tid = path[len(f"{api}/thread/"):]
            for t in threads_for("fund")["threads"]:
                if t["id"] == tid:
                    return self._json(t)
            return self._json({"error": "not found"}, 404)
        if path == f"{api}/config":
            return self._json({"appRoot": str(APP)})
        if path == f"{api}/deskconfig":
            # The REAL module, not a shape I invented. The invented one shipped a
            # phantom P0: the page said it could not read the config while the app's
            # own predicate matched the backend perfectly -- the harness was the
            # thing that was wrong, which is the worst way for a verification loop
            # to fail, because it sends someone hunting a bug that is not there.
            from backend import configio

            return self._json(configio.read(DESK))
        if path == f"{api}/run":
            from backend import runview

            try:
                import asyncio as _aio

                # runview.build is a coroutine (it shells out to the desk's own
                # derive script), so it is awaited rather than returned as a promise
                # object -- serialising the coroutine would have been another
                # invented shape.
                return self._json(
                    _aio.run(runview.build(DESK, self._date() or datetime.now().strftime("%Y-%m-%d")))
                )
            except Exception as exc:  # a real failure is reported, never papered over
                return self._json({"error": f"runview: {exc}"}, 500)
        if path == f"{api}/artifacts":
            from backend import artifacts as artifacts_mod

            return self._json(artifacts_mod.build(DESK, self._date()))
        if path == "/api/file-read":
            # RAW TEXT, which is what the gateway's own route returns
            # (dashboard/handlers/files.py: `web.Response(text=content, ...)`). An
            # earlier version of this handler wrapped it in {"text": ...}: the app
            # then JSON-parsed an envelope instead of app.json and the header showed
            # `v?` forever. Same class of harness lie as the config page's.
            target = self._param("path")
            f = Path(target)
            if not f.is_file():
                return self._json({"error": "not found"}, 404)
            body = f.read_text(encoding="utf8", errors="replace").encode("utf8")
            self.send_response(200)
            kind = "application/json" if f.suffix == ".json" else "text/plain"
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith(f"{api}/file"):
            # The app's OWN reader: a DESK-RELATIVE path, confined to the desk
            # root by `artifacts.read_file`, answered as RAW TEXT with the
            # resolved path in a header -- exactly what `backend/routes.py`
            # `get_file` returns. This used to answer `{"text": "", "path": ""}`
            # for every request, which is the worst kind of harness lie: the
            # Output page rendered an empty file instead of an error, so a
            # reader that could not work still looked like it did.
            from backend import artifacts as artifacts_mod

            try:
                text, relative = artifacts_mod.read_file(DESK, self._param("path"))
            except FileNotFoundError as exc:
                return self._json({"error": f"not found: {exc}"}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 413)
            body = text.encode("utf8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Desk-Path", relative)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        # Anything else is a static file out of the app directory.
        if path.startswith("/ui/") or path.endswith(".svg"):
            target = APP / path.lstrip("/")
            if target.is_file():
                data = target.read_bytes()
                self.send_response(200)
                kind = "image/svg+xml" if target.suffix == ".svg" else "text/javascript"
                self.send_header("Content-Type", f"{kind}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
        self.send_error(404)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--once", action="store_true", help="serve one request and exit (smoke)")
    args = ap.parse_args()
    # `--port 0` lets the OS pick, and the chosen port is printed. A caller that
    # probes for a free port and then hands the number over loses the race to
    # TIME_WAIT; letting the server bind first and say where cannot lose it.
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = srv.server_address[1]
    print(f"harness on http://127.0.0.1:{port}  (app {APP}, desk {DESK})", flush=True)
    if args.once:
        srv.handle_request()
        return 0
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
