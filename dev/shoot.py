#!/usr/bin/env python3
"""
Screenshots of every state, in both languages (kirocrew-app-ui §8).

Boots dev/harness.py, drives the real ui/ with Playwright, and writes one PNG per
state at 1440x900 plus one ultrawide frame at 3440x1200. Any console error fails
the run.

Every frame must PROVE it is the state it is named after before the PNG is kept.
This session cannot look at images, so a frame called `thread` whose panel never
opened, or an `en` frame still in Chinese, would be an invented deliverable and a
reviewer would judge the wrong screen.

Selectors are classes and `data-page`, never text: a text selector stops working
the moment the same control has a second label, which is the whole point of the
English pass.

    python3 dev/shoot.py                    # Chinese, 1440 + one 3440
    python3 dev/shoot.py --lang en          # English, suffix -en
"""
from __future__ import annotations

import argparse
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
OUT = APP / "design" / "evidence"
PORT = 8794

# A frame's claim: (selector work to do first, a predicate on the page)
CLAIMS = {
    "chat": "() => document.querySelectorAll('.td-row').length >= 2 && !!document.querySelector('.td-rail')",
    "chat-wide": "() => { const c = document.querySelector('.td-chat'); const col = document.querySelector('.td-col');"
                 " return !!c && !!col && c.getBoundingClientRect().width > 2000"
                 " && Math.round(col.getBoundingClientRect().width) <= 820 }",
    "walk-open": "() => [...document.querySelectorAll('.td-fold')].some(b => b.textContent.includes('\\u25be'))",
    # The panel must be ON SCREEN and holding its column, measured. Counting two
    # composers was not enough: the DOM had both while the panel's own box was
    # taller than the viewport with its lower half outside it, so the frame passed
    # with an empty dark strip where the panel should have been.
    "thread": """() => {
      const p = document.querySelector('.td-panel')
      if (!p) return false
      const r = p.getBoundingClientRect()
      const root = document.querySelector('.td-root').getBoundingClientRect()
      return r.width >= 360 && r.height >= root.height * 0.6 &&
        r.top >= root.top - 2 && r.bottom <= root.bottom + 2 &&
        Math.abs(r.right - root.right) <= 2 &&
        document.querySelectorAll('.td-input').length === 2
    }""",
    "desk": "() => document.body.innerText.includes('line-manager') || document.querySelectorAll('.td-row').length === 0",
    "settings": "() => document.body.innerText.includes('English') && document.body.innerText.includes('Trading Desk')",
    "settings-advanced": "() => document.body.innerText.includes('\\u25be')",
    "logs": "() => !!document.querySelector('.td-root')",
}

# The app owns exactly one viewport and scrolls INSIDE it. If the document can
# scroll, the app has outgrown the surface it painted white, and everything past
# that surface is the dashboard's dark page -- which is what a reader sees as "the
# light card ends halfway down". This catches it at scroll-top, before anyone has to
# scroll to find it, and it is the same fact in both languages.
FITS_PROBE = """() => {
  const d = document.documentElement
  const over = Math.max(d.scrollHeight - innerHeight, d.scrollWidth - innerWidth)
  const root = document.querySelector('.td-root')
  const r = root ? root.getBoundingClientRect() : null
  return {
    over,
    covers: !!r && r.height >= innerHeight - 2 && r.width >= innerWidth - 2,
    rootH: r ? Math.round(r.height) : 0,
    vh: innerHeight,
  }
}"""

# Everything the page renders must be the app's own font and a light surface: a
# host token that leaked shows up here rather than in a reviewer's eye.
LIGHT_PROBE = """() => {
  const bad = []
  const root = document.querySelector('.td-root')
  if (!root) return ['no .td-root']
  const rs = getComputedStyle(root)
  if (!/rgb\\(255, 255, 255\\)/.test(rs.backgroundColor)) bad.push('root bg ' + rs.backgroundColor)
  if (/mono/i.test(rs.fontFamily)) bad.push('root font ' + rs.fontFamily)
  const name = (el) => el.tagName.toLowerCase() +
    (el.className ? '.' + String(el.className).split(' ')[0] : '') +
    ' "' + (el.textContent || '').trim().slice(0, 18) + '"'
  let n = 0
  for (const el of root.querySelectorAll('*')) {
    if (n++ > 2000) break
    const s = getComputedStyle(el)
    // Monospace is legitimate for code and for a path or a machine label the app
    // deliberately sets in MONO. What is NOT legitimate is inheriting the host's
    // monospace --font-body, which shows up on ordinary prose.
    if (/mono/i.test(s.fontFamily) && !['PRE', 'CODE'].includes(el.tagName) &&
        !el.closest('pre, code, .td-mono, .td-code')) {
      bad.push('MONO ' + name(el))
    }
    // Alpha matters: rgba(34,34,34,.07) is a faint tint, not a dark fill. Summing
    // the channels without reading alpha reported every subtle pill as dark.
    const m = s.backgroundColor.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/)
    if (m) {
      const a = m[4] === undefined ? 1 : Number(m[4])
      const lum = Number(m[1]) + Number(m[2]) + Number(m[3])
      // Declared exceptions: a status dot, a hue avatar (the standard's photo
      // fallback), a dark primary control, and the settings check badge.
      const cls = String(el.className)
      const primary = /td-pill-dark|td-tab-on|td-dot|td-avatar|td-badge-dark/.test(cls) ||
        (el.tagName === 'BUTTON' && lum < 120)
      if (a > 0.5 && lum < 300 && !primary) bad.push('DARK ' + name(el) + ' ' + s.backgroundColor)
    }
    if (bad.length > 8) break
  }
  return bad
}"""

failed: list[str] = []

# A dark sample is anything below this luminance. The app is white with black ink;
# the only dark things on it are small (a filled tab pill, an avatar, a dark
# primary button), which is why a BAND of dark samples means a background and a
# handful of them does not.
DARK = 110
STEP = 24
BAND_SHARE = 0.55


def composited_leak(png: Path) -> list[str]:
    """
    Read the FRAME, not the DOM.

    The element-style probe cannot see a defect a human sees immediately: the app's
    white surface stops partway down the viewport and the dashboard's dark page shows
    below it. Every element such a probe inspects is correctly light -- the leak is in
    the area no element covers. Only the composited image knows that, so this samples
    the PNG on a grid and fails on a dark BAND, reporting where.
    """
    try:
        from PIL import Image
    except Exception as exc:  # a probe that cannot run must say so, not pass
        return [f"cannot read the frame: {exc}"]
    im = Image.open(png).convert("RGB")
    w, h = im.size
    px = im.load()
    xs = list(range(STEP // 2, w, STEP))
    ys = list(range(STEP // 2, h, STEP))

    def dark(x: int, y: int) -> bool:
        r, g, b = px[x, y]
        return (0.299 * r + 0.587 * g + 0.114 * b) < DARK

    out: list[str] = []
    for y in ys:
        n = sum(1 for x in xs if dark(x, y))
        if n > len(xs) * BAND_SHARE:
            out.append(f"dark row at y={y} ({n}/{len(xs)} samples)")
            if len(out) > 3:
                break
    for x in xs:
        n = sum(1 for y in ys if dark(x, y))
        if n > len(ys) * BAND_SHARE:
            out.append(f"dark column at x={x} ({n}/{len(ys)} samples)")
            if len(out) > 6:
                break
    return out


def wait_up(port: int) -> bool:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="both", choices=["zh-CN", "en", "both"])
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    langs = ["zh-CN", "en"] if args.lang == "both" else [args.lang]
    OUT.mkdir(parents=True, exist_ok=True)

    # `timeout` and Ctrl-C send SIGTERM/SIGINT, and Python does NOT unwind a `finally`
    # for a signal -- which is how a cancelled run left five harness servers holding
    # their ports for an hour. Turning the signal into an exception is what makes the
    # cleanup below actually run.
    def bail(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGINT, bail)

    from playwright.sync_api import sync_playwright

    server = subprocess.Popen(
        [sys.executable, str(APP / "dev" / "harness.py"), "--port", str(args.port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    if not wait_up(args.port):
        server.kill()
        print("MOCKUPS_FAIL — harness did not come up")
        return 1

    base = f"http://127.0.0.1:{args.port}/"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for lang, (width, height, tag) in [
                (l, v) for l in langs for v in ((1440, 900, ""), (3440, 1200, "-3440"))
            ]:
                suffix = "" if lang == "zh-CN" else "-en"
                ctx = browser.new_context(viewport={"width": width, "height": height})
                page = ctx.new_page()
                errors: list[str] = []
                # A slot that has never received a message does not exist on the
                # gateway, so probing it 404s BY DESIGN (§6). Whitelisted by URL;
                # every other console error stays fatal.
                def on_console(m, sink=errors):
                    if m.type != "error":
                        return
                    txt = m.text
                    loc = (m.location or {}).get("url", "") if hasattr(m, "location") else ""
                    if "404" in txt and ("/api/chat/slots/" in loc or "/api/chat/slots/" in txt):
                        return
                    sink.append(f"{txt} @ {loc}")

                page.on("console", on_console)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(base)
                page.evaluate("() => localStorage.clear()")
                page.evaluate("(l) => localStorage.setItem('trading-desk.lang', l)", lang)
                page.reload()
                page.wait_for_selector(".td-root", timeout=20000)
                # The reply bars arrive on the threads poll, which lands after the
                # transcript. A fixed sleep raced it: the run silently produced no
                # thread frame at all, because `.td-reply` was not there yet when
                # the script looked. Wait for the thing, not for a duration.
                try:
                    page.wait_for_selector(".td-reply", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(800)

                def shot(name: str, claim_key: str | None = None) -> None:
                    file = OUT / f"rev9-{name}{suffix}{tag}.png"
                    if claim_key and claim_key in CLAIMS:
                        if not page.evaluate(CLAIMS[claim_key]):
                            failed.append(f"{lang}/{width}/{name}: did not prove state `{claim_key}`")
                            print(f"  !! {name}: claim `{claim_key}` false")
                    fits = page.evaluate(FITS_PROBE)
                    if fits["over"] > 2 or not fits["covers"]:
                        failed.append(
                            f"{width}/{name}: the app outgrew its viewport "
                            f"(overflow {fits['over']}px, root {fits['rootH']} of {fits['vh']}) "
                            "-- the dashboard's dark page shows past the white surface"
                        )
                        print(f"  !! {name}: overflow {fits['over']}px root {fits['rootH']}/{fits['vh']}")
                    leaks = page.evaluate(LIGHT_PROBE)
                    if leaks:
                        failed.append(f"{lang}/{width}/{name}: host theme leaked -- {leaks[:3]}")
                        print(f"  !! {name}: {leaks[:3]}")
                    page.screenshot(path=str(file))
                    leak = composited_leak(file)
                    if leak:
                        failed.append(f"{lang}/{width}/{name}: dark background in the frame -- {leak[:3]}")
                        print(f"  !! {name}: {leak[:3]}")
                    print(f"  {file}")

                if tag:
                    # The ultrawide frame exists for ONE question: does the
                    # conversation fill the pane while the text stays readable?
                    shot("chat", "chat-wide")
                    ctx.close()
                    continue

                shot("chat", "chat")
                fold = page.locator(".td-fold").first
                if fold.count():
                    fold.click()
                    page.wait_for_timeout(400)
                    shot("walk-open", "walk-open")
                # A frame this script promises to deliver must be delivered or the
                # run fails. Skipping it quietly is how a pass came back with no
                # thread frame in the set at all.
                reply = page.locator(".td-reply").first
                if not reply.count():
                    failed.append(f"{width}/thread: no reply bar on screen, so the panel could not be opened")
                else:
                    reply.click()
                    page.wait_for_timeout(900)
                    shot("thread", "thread")
                    reply.click()
                    page.wait_for_timeout(300)
                for pid, claim in (("desk", "desk"), ("run", None), ("logs", "logs"), ("config", None)):
                    tabb = page.locator(f'[data-page="{pid}"]')
                    if tabb.count():
                        tabb.click()
                        page.wait_for_timeout(900)
                        shot(pid, claim)
                # Settings, and Advanced opened -- the ops disclosure has to be
                # photographed in both states or nobody reviews the one that matters.
                page.locator('button[aria-label]').last.click()
                page.wait_for_timeout(600)
                shot("settings")
                adv = page.locator("button.td-pill").filter(has_text="▸")
                if adv.count():
                    adv.first.click()
                    page.wait_for_timeout(300)
                    shot("settings-advanced", "settings-advanced")
                if errors:
                    failed.append(f"{lang}/{width}: console errors -- {errors[:2]}")
                ctx.close()
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    if failed:
        print(f"\nSHOOT_FAIL — {len(failed)} problem(s):")
        for f in failed:
            print("  " + f)
        return 1
    print(f"\nSHOOT_PASS — every frame proved its state, in {' + '.join(langs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
