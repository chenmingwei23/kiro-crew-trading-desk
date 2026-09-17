import { t } from './i18n.mjs'
/** The backend, durable preferences, and the hooks that read a session. */

import { Component, useCallback, useEffect, useRef, useState } from 'react'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { L, Notice, S } from './theme.mjs'

const APP = 'trading-desk'
const API = `/api/apps/${APP}`

/**
 * Last-resort app root, used only when `data/config.json` carries neither
 * `appRoot` nor `statePath`. ARCHITECTURE.md §1 pins the install target to this
 * gateway home.
 */
const FALLBACK_APP_ROOT = ''

export const VIEW_KEY = 'trading-desk.view'
/** `{ [memberId]: { key, at } }` — slot keys minted by a reset, with when. */
export const SLOTS_KEY = 'trading-desk.slots'
/** `{ panel: <px>, rail: <'on'|'off'> }` — the shell's shape, per browser. */
export const SHELL_KEY = 'trading-desk.shell'

/**
 * A panel width the shell can actually honour.
 *
 * Both ends matter and neither is cosmetic: below `L.panelMin` a thread title stops
 * fitting on its two lines, and above 45% of the viewport the panel stops reading as
 * a side panel. The max is computed from the CURRENT viewport, so a width stored on
 * a 3440px monitor is re-clamped rather than restored on a 1280px laptop.
 */
export function clampPanel(px, viewportW) {
  const vw = Number(viewportW) > 0 ? Number(viewportW) : L.panel * 3
  const max = Math.max(L.panelMin, Math.round(vw * L.panelMaxVw))
  const n = Math.round(Number(px))
  if (!Number.isFinite(n)) return L.panel
  return Math.min(max, Math.max(L.panelMin, n))
}

/** The stored width, honoured only if this viewport can still honour it. */
export function readShell(viewportW) {
  const raw = readStore(SHELL_KEY)
  const stored = Number(raw && raw.panel)
  return {
    panel: clampPanel(Number.isFinite(stored) && stored > 0 ? stored : L.panel, viewportW),
    rail: raw && raw.rail === 'off' ? 'off' : 'on',
  }
}

export function writeShell(next) {
  writeStore(SHELL_KEY, { panel: Math.round(next.panel), rail: next.rail === 'off' ? 'off' : 'on' })
}

export function readStore(name) {
  try {
    const raw = window.localStorage.getItem(name)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch (err) {
    return {}
  }
}

export function writeStore(name, value) {
  try {
    window.localStorage.setItem(name, JSON.stringify(value))
  } catch (err) {
    /* private mode or a full quota — the app still works, it just forgets */
  }
}

/** Outward-facing wording. No sentinel or orchestration vocabulary. */
/** Outward-facing wording. "delivered" / "stuck" read as desk jargon to a newcomer;
 *  "done" / "blocked" say the same thing in words anyone uses. */
export const DELIVERY_WORD = {
  get done() {
    return t('state_done')
  },
  get work() {
    return t('state_work')
  },
  get fail() {
    return t('state_fail')
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. One-off stylesheet
//
// Only what an inline style cannot say: a keyframe, a hover reveal, a
// placeholder colour. Every rule below addresses an element THIS file creates.
// There is deliberately nothing here that reaches into another component's DOM:
// four rounds of overriding the host pane's message body from outside never
// converged (ARCHITECTURE.md §9), which is why the transcript is now drawn here.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Every id this app has ever injected a stylesheet under.
 *
 * The versioned filename (§9.3) means one browser window can load module 0101,
 * then 0103, then 0104 — the old modules are gone but what they PUT IN THE HEAD
 * is not. A guard that returned early when `getElementById(STYLE_ID)` found
 * anything therefore made a new module inherit an old module's rules: on the
 * reader's window every rev5 rule was missing (the hover-only action bar, the
 * reply bar's swap, the sticky date), so the action bar sat visible on every row.
 * That is a mechanism, not a one-off: any rule added after a window first loaded
 * the app would have been dropped the same way.
 *
 * So the id carries the module's own tag, and injection REMOVES every stylesheet
 * from an earlier tag before inserting. Bump MODULE_TAG with the filename.
 */

function hostModule(name) {
  if (typeof window === 'undefined') return null
  const map = window.__kirocrew_modules
  return (map && map[name]) || null
}

export const appSdk = () => hostModule('@kirocrew/app-sdk')
export const uiKit = () => hostModule('@kirocrew/ui')

// ─────────────────────────────────────────────────────────────────────────────
// 4. Data layer
// ─────────────────────────────────────────────────────────────────────────────

let _appConfig
let _appRoot

/**
 * `GET /api/apps/<app>/config` is the GATEWAY's own route and returns
 * `data/config.json`. It is registered before the app route table, so it also
 * shadows any app handler at that path — which is why the desk's own config
 * lives at `/deskconfig` (ARCHITECTURE.md §2).
 *
 * The PROMISE is cached, not the result: several callers ask for this during the
 * first render, and caching the result alone lets all of them miss the empty
 * cache and fire their own request.
 */
function getAppConfig() {
  if (!_appConfig) {
    _appConfig = fetch(`${API}/config`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
  }
  return _appConfig
}

function deriveRootFromState(statePath) {
  if (!statePath) return null
  const m = String(statePath).match(/^(.*)\/workspace\/[^/]+\/state\.json$/)
  return m ? `${m[1]}/apps/${APP}` : null
}

/**
 * The app's own install root, used to read `app.json` for the version badge.
 * `data/config.json` carries `appRoot` (ARCHITECTURE.md §1); the two fallbacks cover a
 * gateway whose heal cron has not written it yet — derive it from `statePath`,
 * then assume the install target §1 pins.
 */
export function getAppRoot() {
  if (!_appRoot) {
    _appRoot = getAppConfig().then(
      (cfg) =>
        (cfg && cfg.appRoot) ||
        deriveRootFromState(cfg && cfg.statePath) ||
        FALLBACK_APP_ROOT,
    )
  }
  return _appRoot
}

/**
 * Read a file of the HOST's, by absolute path, through the gateway's reader.
 *
 * Only `app.json` is read this way, for the version badge: it lives in the app's
 * install directory, which is outside the desk root, so the desk's own reader
 * refuses it by design. Everything the DESK produces goes through
 * `readDeskFile` instead -- see the note there.
 */
export async function readFile(path) {
  try {
    const r = await fetch(`/api/file-read?path=${encodeURIComponent(path)}`)
    return r.ok ? await r.text() : null
  } catch (err) {
    return null
  }
}

/**
 * Read one of the desk's own files, by a path relative to the desk root.
 *
 * This goes to the app's `/file`, not the gateway's `/api/file-read`, for two
 * reasons. The gateway's reader takes an ABSOLUTE path -- it only resolves a
 * relative one when asked with `resolve=1`, and then against the project
 * directory, which is not the desk root -- so a desk-relative path handed to it
 * simply is not found. And the app's own route confines what it will open to the
 * desk root, symlinks included, so a path that climbs out is refused rather than
 * read. Passing `abs_path` to the gateway instead would work and would give this
 * page the run of the filesystem, which is not a trade worth making to save a
 * line.
 */
export async function readDeskFile(path) {
  try {
    const r = await fetch(`${API}/file?path=${encodeURIComponent(path)}`)
    return r.ok ? await r.text() : null
  } catch (err) {
    return null
  }
}

export async function readJsonFile(path) {
  const txt = await readFile(path)
  if (!txt) return null
  try {
    return JSON.parse(txt)
  } catch (err) {
    return null
  }
}

const ABORTED = { aborted: true }

function isAbort(err) {
  return !!err && (err.name === 'AbortError' || err.code === 20)
}

/**
 * Read the backend, or say so. There is no fixture path here (§rev7 P0).
 *
 * There used to be one, guarded by "cold start only": a route that had answered
 * once was never served `fixtures/` again. That guard cannot hold for a route
 * keyed by an id, because EVERY id is a cold start. `GET /thread/{id}` is exactly
 * that, and the failure it produced is the reason this function no longer has a
 * fixture argument: one failed read of `/thread/t-x` served
 * `fixtures/thread-detail.json`, so the panel's header showed a fabricated thread
 * ("deep dive on example-megacap") while its body -- read from the real `slot_key` the threads
 * LIST carried, down a code path with no fixtures -- showed the live conversation.
 * Header and body described two different things and neither said so.
 *
 * That is the fourth time fake data reached the screen through a fallback, and
 * every previous fix narrowed the window instead of closing it. Fixtures are now
 * for the test harness only. A failure returns an error and KEEPS whatever the
 * caller already holds, so the page shows real data with a stale marker, or an
 * honest empty state with a retry -- never something invented.
 *
 * `valid` still guards against a shadowed route answering with someone else's
 * payload, which is a different failure from an unreachable one.
 */
/**
 * What each backend route has to look like, in one place (§rev9.1).
 *
 * These used to be inline lambdas at six call sites, which made the seam between
 * this app and its backend impossible to test: a route could change shape and only
 * a person clicking that one page would find out. `/thread/{id}` drifted that way
 * once (rev6 dropped `entries` for `slot_key` and every response was rejected as
 * the wrong shape), and a reviewer hit the same class again on the config page.
 *
 * Named here, they can be run against the REAL backend's payload in a test -- which
 * is what dev/contract.mjs does. A predicate checks the ONE field the page cannot
 * draw without; checking more would red on a backend that legitimately grew a field.
 */
export const SHAPE = {
  org: (d) => !!d && Array.isArray(d.members),
  threads: (d) => !!d && Array.isArray(d.threads),
  // Either shape: rev6's clone session, or the older boundary timeline.
  thread: (d) => !!d && (typeof d.slot_key === 'string' || Array.isArray(d.entries)),
  deskconfig: (d) => !!d && d.books !== undefined,
  run: (d) => !!d && d.chain !== undefined,
  artifacts: (d) => !!d && d.tree !== undefined,
}

export async function load(route, valid, signal) {
  let failure = ''
  try {
    const r = await fetch(API + route, { headers: { Accept: 'application/json' }, signal })
    if (r.ok) {
      const data = await r.json()
      if (!valid || valid(data)) return { data, source: 'live' }
      // Kept for the tooltip and the console, never for the screen: "the data
      // shape is wrong" tells a reader nothing they can act on, and it is a
      // sentence about our code, not about their desk.
      failure = `unexpected payload shape for ${String(route).split('?')[0]}`
    } else if (r.status === 404) {
      // The gateway's Route Registry answers an unregistered path this way, which
      // is the one failure that means "this build has no such endpoint" rather
      // than "the endpoint is having a bad moment". Worth separating because the
      // remedy is different, but it is still not a licence to draw a fixture.
      failure = `HTTP 404 — no ${String(route).split('?')[0]} route on this backend`
    } else {
      failure = `HTTP ${r.status}`
    }
  } catch (err) {
    // A page switch aborts its in-flight request. That is not a failure, and must
    // never be mistaken for one.
    if (isAbort(err) || (signal && signal.aborted)) return ABORTED
    failure = String((err && err.message) || err)
  }
  // What reaches the screen is one plain sentence; `detail` carries the technical
  // reason for the tooltip and the console (§rev9.1: no "data shape" wording on screen).
  return { error: t('read_failed_hint'), detail: failure, keepData: true }
}

/**
 * Does this slot exist in the gateway yet?
 *
 * A bound key is not a live session: a reset writes the binding, and the session
 * itself is created by the first message. `GET /api/chat/slots/{key}` is read-only
 * and answers 404 for a key with no slot, which is the only way to tell the two
 * apart — `/org` reports the binding, not its existence.
 */
async function slotExists(key) {
  try {
    const r = await fetch(`/api/chat/slots/${encodeURIComponent(key)}`, {
      headers: { Accept: 'application/json' },
    })
    return r.ok
  } catch (err) {
    return false
  }
}

/** Keys we have already tried to create, so a retry loop cannot POST repeatedly. */
const provisioned = new Set()

/**
 * Create the session behind a bound key, with the member's agent.
 *
 * `POST /api/chat/slots` takes the key as `name` and binds `agent` at creation.
 * Verified against a live gateway: reset mints a key, a GET on it answers 404,
 * this call answers 200, and the GET then returns an empty transcript.
 *
 * Creating it up front is what keeps the transcript read from 404ing. ChatEmbed
 * reports a failed read as "couldn't load this session's messages" with a retry,
 * which is the right message for an unreachable transcript and the wrong one for
 * a session that simply has no messages yet.
 *
 * Only ever called with an agent: creating the session without one would bind the
 * default agent, which is exactly what the member's tada-* binding must not lose.
 */
async function provisionSlot(key, agent) {
  if (!agent || provisioned.has(key)) return
  provisioned.add(key)
  try {
    await fetch('/api/chat/slots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: key, agent }),
    })
  } catch (err) {
    /* the probe below decides; a failed create just leaves it uncreated */
  }
}

/**
 * The transcript itself (ARCHITECTURE.md §9.1).
 *
 * `GET /api/chat/slots/{key}?limit=N` is the gateway's own bounded read — the
 * same call the host's embed makes, on the same origin with the same session
 * cookie, so no proxy through the app backend is needed. `app.json` already
 * grants `/api/chat/*`.
 *
 * A 404 is NOT a failure here: a bound key whose session has not been created
 * yet has no transcript to read. It is reported as an empty one, because the
 * message a reader deserves for that is "no messages yet" and not "couldn't load
 * this session" (the P0 that closed rev3-fix2).
 */
async function fetchTranscript(key, limit, signal) {
  try {
    const r = await fetch(
      `/api/chat/slots/${encodeURIComponent(key)}?limit=${limit}`,
      { headers: { Accept: 'application/json' }, signal },
    )
    if (r.status === 404) return { messages: [], running: false, missing: true }
    if (!r.ok) return { error: t('read_conv_http', { status: r.status }) }
    const data = await r.json()
    return {
      messages: Array.isArray(data && data.messages) ? data.messages : [],
      running: !!(data && data.running),
      hasMore: !!(data && data.has_more),
    }
  } catch (err) {
    if (isAbort(err) || (signal && signal.aborted)) return ABORTED
    return { error: t('read_conv_err', { detail: String((err && err.message) || err) }) }
  }
}

/**
 * Send one message into a member's session.
 *
 * `POST /api/chat` answers two different ways, and both are success:
 *  - idle slot: the turn starts and the body is an SSE stream. Nothing here
 *    consumes it (the poll is what renders the reply), but it is drained in the
 *    background so the response is not left half-read.
 *  - running slot: the gateway queues the text and answers JSON immediately with
 *    `queued: true`. An app-authenticated send is deliberately never a mid-turn
 *    steer — the handler fails closed to the queue — which is what makes typing
 *    while the agent works safe rather than a second concurrent turn.
 */
export async function sendToSlot(key, agent, text) {
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, slot: key, agent: agent || '' }),
    })
    const ct = String(r.headers.get('content-type') || '')
    if (ct.includes('application/json')) {
      const data = await r.json().catch(() => null)
      if (!r.ok) return { error: (data && data.error) || t('send_failed_http', { status: r.status }) }
      return { queued: !!(data && data.queued) }
    }
    if (!r.ok) return { error: t('send_failed_http', { status: r.status }) }
    if (r.body && typeof r.text === 'function') r.text().catch(() => {})
    return { queued: false }
  } catch (err) {
    return { error: String((err && err.message) || err) }
  }
}

export async function postJson(route, body) {
  const r = await fetch(API + route, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => null)
  return { ok: r.ok, status: r.status, data }
}

/**
 * The gateway's Route Registry answers an UNREGISTERED path under
 * `/api/apps/<app>/` with exactly this body. The desk's own handler also answers
 * 404 — for an unknown member id — so the message is what separates "the backend
 * has not shipped this route yet" from a real, reportable error.
 */
const ROUTE_MISSING_ERROR = 'not found'

/**
 * `POST /member/{id}/reset` — hand the member a brand new session and return its
 * key (ARCHITECTURE.md §2). The old session is deliberately left alone as history,
 * and the new slot is created lazily by the embed's first message.
 */
/**
 * `POST /thread` — open a thread on a message that does not have one (§rev7 B).
 *
 * Slack lets you start a thread on ANY message, so the row action is always live;
 * a greyed-out button was the wrong reading of "no thread here yet". The anchor is
 * the identity ruling from rev5.1: `main_msg` is the gateway-minted `meta.mid`
 * and `ts` is the message's own stamp, sent verbatim.
 *
 * `text` is only sent when the composer holds a draft — that is Slack's "reply in
 * thread" (the user's own words start the thread). With an empty composer the
 * backend gets the anchor and nothing else, so the seed is its decision, not a
 * sentence this UI invented on the member's behalf.
 */
export async function createThread(memberId, anchor, text) {
  try {
    const body = { member_id: memberId, anchor }
    if (text) body.text = text
    const { ok, status, data } = await postJson('/thread', body)
    const message = (data && data.error) || ''
    if (status === 404 && (!message || message === ROUTE_MISSING_ERROR)) return { missing: true }
    if (!ok) return { error: message || t('thread_failed_http', { status }) }
    const id = (data && (data.id || (data.thread && data.thread.id))) || ''
    if (!id) return { error: t('thread_missing_id') }
    return { id }
  } catch (err) {
    if (isAbort(err)) return { error: '' }
    return { error: String((err && err.message) || err) }
  }
}

/**
 * Whether `POST /thread` is known to be absent from this gateway's build.
 *
 * One refusal teaches the whole surface: every later row shows the explanation in
 * its tooltip straight away instead of each one having to fail for itself. It is
 * module-level rather than per-component because the route's absence is a fact
 * about the backend, not about a row — and it is deliberately NOT probed on mount,
 * which would spend a request per session to learn something the first click
 * learns for free.
 */
let _threadRouteMissing = false

/** Whether the gateway has already refused `POST /thread`. */
export const threadRouteMissing = () => _threadRouteMissing

/**
 * Remember that refusal.
 *
 * An accessor pair rather than an exported `let`: rev9 split this file out of the
 * page that sets the flag, and an imported binding is READ-ONLY in an ES module --
 * assigning to it throws "Assignment to constant variable" at the moment the user
 * clicks the thread action, which is the one path this flag exists to make graceful.
 */
export function markThreadRouteMissing() {
  _threadRouteMissing = true
}

export async function resetMember(id) {
  try {
    const { ok, status, data } = await postJson(`/member/${encodeURIComponent(id)}/reset`, {})
    const message = (data && data.error) || ''
    if (status === 404 && (!message || message === ROUTE_MISSING_ERROR)) return { missing: true }
    if (!ok) return { error: message || t('reset_failed_http', { status }) }
    if (!data || !data.slot_key) return { error: t('reset_missing_slot') }
    return { slotKey: data.slot_key }
  } catch (err) {
    return { error: String((err && err.message) || err) }
  }
}

/** M1: wired to the save button once the config form becomes editable. */
export const configActions = {
  validate: (body) => postJson('/config/validate', body),
  apply: (body) => postJson('/config/apply', body),
}

// ─────────────────────────────────────────────────────────────────────────────
// 5. Polling hook — chained timeout, so slow responses never stack up
// ─────────────────────────────────────────────────────────────────────────────

export function useLoader(loader, deps, intervalMs) {
  const [state, setState] = useState({ data: null, error: null, detail: '', loading: true, source: '', at: 0 })
  const [nonce, setNonce] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    let alive = true
    let timer = null
    let controller = null

    async function run() {
      controller = typeof AbortController === 'function' ? new AbortController() : null
      try {
        const res = await loaderRef.current(controller && controller.signal)
        if (!alive) return
        if (res && res.aborted) return
        setState((s) => {
          if (res && res.data !== undefined && res.data !== null) {
            return {
              data: res.data,
              error: null,
              detail: '',
              loading: false,
              source: res.source || '',
              // When this payload was read, so a caller can tell it apart from
              // something that happened after it.
              at: Date.now(),
            }
          }
          // A failure after the backend has answered keeps the data AND its read
          // time: the age of what is on screen is what makes a locally minted
          // slot key comparable to it.
          if (res && res.keepData) return { ...s, loading: false, error: res.error || null, detail: res.detail || '' }
          return { data: null, error: (res && res.error) || null, detail: (res && res.detail) || '', loading: false, source: '', at: s.at }
        })
      } catch (err) {
        if (!alive || isAbort(err)) return
        setState((s) => ({ ...s, loading: false, error: t('read_failed_hint'), detail: String((err && err.message) || err) }))
      }
      if (alive && intervalMs) timer = setTimeout(run, intervalMs)
    }

    setState((s) => ({ ...s, loading: true }))
    run()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
      if (controller) controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, intervalMs, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, reload }
}

// ─────────────────────────────────────────────────────────────────────────────
// 6. Primitives
// ─────────────────────────────────────────────────────────────────────────────


/**
 * Resolve a bound key into a session that actually exists, creating it if it does
 * not, and report whether it is there yet.
 */
export function useSession(slotKey, agent) {
  const [state, setState] = useState({ key: '', exists: false })

  useEffect(() => {
    if (!slotKey) return undefined
    let alive = true
    let timer = null

    async function settle() {
      if (await slotExists(slotKey)) {
        if (alive) setState({ key: slotKey, exists: true })
        return
      }
      await provisionSlot(slotKey, agent)   // no-op once tried, or with no agent
      if (await slotExists(slotKey)) {
        if (alive) setState({ key: slotKey, exists: true })
        return
      }
      if (!alive) return
      setState({ key: slotKey, exists: false })
      timer = setTimeout(settle, 5000)
    }

    settle()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [slotKey, agent])

  return state.key === slotKey && state.exists
}

/** How often the transcript is re-read: while a turn runs, and while it does not. */
const POLL_RUNNING = 1000
const POLL_IDLE = 4000
/** Rows per read. The handler's own default; `has_more` widens it by another page. */
const CHAT_PAGE = 200

/**
 * The transcript, kept current by a chained poll (ARCHITECTURE.md §9.1 — v1 renders
 * a running turn by re-reading at a short interval rather than over a socket).
 *
 * Chained rather than an interval, so a slow read never stacks up behind itself,
 * and every in-flight read is aborted when the slot changes or the page unmounts.
 * A failed read keeps what is already on screen and reports the failure, for the
 * same reason a failed `/org` no longer falls back to fixtures: replacing real
 * data with something else is worse than showing it with a warning.
 */
export function useTranscript(slotKey) {
  const [state, setState] = useState({
    messages: [], running: false, hasMore: false, missing: false, error: null, loaded: false,
  })
  const [limit, setLimit] = useState(CHAT_PAGE)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!slotKey) {
      setState({ messages: [], running: false, hasMore: false, missing: false, error: null, loaded: false })
      return undefined
    }
    let alive = true
    let timer = null
    let controller = null

    async function run() {
      controller = typeof AbortController === 'function' ? new AbortController() : null
      const res = await fetchTranscript(slotKey, limit, controller && controller.signal)
      if (!alive) return
      if (!res.aborted) {
        setState((s) =>
          res.error
            ? { ...s, error: res.error, loaded: true }
            : {
                messages: res.messages,
                running: !!res.running,
                hasMore: !!res.hasMore,
                missing: !!res.missing,
                error: null,
                loaded: true,
              },
        )
      }
      if (alive) timer = setTimeout(run, res && res.running ? POLL_RUNNING : POLL_IDLE)
    }

    run()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
      if (controller) controller.abort()
    }
  }, [slotKey, limit, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  const widen = useCallback(() => setLimit((n) => n + CHAT_PAGE), [])
  return { ...state, refresh, widen }
}

/**
 * A render failure costs the chat view, not the desk.
 *
 * The app's own boundary is above the whole page, so without this one a bad
 * message body would take Desk, Run, Config and Logs with it. The session is
 * still reachable from the main chat window, which is what this says.
 */
export class ChatBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { broken: false }
  }

  static getDerivedStateFromError() {
    return { broken: true }
  }

  componentDidCatch(err) {
    // eslint-disable-next-line no-console
    console.error('[trading-desk] chat view failed to render:', err)
  }

  render() {
    if (!this.state.broken) return this.props.children
    return _jsx('div', {
      style: { padding: S.x4 },
      children: _jsx(Notice, {
        tone: 'warn',
        children: t('render_crash', { slotKey: this.props.slotKey }),
      }),
    })
  }
}

/**
 * Render `children`, and if they throw, render `fallback` instead.
 *
 * For a HOST component. The app borrows the dashboard's markdown renderer, which
 * is a large component maintained on the other side of an interface this app does
 * not control, and a throw inside it is not this app's failure to recover from --
 * yet without this it took the whole chat view down and left the reader an empty
 * page. So the host is attempted, and on a throw the app's own rendering takes
 * over: the reader loses tables and task boxes for that one body, not the app.
 *
 * `resetKey` is what makes the swap per-body rather than permanent. An error
 * boundary latches once tripped, so without it one message the host could not
 * render would hold every later message on the fallback for the rest of the
 * session.
 */
export class HostBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { broken: false }
  }

  static getDerivedStateFromError() {
    return { broken: true }
  }

  componentDidCatch(err) {
    // eslint-disable-next-line no-console
    console.error('[trading-desk] host component threw, using the app\'s own rendering:', err)
  }

  componentDidUpdate(prev) {
    if (this.state.broken && prev.resetKey !== this.props.resetKey) {
      this.setState({ broken: false })
    }
  }

  render() {
    return this.state.broken ? this.props.fallback : this.props.children
  }
}

/** Rows the reader has sent: what a pending placeholder is waiting to become. */
export function countSent(messages) {
  const list = Array.isArray(messages) ? messages : []
  let n = 0
  for (let i = 0; i < list.length; i += 1) {
    const role = String((list[i] && list[i].role) || '')
    if (role === 'user' || role === 'queued') n += 1
  }
  return n
}

/**
 * Selected text in the transcript, and where to float the quote button.
 *
 * Self-implemented per §9.1. The host pane carries its own selection quote, but
 * it writes into the host composer — which this view no longer has.
 */
export function useQuote(containerRef) {
  const [sel, setSel] = useState(null)

  const onMouseUp = useCallback(() => {
    const box = containerRef.current
    const s = typeof window !== 'undefined' && window.getSelection ? window.getSelection() : null
    if (!box || !s || s.isCollapsed || !s.anchorNode || !box.contains(s.anchorNode)) {
      setSel(null)
      return
    }
    const text = String(s.toString() || '').trim()
    if (!text) {
      setSel(null)
      return
    }
    let rect = null
    try {
      rect = s.getRangeAt(0).getBoundingClientRect()
    } catch (err) {
      rect = null
    }
    const outer = box.getBoundingClientRect()
    setSel({
      text,
      top: rect ? Math.max(0, rect.top - outer.top + box.scrollTop - 30) : 0,
      left: rect ? Math.max(0, rect.left - outer.left) : 0,
    })
  }, [containerRef])

  return { sel, onMouseUp, clear: useCallback(() => setSel(null), []) }
}

/** Every line of the selection becomes a quoted line, the way a reply reads. */
export function asQuote(text) {
  return `${String(text || '').split('\n').map((l) => `> ${l}`).join('\n')}\n\n`
}

export function resolveSlotKey(member, remembered, orgAt) {
  const serverKey = member && member.slot_key
  const local = remembered && remembered[member && member.id]
  if (!local || !local.key) return serverKey || null
  if (!serverKey) return local.key
  if (orgAt && local.at && orgAt < local.at) return local.key
  return serverKey
}
