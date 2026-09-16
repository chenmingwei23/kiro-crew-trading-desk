import { t } from './i18n.mjs'
/** Design tokens, the one injected stylesheet, and the primitives every page draws with. */

import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'

/**
 * The palette (kirocrew-app-ui §2).
 *
 * Literal values, not `var(--…)` with a dark fallback. The dashboard's own tokens
 * used to be read here so a custom theme kept working, and that is precisely the
 * anti-pattern the standard names: the surface then paints whatever palette the
 * reader's dashboard is set to — dark cards, its accent on rails, a monospace body
 * in CLI mode — which is how a white app ends up half light and half dark. This
 * app's page is white and sans, and it says so itself.
 *
 * White page, black ink, one accent. `brand` appears in the wordmark and nowhere
 * else; a primary action is a DARK pill, which is why `accent` is #222 and not a
 * colour. `ok` / `warn` are status only, never decoration.
 */
export const C = {
  bg: '#FFFFFF',
  bg2: '#F7F7F7',
  card: '#F7F7F7',
  border: '#DDDDDD',
  line2: '#EBEBEB',
  borderStrong: '#222222',
  text: '#222222',
  muted: '#717171',
  mutedStrong: '#484848',
  brand: '#FF385C',
  brandHover: '#E31C5F',
  accent: '#222222',
  accentFg: '#FFFFFF',
  accentSubtle: 'rgba(34, 34, 34, 0.07)',
  ok: '#008A05',
  okFg: '#FFFFFF',
  okSubtle: 'rgba(0, 138, 5, 0.10)',
  warn: '#C13515',
  warnFg: '#FFFFFF',
  warnSubtle: 'rgba(193, 53, 21, 0.08)',
  danger: '#C13515',
  dangerSubtle: 'rgba(193, 53, 21, 0.08)',
  /** A status dot with nothing to report. Grey, not muted text grey: it sits on
   *  white next to green and red and has to read as "neither". */
  dotIdle: '#C9C9C9',
  /** The faint surface a row takes under the pointer. */
  hover: '#FAFAFA',
}

/** The app's own typeface, including inside anything it embeds (§2). */
export const FONT =
  // §15.1: Slack's own first family, then a CJK sans that actually has the glyphs.
  // Lato is taken from the system -- nothing is fetched -- so on a box without it the
  // chain has to hold on its own, which is what the harness checks rather than
  // assumes. Lato covers no CJK at all, so the second family is doing real work on
  // every Chinese character even where Lato IS installed.
  'Lato, "Noto Sans SC", -apple-system, "PingFang SC", sans-serif'

export const MONO = "ui-monospace, 'SF Mono', 'Cascadia Code', Menlo, Consolas, monospace"

// ─────────────────────────────────────────────────────────────────────────────
// 1a. The grid  (§rev7)
//
// Every length on this surface comes from here. It exists because the surface
// measurably did not have one: a census of the rendered DOM counted 216 off-grid
// spacing values (1/2/3/5/6/10/14/18px all in use at once), ten distinct font
// sizes between 8 and 18px, and sixteen line-heights — which is what "ui 下面都
// 没对齐" looks like from the inside. Nothing lines up with anything when each
// element picked its own number.
//
// SPACING is a 4px grid. Off-grid values were snapped by one stated rule —
// nearest multiple of 4, ties toward the denser value — rather than re-judged
// site by site, so the result is reproducible and reviewable: the census diff
// shows every element that moved and by how much. Two values sit outside the
// grid on purpose: `hair`, which is a 1px border and never a gap, and `half`,
// the single 2px step for a nudge that keeps two things on one baseline.
//
// TYPE is a six-step ramp. Slack's own hierarchy is three sizes doing nearly all
// the work (body, meta, micro); the extra steps here are the product title and
// the profile name. A seventh size is a bug, not a design.
// ─────────────────────────────────────────────────────────────────────────────

/** The 4px spacing grid. `hair` is a border; `half` is the one 2px step. */
export const S = {
  hair: 1,
  half: 2,
  x1: 4,
  x2: 8,
  x3: 12,
  x4: 16,
  x5: 20,
  x6: 24,
  x8: 32,
  x12: 48,
}

/** The type ramp. `micro` is the smallest size CJK stays legible at. */
export const F = {
  micro: 11,
  meta: 12,
  quiet: 13,
  body: 15,
  title: 17,
  head: 18,
  h2: 22,
  hero: 24,
  display: 34,
}

/** Line heights. `body` is §10.2's 1.46; `prose` is for a wrapped paragraph. */
export const LH = { flat: 1, tight: 1.3, body: 1.46, prose: 1.6 }

/**
 * Font weights.
 *
 * `name` is the author line. An earlier revision set it to 700, reasoning that 900 at
 * 15px on white reads as shouting -- and that reasoning was wrong about the thing
 * being copied: Slack's own author line IS 900, and this is a replica. The weight is
 * what separates a group's first row from its continuations at this density, so it
 * earns the contrast.
 */
export const W = { normal: 400, medium: 600, bold: 700, name: 900 }

/**
 * Corner radii — ONE family (§2): pills, 12px tiles and inputs, 16px cards and
 * floats. The old scale started at 4px and 6px, which is the "no 4px/6px corners"
 * the standard rules out; nothing on the surface has a hard corner any more.
 */
export const R = { sm: 8, md: 10, lg: 12, xl: 16, pill: 9999 }

/**
 * Layout lengths — the ones that are a decision about the page, not a gap.
 * `rail` and `panel` are the two side columns and `measure` caps the text column,
 * all three read off design/mockups/option-a.html, which is this page's baseline:
 * 260 / 820 / 380 at 1440. `measure` was 1200, which at 1440 with two side columns
 * meant the text never actually reached its cap; 820 is a line a person can track.
 */
export const L = {
  rail: 260,
  panel: 380,
  /** The panel is draggable (§rev9.1): narrower than this and a thread title
   *  plus its 2-line clamp stops fitting, so the panel stops being readable. */
  panelMin: 320,
  /** Past this the panel is no longer a side panel -- it is a second
   *  conversation competing with the one being read. */
  panelMaxVw: 0.45,
  measure: 820,
  avatar: 36,
  avatarSm: 24,
  avatarLg: 112,
  glyphBtn: 24,
  chrome: 220,
  minChat: 480,
  menu: 360,
  menuMin: 260,
  field: 380,
  quote: 560,
  modal: 640,
  stat: 132,
  label: 104,
  keyCol: 160,
  sidePane: 280,
  scrollCap: 210,
  /** The sticky top bar (§4). */
  bar: 72,
  /** A pill's two heights, and the round icon button. */
  pill: 40,
  pillSm: 34,
}

/** Depth only for things that float (§2). Cards are near-borderless instead. */
export const SHADOW = {
  pop: '0 1px 2px rgba(0,0,0,0.08)',
  menu: '0 1px 2px rgba(0,0,0,0.08), 0 6px 20px rgba(0,0,0,0.12)',
}

/** A shorthand length list: `sp(S.half, S.x2)` -> `'2px 8px'`. */
export const sp = (...v) => v.map((n) => (typeof n === 'number' && n !== 0 ? `${n}px` : String(n))).join(' ')

/** A 1px border in `color` — the only border width on the surface. */
export const hair = (color) => `${S.hair}px solid ${color}`

/** A 2px rule, for the one place a border carries emphasis (a quote's edge). */
export const rule = (color) => `${S.half}px solid ${color}`

/** Which ramp step an avatar's letter takes, by box size. */
const avatarType = (px) => (px >= L.avatarLg ? F.hero : px >= L.avatar ? F.quiet : F.micro)

// ─────────────────────────────────────────────────────────────────────────────
// 1b. Durable state
//
// The app UI is unmounted whenever the user leaves the page, so anything held
// only in React state is gone on the way back — which is why the member you were
// chatting with, and a session you had just started, both have to live on disk.
// ─────────────────────────────────────────────────────────────────────────────


const STYLE_PREFIXES = ['td-app-style', 'td-app-keyframes']
const MODULE_TAG = '0202'
const STYLE_ID = `${STYLE_PREFIXES[0]}-${MODULE_TAG}`

/**
 * The app's one stylesheet (§3).
 *
 * Everything is scoped under `.td-root` so nothing leaks into the dashboard and
 * nothing from the dashboard is assumed — including `color-scheme: light`, without
 * which a reader on a dark dashboard gets dark form controls and scrollbars inside
 * a white page.
 *
 * Rules live here rather than inline when they need a selector an inline style
 * cannot express: a hover, a placeholder, a pseudo-element, a keyframe.
 */
const CSS = [
  `.td-root { height: 100%; min-height: 0; background: ${C.bg}; color: ${C.text}; font-family: ${FONT};`,
  `  font-size: ${F.body}px; line-height: 1.5; color-scheme: light; -webkit-font-smoothing: antialiased; }`,
  // The host's MarkdownRenderer draws a message body (parts.mjs MdBody). It sets
  // no font-family — so it inherits the family above — and takes every colour
  // from a CSS custom property, which on the dashboard's own page resolves to
  // whatever theme the reader picked. This app is a white card either way, so a
  // dark theme in scope would put a dark inline-code chip and a dark table header
  // on white. Pinning the variables it reads inside `.td-root` is what makes the
  // borrowed component this app's own: the six below are every one its element
  // renderers and CodeBlock touch.
  `.td-root { --text: ${C.text}; --text-strong: ${C.text}; --muted: ${C.muted};`,
  `  --accent: ${C.mutedStrong}; --border: ${C.border}; --bg-elevated: ${C.bg2};`,
  `  --bg-hover: ${C.hover}; }`,
  // Its paragraph and list spacing are Tailwind utilities that do not exist here,
  // so the same values are restated as plain rules for the borrowed subtree.
  `.td-md-host p { margin: ${S.x1}px 0 }`,
  `.td-md-host ul, .td-md-host ol { margin: ${S.x2}px 0; padding-left: ${S.x8}px }`,
  '.td-md-host li { line-height: 1.625 }',
  `.td-md-host li + li { margin-top: ${S.x1}px }`,
  `.td-md-host li::marker { color: ${C.muted} }`,
  '.td-root *, .td-root *::before, .td-root *::after { box-sizing: border-box }',
  '.td-root button, .td-root input, .td-root textarea { font-family: inherit }',
  `.td-scroll { overflow-y: auto; overflow-x: hidden; scrollbar-width: thin; scrollbar-color: #C9C9C9 transparent }`,
  '@keyframes td-pulse { 50% { opacity: 0.4 } }',
  // A continuation row's time is revealed on hover: one visible timestamp per
  // author block instead of one per line.
  '.td-row-time { opacity: 0; transition: opacity 0.12s ease }',
  '.td-row:hover .td-row-time { opacity: 1 }',
  `.td-input::placeholder { color: ${C.muted} }`,
  '.td-quiet-btn { transition: color 0.12s ease, background 0.12s ease }',
  `.td-quiet-btn:hover { color: ${C.text} }`,
  // The row hover surface, and the action bar that appears over its corner.
  `.td-row:hover { background: ${C.hover} }`,
  '.td-actions { opacity: 0; transition: opacity 0.1s ease }',
  '.td-row:hover .td-actions { opacity: 1 }',
  // An icon button needs its own hover: with the word gone, the only thing that says
  // "this is a control" is the pointer and this tint (§15.1).
  `.td-act:hover:not(:disabled) { background: ${C.bg2}; color: ${C.text} }`,
  '.td-act:first-child { border-radius: 12px 0 0 12px }',
  '.td-act:last-child { border-radius: 0 12px 12px 0 }',
  `.td-actions button:hover:not(:disabled) { background: ${C.bg2}; border-color: ${C.text} }`,
  // The reply bar states the count until you point at it, then states what
  // clicking it does.
  '.td-reply-main { display: inline-flex }',
  '.td-reply-hint { display: none }',
  '.td-reply:hover .td-reply-hint { display: inline-flex }',
  '.td-reply:hover .td-reply-main { display: none }',
  `.td-reply:hover { background: ${C.bg2}; border-color: ${C.border} }`,
  `.td-rail-row:hover { background: ${C.bg2} }`,
  // A pill's border darkens under the pointer; that is the whole hover language.
  `.td-pill:hover:not(:disabled) { border-color: ${C.text} }`,
  `.td-pill-dark:hover:not(:disabled) { background: #000 }`,
  `.td-tab:hover:not(.td-tab-on) { background: ${C.bg2}; color: ${C.text} }`,
  // A thread title is a sentence someone wrote, so it can be any length. Clamped to
  // two lines with an ellipsis rather than wrapped freely: an unclamped title pushed
  // the panel's own controls down and, at the wrong width, left one character
  // stranded on a third line (§rev9.1 finding 4).
  // The divider between the conversation and the panel (§rev9.1 addendum). It is a
  // 6px hit area over a 1px line: invisible until pointed at, because a permanent
  // grey bar between two white columns reads as a seam in the page.
  '.td-grip { cursor: col-resize; touch-action: none; background: transparent; transition: background 0.12s ease }',
  `.td-grip:hover, .td-grip[data-drag="1"] { background: ${C.text} }`,
  `.td-grip:focus-visible { outline: 2px solid ${C.text}; outline-offset: -1px }`,
  '.td-clamp2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;',
  '  overflow: hidden; overflow-wrap: anywhere }',
  // Two composers on screen at once: the one you are typing into takes the dark
  // border, the other keeps a hairline. Without this the reader had two identical
  // boxes and no way to tell which one their keystrokes were going into.
  `.td-box { border: 1px solid ${C.border}; transition: border-color 0.12s ease }`,
  `.td-box:hover:not(:focus-within) { border-color: ${C.mutedStrong} }`,
  `.td-box:focus-within { border-color: ${C.text} }`,
].join('\n')

export function injectKeyframes() {
  if (typeof document === 'undefined') return
  // Evict every stylesheet an earlier module left behind, then insert ours. Both
  // halves matter: without the eviction two generations of rules cascade, and
  // without the early return a re-run would stack duplicates.
  const stale = []
  STYLE_PREFIXES.forEach((prefix) => {
    const found = document.querySelectorAll ? document.querySelectorAll(`style[id^="${prefix}"]`) : []
    Array.prototype.forEach.call(found, (el) => {
      if (el.id !== STYLE_ID) stale.push(el)
    })
  })
  stale.forEach((el) => {
    if (el.remove) el.remove()
    else if (el.parentNode) el.parentNode.removeChild(el)
  })
  const existing = document.getElementById(STYLE_ID)
  if (existing) {
    // Idempotent, and hot-reload safe: same id, new bytes.
    if (existing.textContent !== CSS) existing.textContent = CSS
    return
  }
  const el = document.createElement('style')
  el.id = STYLE_ID
  el.textContent = CSS
  document.head.appendChild(el)
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. Host module map (feature-detected — the map can lag a gateway version)
// ─────────────────────────────────────────────────────────────────────────────


export const STATE_COLOR = {
  idle: C.dotIdle,
  todo: C.dotIdle,
  working: C.warn,
  work: C.warn,
  done: C.ok,
  blocked: C.danger,
  fail: C.danger,
}

export function Dot({ state, size }) {
  const px = size || 8
  const live = state === 'working' || state === 'work'
  return _jsx('span', {
    // Classed so the screenshot probe can tell a status dot from a dark fill: the
    // probe stays strict about dark surfaces, and the exceptions are declared here
    // in code rather than listed in the probe.
    className: 'td-dot',
    style: {
      display: 'inline-block',
      width: `${px}px`,
      height: `${px}px`,
      borderRadius: '50%',
      flexShrink: 0,
      background: STATE_COLOR[state] || C.muted,
      animation: live ? 'td-pulse 1.6s infinite' : 'none',
    },
  })
}

export function Pill({ tone, children, title }) {
  const tones = {
    accent: { bg: C.accentSubtle, fg: C.accent },
    ok: { bg: C.okSubtle, fg: C.ok },
    warn: { bg: C.warnSubtle, fg: C.warn },
    danger: { bg: C.dangerSubtle, fg: C.danger },
    quiet: { bg: 'transparent', fg: C.muted },
  }
  const t = tones[tone] || tones.quiet
  return _jsx('span', {
    title,
    style: {
      background: t.bg,
      color: t.fg,
      padding: sp(S.half, S.x2),
      borderRadius: R.pill,
      fontSize: F.micro,
      fontWeight: 600,
      letterSpacing: '0.02em',
      whiteSpace: 'nowrap',
      border: tone === 'quiet' ? hair(C.border) : 'none',
    },
    children,
  })
}

const CJK = /[\u3000-\u9fff\uff00-\uffef]/

/**
 * Small-caps section label. Uppercasing is a no-op on Chinese and the wide
 * tracking opens visible gaps between glyphs, so both are dropped when the
 * label contains CJK.
 */
export function labelStyle(text) {
  const cjk = CJK.test(String(text == null ? '' : text))
  return {
    color: C.muted,
    fontSize: cjk ? F.meta : F.micro,
    letterSpacing: cjk ? 'normal' : '0.14em',
    textTransform: cjk ? 'none' : 'uppercase',
  }
}

export function Sect({ label, hint, first }) {
  return _jsxs('div', {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: S.x2,
      flexWrap: 'wrap',
      margin: first ? sp(0, 0, S.x2) : sp(S.x5, 0, S.x2),
    },
    children: [
      _jsx('span', { style: labelStyle(label), children: label }),
      hint ? _jsx('span', { style: { color: C.muted, fontSize: F.meta }, children: hint }) : null,
    ],
  })
}

export function Card({ children, pad, style, className }) {
  return _jsx('div', {
    className,
    style: {
      background: C.card,
      border: hair(C.border),
      borderRadius: R.lg,
      padding: pad === undefined ? S.x3 : pad,
      ...(style || {}),
    },
    children,
  })
}

export function Ghost({ children, onClick, disabled, title, active, tone }) {
  const accent = tone === 'danger' ? C.danger : C.accent
  const tint = tone === 'danger' ? C.dangerSubtle : C.accentSubtle
  return _jsx('button', {
    onClick,
    disabled,
    title,
    style: {
      background: active ? tint : 'transparent',
      color: disabled ? C.muted : accent,
      border: hair(active ? accent : C.border),
      padding: sp(S.x1, S.x3),
      borderRadius: R.pill,
      fontSize: F.micro,
      fontWeight: 500,
      cursor: disabled ? 'default' : 'pointer',
      whiteSpace: 'nowrap',
      fontFamily: 'inherit',
    },
    children,
  })
}

export function Notice({ tone, children }) {
  const map = { error: C.danger, warn: C.warn, info: C.muted }
  return _jsx('div', {
    style: {
      color: map[tone] || C.muted,
      fontSize: F.meta,
      padding: S.x3,
      border: hair(C.border),
      borderRadius: R.lg,
      background: C.card,
    },
    children,
  })
}

export function Loading({ what }) {
  return _jsx('div', {
    style: { color: C.muted, fontSize: F.quiet, padding: sp(S.x4, '0') },
    children: t('loading', { what: what || '' }),
  })
}

/**
 * Shown when the backend failed but real data is still on screen. Without it the
 * page would look current while quietly being a snapshot.
 */
export function StaleBar({ message, onRetry, detail }) {
  if (!message) return null
  return _jsxs('div', {
    title: detail || undefined,
    style: {
      background: C.warnSubtle,
      color: C.warn,
      border: hair(C.border),
      borderRadius: R.lg,
      padding: sp(S.x2, S.x3),
      fontSize: F.meta,
      marginBottom: S.x2,
      display: 'flex',
      alignItems: 'center',
      gap: S.x2,
    },
    children: [
      _jsx('span', { style: { minWidth: 0 }, children: message }),
      onRetry
        ? _jsx('span', {
            style: { marginLeft: 'auto', flexShrink: 0 },
            children: _jsx(Ghost, { onClick: onRetry, title: t('retry_hint'), children: t('retry') }),
          })
        : null,
    ],
  })
}

/**
 * A read that failed with nothing on screen to keep (§rev7 P0).
 *
 * This is the state that used to be filled with `fixtures/`. It says what went
 * wrong and offers the one action that can change the answer. It is deliberately
 * not a "no data" message: the desk may well have data, and the app not being able
 * to read it is a different fact from there being none.
 */
export function LoadError({ message, what, onRetry, detail }) {
  return _jsxs('div', {
    title: detail || undefined,
    style: {
      background: C.card,
      border: hair(C.border),
      borderRadius: R.lg,
      padding: S.x4,
      display: 'flex',
      flexDirection: 'column',
      gap: S.x2,
      alignItems: 'flex-start',
    },
    children: [
      _jsx('div', { style: { color: C.text, fontSize: F.body, fontWeight: W.medium },
        children: t('read_failed', { what: what || '' }) }),
      _jsx('div', { style: { color: C.muted, fontSize: F.quiet }, children: message }),
      onRetry ? _jsx(Ghost, { onClick: onRetry, title: t('retry'), children: t('retry') }) : null,
    ],
  })
}

export function DeskMark({ size }) {
  const px = size || 20
  return _jsxs('svg', {
    xmlns: 'http://www.w3.org/2000/svg',
    width: px,
    height: px,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: C.accent,
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
    children: [
      _jsx('path', { d: 'M3 17.5 8.5 11l4 3.5L21 6' }),
      _jsx('path', { d: 'M15.5 6H21v5.5' }),
      _jsx('path', { d: 'M3 21h18' }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 7. Member helpers (shared by Chat + Desk)
// ─────────────────────────────────────────────────────────────────────────────

export function memberKind(m) {
  if (!m) return 'staff'
  if (m.id === 'fund') return 'fund'
  if (m.id === 'desk') return 'desk'
  if (String(m.id).startsWith('lm')) return 'line'
  // An IC reads quieter than the standing roles above it: nine pods draw the
  // same ten of them, so giving each a saturated hue would make the rail read
  // as ninety different people rather than ten roles repeated.
  if (String(m.id).startsWith('ic-')) return 'ic'
  return 'staff'
}

const AVATAR_STYLE = {
  // A relayed row whose sender belongs to no member (§rev7 P0#3). Deliberately
  // colourless: it is the one author that is not a person, and giving it a
  // member's palette would read as a colleague nobody can find on the Desk page.
  system: { background: 'transparent', color: C.muted, border: hair(C.borderStrong) },
  ceo: { background: C.mutedStrong, color: C.accentFg, border: 'none' },
  // An IC has NO entry here on purpose, so it falls through to the filled
  // `avatarBg(seed)` path like everyone else. An outlined muted version read as
  // a MISSING avatar at 24px rather than a quiet one; the smaller box is what
  // keeps it from competing with the line-manager above it.
}

/**
 * A stable hue from a string (§2's fallback for a missing photo).
 *
 * There are no photographs on this surface — no member portraits, no ticker art —
 * so the standard's own degradation applies: a deterministic hue plus the first
 * glyph, never a grey box. Deterministic matters more than pretty: the same person
 * is the same colour on every page and across reloads, which is what lets a reader
 * recognise them in a rail, a reply bar and a thread header without reading.
 */
export function hue(seed) {
  let x = 0
  for (const ch of String(seed || '')) x = (x * 31 + ch.charCodeAt(0)) >>> 0
  return x % 360
}

export function avatarBg(seed) {
  return `hsl(${hue(seed)} 48% 46%)`
}

/** The kind's identifying colour, for the outlined hero badge. */
const KIND_COLOR = { fund: C.accent, desk: C.ok, staff: C.warn, line: C.accent, ic: C.muted, ceo: C.borderStrong }

const LETTER_BY_ID = { fund: 'F', macro: 'M', desk: 'D', risk: 'R', trader: 'T', scrum: 'S' }

//: An IC's monogram, keyed by the role suffix of its `ic-<pod>-<role>` id. Two
//: letters because one is ambiguous within a single pod: `technicals` and
//: `trader` both start with T, `bull` and `bear` with B, and the three risk
//: reviewers all with R -- six of the ten rows would have shared three letters
//: AND, since the hue is derived from what is drawn, three colours.
const IC_LETTER = {
  'risk-conservative': 'RC',
  'risk-aggressive': 'RA',
  'risk-neutral': 'RN',
  fundamentals: 'FU',
  technicals: 'TE',
  sentiment: 'SE',
  news: 'NE',
  trader: 'TR',
  bull: 'BU',
  bear: 'BE',
}

/**
 * A member's monogram.
 *
 * The nine line managers used to all read 'L', which is nine identical avatars for
 * nine different teams — the rail then told a reader nothing. Each takes the
 * initials of the pod it runs instead (example-megacap -> AC), which is also what makes
 * the hue distinct, since the hue is derived from what is drawn.
 */
export function memberLetter(m) {
  if (!m) return '?'
  if (LETTER_BY_ID[m.id]) return LETTER_BY_ID[m.id]
  const id = String(m.id || '')
  if (id.startsWith('ic-')) {
    for (const role of Object.keys(IC_LETTER)) {
      if (id.endsWith(`-${role}`)) return IC_LETTER[role]
    }
  }
  const pod = m.pod || id.replace(/^lm-/, '')
  if (id.startsWith('lm')) {
    const parts = String(pod).split(/[-_ ]+/).filter(Boolean)
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    return String(pod || 'L').slice(0, 2).toUpperCase()
  }
  return String(m.name || m.id || '?').charAt(0).toUpperCase()
}

export function Avatar({ letter, kind, size, radius, seed, soft }) {
  const px = size || L.avatar
  const fixed = AVATAR_STYLE[kind]
  const s = soft
    ? {
        background: C.bg,
        color: KIND_COLOR[kind] || C.accent,
        border: rule(KIND_COLOR[kind] || C.accent),
      }
    : fixed || { background: avatarBg(seed || letter), color: '#FFFFFF', border: 'none' }
  return _jsx('div', {
    className: 'td-avatar',
    style: {
      width: `${px}px`,
      height: `${px}px`,
      borderRadius: radius || R.md,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      // A ratio of the box would put the letter on its own size at every call
      // site -- 8px in the 20px avatar, 14px in the 36px one, neither on the
      // ramp. The letter picks a ramp step by box size instead.
      fontSize: avatarType(px),
      fontWeight: W.bold,
      letterSpacing: '0.01em',
      flexShrink: 0,
      ...s,
    },
    children: letter,
  })
}

/** Depth-first walk from the roots so children always sit under their parent;
 *  siblings keep the order the backend returned.
 *
 *  `collapsed` is an optional Set of member ids whose subtree is folded away.
 *  The roster carries 90 ICs across nine pods, so the rail is unusable if every
 *  one of them is always drawn -- the Desk page folds the pods by default and
 *  needs to know, per row, whether there is anything under it to unfold. Each
 *  row therefore reports `hasChildren`; an absent `collapsed` keeps the old
 *  fully-expanded behaviour. */
export function orgRows(members, collapsed) {
  const list = Array.isArray(members) ? members : []
  const folded = collapsed instanceof Set ? collapsed : new Set()
  const byParent = new Map()
  for (const m of list) {
    const key = m.parent || '__root__'
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key).push(m)
  }
  const rows = []
  // `seen` means CLAIMED, not rendered. A folded node claims its whole subtree
  // without emitting it, which is what keeps the orphan sweep below from
  // re-adding those rows: they are deliberately absent, not unreachable.
  const seen = new Set()
  const claimSubtree = (key) => {
    for (const m of byParent.get(key) || []) {
      if (seen.has(m.id)) continue
      seen.add(m.id)
      claimSubtree(m.id)
    }
  }
  const walk = (key, depth) => {
    for (const m of byParent.get(key) || []) {
      if (seen.has(m.id)) continue
      seen.add(m.id)
      const hasChildren = (byParent.get(m.id) || []).length > 0
      const isFolded = folded.has(m.id)
      rows.push({ member: m, depth, hasChildren, collapsed: isFolded })
      if (isFolded) claimSubtree(m.id)
      else walk(m.id, depth + 1)
    }
  }
  walk('__root__', 1)
  // The sweep is for a node the walk cannot reach at all -- a parent id absent
  // from this payload, or a parent cycle. Without the claim above it also swept
  // up every folded descendant and drew all ninety ICs at depth 1 with no
  // indent and no twisty, undoing the fold it was supposed to survive.
  for (const m of list) {
    if (!seen.has(m.id)) {
      rows.push({ member: m, depth: 1, hasChildren: false, collapsed: false })
    }
  }
  return rows
}

export function findMember(members, id) {
  return (members || []).find((m) => m.id === id) || null
}

// ─────────────────────────────────────────────────────────────────────────────
// 8. Chat page
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The tada-* agent a NEW session must bind to. It lives in `/org`'s `profiles`
 * map, which §2's member block does not list and `fixtures/org.json` does not
 * carry, so both shapes are read and a miss just omits the prop — harmless,
 * since an existing slot already has its agent.
 */
export function agentFor(org, id) {
  const profile = org && org.profiles && org.profiles[id]
  if (profile && profile.agent) return profile.agent
  const member = findMember(org && org.members, id)
  return (member && member.agent) || undefined
}
