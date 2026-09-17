/** Shared chat chrome: the row, the item model, markdown, the folds, the composer. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { appSdk, HostBoundary, resetMember, uiKit } from './data.mjs'
import { getLang, memberTitle, phrase, t } from './i18n.mjs'
import { Avatar, C, Dot, F, Ghost, L, LH, MONO, R, S, SHADOW, W, hair, memberKind, memberLetter, rule, sp } from './theme.mjs'


/** How long the confirm step stays armed before disarming itself. */
const RESET_ARM_MS = 4000

const RESET_LABEL = {
  idle: () => t('reset_idle'),
  armed: () => t('reset_armed'),
  busy: () => t('reset_busy'),
  missing: () => t('reset_idle'),
}

/**
 * Two-step reset. The first click arms the confirm, the second performs it, and
 * an unanswered confirm disarms on its own so a stray click cannot leave a
 * destructive button primed for a later one. No `confirm()` — it blocks the whole
 * dashboard, not just this panel.
 */
function ResetButton({ memberId, onReset }) {
  const [ui, setUi] = useState({ phase: 'idle', error: '' })
  const timer = useRef(null)

  // Only unmount cleanup: the button is keyed on the member, so switching member
  // remounts it and an armed confirm cannot follow you to someone else's chat.
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  function disarm() {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }

  async function click() {
    if (ui.phase === 'busy' || ui.phase === 'missing') return
    if (ui.phase === 'idle') {
      setUi({ phase: 'armed', error: '' })
      disarm()
      timer.current = setTimeout(() => setUi({ phase: 'idle', error: '' }), RESET_ARM_MS)
      return
    }
    disarm()
    setUi({ phase: 'busy', error: '' })
    const res = await resetMember(memberId)
    if (res.missing) {
      setUi({ phase: 'missing', error: t('reset_missing_note') })
      return
    }
    if (res.error) {
      setUi({ phase: 'idle', error: res.error })
      return
    }
    setUi({ phase: 'idle', error: '' })
    onReset(memberId, res.slotKey)
  }

  const armed = ui.phase === 'armed'
  return _jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: S.x2 },
    children: [
      ui.error
        ? _jsx('span', {
            style: { fontSize: F.micro, color: ui.phase === 'missing' ? C.muted : C.danger },
            children: ui.error,
          })
        : null,
      _jsx(Ghost, {
        onClick: click,
        active: armed,
        tone: armed ? 'danger' : undefined,
        disabled: ui.phase === 'busy' || ui.phase === 'missing',
        title:
          ui.phase === 'missing'
            ? t('reset_missing_tip')
            : t('reset_tip'),
        children: RESET_LABEL[ui.phase](),
      }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// TdChat — this app's own chat view (ARCHITECTURE.md §9)
//
// Every pixel of the transcript, the process lines and the composer is drawn
// here. The host's ChatPane and ChatEmbed are retired: for four rounds their
// message body was reshaped from the outside with scoped CSS, and it never held
// — the body is theirs to change, its colours are inline, and what the reader
// saw stayed "not Slack". Owning the DOM is what makes the reference image
// (design/refs/slack-ref-thread-reply.png) reachable at all.
//
// What that costs is stated rather than faked, in §9.1 and again at the
// composer: no /command menu, no @file mention, no model picker and no approval
// buttons. Those are the host composer's, and imitating them would promise a
// capability this app does not have.
// ─────────────────────────────────────────────────────────────────────────────


// ─── Slack's geometry (ARCHITECTURE.md §10.2) ────────────────────────────────────
//
// rev4.1 aligned this to the main dashboard chat (14px/24px, measured in the real
// bundle). rev5 supersedes those numbers with Slack's own, which is what the
// reader actually asked to be shown: a 36px square-ish avatar in a 52px gutter, a
// 15px/900 name on the timestamp's baseline, and a 15px body at 1.46. The colours
// stay on theme tokens — a palette is the one thing not being cloned.
const ROW_AVATAR = L.avatar
const ROW_GAP = S.x4
export const ROW_GUTTER = ROW_AVATAR + ROW_GAP
const AVATAR_RADIUS = R.md
/** The row's own horizontal padding, so a hover background spans the pane. */
export const ROW_PAD = S.x5

/**
 * The reading size of a message body, and the author name's.
 *
 * They used to be one constant (`BODY_PX = F.body`), which meant the body could
 * not move without taking the author line with it. They are different jobs: the
 * author line is Slack's own 15px/900 (§10.2), and the body is the paragraph a
 * person actually reads — aligned to the dashboard's chat transcript, which is
 * 14px on a 24px leading (`text-sm leading-6`). At 15px/1.46 the body's leading
 * was 21.9px, which is what read as cramped against it.
 */
export const READ_PX = 14
export const READ_LH_PX = 24
export const NAME_PX = F.body
export const BODY_PX = READ_PX
export const BODY_LH = READ_LH_PX / READ_PX
const NAME_WEIGHT = W.name
export const QUIET_PX = F.quiet
export const STAMP_PX = F.meta

/**
 * How wide the text column is allowed to get.
 *
 * The row itself stays full width — a centred 800px column was rejected, and
 * rightly: it left a quarter of the pane empty to the LEFT of the conversation.
 * This caps only the measure, so the whitespace lands on the right.
 *
 * 1200px is §10.2's number, and it replaces the two-term `max(100ch, 34%)` this
 * arrived at by rendering: that resolved to ~800px on a normal window and
 * ~1100px on the reader's, so 1200 is close to its wide end and simply always
 * applies. On a 1280px window the pane is narrower than the cap, so nothing
 * changes there; on a 3400px one the prose stops short of the right edge, which
 * is the Slack observation the number came from.
 */
const MEASURE = `${L.measure}px`

/**
 * The whole column: the gutter a row opens with, plus the measure.
 *
 * Everything that is not a row uses it — the day divider, the offered choices,
 * the composer. Capping only the message bodies was tried and looked worse than
 * no cap at all: a 1100px conversation under a 3200px date rule, above a 3200px
 * empty input. The rows themselves stay full width so their hover background
 * spans the pane, which is also Slack's behaviour.
 */
export const COLUMN = `calc(${ROW_GUTTER}px + ${MEASURE})`

/**
 * Which author a row belongs to; null for a row that is not conversation.
 *
 * A relayed row is authored by whoever sent it, not by the reader whose role field
 * it borrowed. Keying the block on the sender is what stops a manager's relayed
 * line from merging into the reader's own block and inheriting its name.
 */
function rowAuthor(m) {
  if (!m) return null
  if (m.role === 'user') {
    const { relayed, sender } = stripEnvelope(m.content)
    return relayed ? `relay:${sender}` : 'user'
  }
  if (m.role === 'assistant' || m.role === 'streaming') return 'agent'
  return null
}

/**
 * How long an author's block stays open. Past this, the same person speaking
 * again earns a fresh author line: the reader has lost track of when the last
 * one was said, which is the whole job of the line.
 */
const GROUP_WINDOW_MS = 5 * 60 * 1000

/** Whether two rows were said closely enough to read as one block. A row with
 *  no usable clock keeps the block rather than breaking it on a parse failure. */
function saidTogether(prev, next) {
  const a = Date.parse((prev && prev.ts) || '')
  const b = Date.parse((next && next.ts) || '')
  if (!isFinite(a) || !isFinite(b)) return true
  return Math.abs(b - a) <= GROUP_WINDOW_MS
}

/**
 * Whether this row continues the one above it, and so drops the avatar, the
 * name and the visible time.
 *
 * Compared against the previous CONVERSATIONAL row, skipping process rows. A
 * tool call is not another speaker, so it must not break an author's block: two
 * replies either side of one tool call are one person still talking, and an
 * author line between them says nothing the reader did not already know. That is
 * the ruling against the Slack reference — what earns a header there is a change
 * of speaker or a long gap, and the reference has no third thing that speaks.
 */
function isContinuationRow(messages, index) {
  const me = messages && messages[index]
  const author = rowAuthor(me)
  if (!author) return false
  for (let i = index - 1; i >= 0; i--) {
    const prevAuthor = rowAuthor(messages[i])
    if (!prevAuthor) continue
    if (prevAuthor !== author) return false
    return saidTogether(messages[i], me)
  }
  return false
}

/**
 * One conversation row: avatar in a left gutter, author line, body.
 *
 * A continuation row keeps the gutter — so every body in a block lines up on the
 * same left edge — and spends it on the time, revealed on hover the way Slack
 * does rather than printed on every line.
 */
export function SlackRow({ member, agent, isUser, relay, relayed, timestamp, timestampTitle, cont, actions, children }) {
  // Three authors, and a relayed row is never the first of them. A row that
  // arrived through `session_send` carries `role: 'user'` but the reader did not
  // write it, so it is drawn as whoever sent it -- or, when that sender belongs to
  // no member, as a neutral non-person rather than as the reader (§rev7 P0#3).
  const who = relay
    ? {
        letter: memberLetter(relay),
        kind: memberKind(relay),
        name: relay.name || relay.id || t('protocol_author'),
        tag: relay.agent || null,
        label: t('ai_of', { title: memberTitle(relay) }).trim(),
      }
    : relayed
      ? { letter: '⋯', kind: 'system', name: t('protocol_author'), tag: null, label: null }
      : isUser
        ? { letter: 'R', kind: 'ceo', name: t('you'), tag: null, label: null }
        : {
            letter: memberLetter(member),
            kind: memberKind(member),
            name: (member && member.name) || 'agent',
            tag: agent,
            label: t('ai_of', { title: memberTitle(member) }).trim(),
          }
  return _jsxs('div', {
    className: 'td-row',
    style: {
      display: 'flex',
      gap: `${ROW_GAP}px`,
      alignItems: 'flex-start',
      // The row's own padding, so the hover background spans the pane rather
      // than a text column floating inside it (Slack's behaviour).
      padding: cont ? sp(S.half, ROW_PAD) : sp(S.x2, ROW_PAD, S.half),
      position: 'relative',
    },
    children: [
      _jsx('div', {
        style: {
          width: `${ROW_AVATAR}px`,
          flexShrink: 0,
          display: 'flex',
          justifyContent: 'flex-end',
          paddingTop: S.half,
        },
        children: cont
          ? _jsx('span', {
              className: 'td-row-time',
              title: timestampTitle,
              style: {
                fontSize: STAMP_PX,
                color: C.muted,
                fontVariantNumeric: 'tabular-nums',
                lineHeight: `${Math.round(NAME_PX * LH.body)}px`,
              },
              children: timestamp,
            })
          : _jsx(Avatar, { letter: who.letter, kind: who.kind, size: ROW_AVATAR, radius: AVATAR_RADIUS }),
      }),
      _jsxs('div', {
        className: 'td-col',
        // The measure. `ch` was once resolved here, so the body size is still set
        // on this element; it also makes the column's own text inherit correctly.
        // `position: relative` so the hover action bar can sit at the TEXT
        // column's top-right. Anchored to the row instead, it lands at the pane's
        // right edge — on a 3400px window, two thousand pixels from the message
        // it belongs to.
        style: { minWidth: 0, flex: 1, fontSize: `${BODY_PX}px`, maxWidth: MEASURE, position: 'relative' },
        children: [
          cont
            ? null
            : _jsxs('div', {
                className: 'td-row-head',
                style: {
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: S.x2,
                  minWidth: 0,
                  marginBottom: S.hair,
                },
                children: [
                  _jsx('span', {
                    style: {
                      fontSize: `${NAME_PX}px`,
                      fontWeight: NAME_WEIGHT,
                      lineHeight: 1.3,
                      color: C.text,
                    },
                    children: who.name,
                  }),
                  who.label
                    ? _jsx('span', {
                        style: {
                          fontSize: F.micro,
                          color: C.muted,
                          border: hair(C.line2),
                          borderRadius: R.pill,
                          padding: sp(S.hair, S.x2),
                          whiteSpace: 'nowrap',
                        },
                        // The agent id lives in the tooltip. On the line itself it
                        // was an internal noun set in a machine typeface, which is
                        // two of the standard's rules broken at once; what a reader
                        // needs to know there is that this colleague is an AI.
                        title: who.tag || '',
                        children: who.label,
                      })
                    : null,
                  timestamp
                    ? _jsx('span', {
                        style: {
                          fontSize: STAMP_PX,
                          color: C.muted,
                          whiteSpace: 'nowrap',
                          fontVariantNumeric: 'tabular-nums',
                        },
                        title: timestampTitle,
                        children: timestamp,
                      })
                    : null,
                ],
              }),
          children,
          actions || null,
        ],
      }),
    ],
  })
}

/**
 * The hover actions Slack floats over a row's top-right corner.
 *
 * The thread action can only OPEN one. Nothing in the desk's API creates a thread — a
 * thread is a dispatch the crew made, and `/threads` only reports them — so on a
 * message that has none the button says why instead of pretending.
 */
/**
 * The hover bar's icons (§15.1).
 *
 * Drawn here rather than loaded: three 16px glyphs is less bytes than a request, and
 * an icon that arrives late is worse than one that never moves. Stroked in
 * `currentColor` so the disabled and hover colours the bar already computes apply
 * without a second palette.
 *
 * Every one is a BUTTON with a tooltip and an accessible name -- the icon replaces the
 * visible word, not the label. A bar of three unlabelled glyphs is a guessing game for
 * a screen reader and for a new user hovering it the first time.
 */
const ICON_PATHS = {
  // A quote block: the rule down the left, and the lines it holds.
  quote: ['M4.5 4.5v7', 'M8 5.5h4.5', 'M8 8h4.5', 'M8 10.5h3'],
  // A conversation that continues somewhere else: a bubble with a tail.
  thread: ['M2.5 4.75A1.25 1.25 0 0 1 3.75 3.5h8.5A1.25 1.25 0 0 1 13.5 4.75v4.5A1.25 1.25 0 0 1 12.25 10.5H6.5L3.5 13v-2.5A1.25 1.25 0 0 1 2.5 9.25z'],
}

function ActionIcon({ name }) {
  return _jsx('svg', {
    width: 16,
    height: 16,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.4,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
    focusable: 'false',
    children: (ICON_PATHS[name] || []).map((d, i) => _jsx('path', { d }, `p${i}`)),
  })
}

export function RowActions({ onQuote, onOpenThread, hasThread, starting, unavailable, nested, unaddressable }) {
  const btn = (icon, label, onClick, title) =>
    _jsx('button', {
      className: 'td-act',
      onClick,
      disabled: !onClick,
      // The word survives as the tooltip and the accessible name; only the visible
      // text became a glyph.
      title: title || label,
      'aria-label': label,
      style: {
        border: 'none',
        background: 'transparent',
        color: onClick ? C.muted : C.borderStrong,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        padding: 0,
        cursor: onClick ? 'pointer' : 'default',
      },
      children: _jsx(ActionIcon, { name: icon }),
    }, label)

  return _jsx('div', {
    className: 'td-actions',
    style: {
      position: 'absolute',
      top: -S.x1,
      right: 0,
      display: 'flex',
      alignItems: 'center',
      background: C.card,
      border: hair(C.border),
      borderRadius: R.md,
      boxShadow: SHADOW.pop,
      zIndex: 2,
    },
    children: _jsxs(_Fragment, {
      children: [
        btn('quote', t('act_quote'), onQuote),
        // Whether this button EXISTS is a different question from whether it is
        // live, and what decides it is the shape of the reason:
        //
        //   permanent -> do not render it. A message that already has a thread
        //                gets in through the reply bar under it, and two controls
        //                for one thread read as two threads (§rev9.1 finding 6);
        //                a row inside a thread panel cannot nest one at all; and
        //                a row the gateway has minted no `mid` for cannot be
        //                addressed, so a create on it is refused before it starts.
        //                None of the three will change, so a greyed button and a
        //                tooltip only invite the reader to find a dead end.
        //   temporary -> render it disabled and say why. A gateway whose build has
        //                no `POST /thread` may gain one, and the reader did
        //                nothing to cause it, so that refusal is worth a sentence.
        //
        // This shipped the other way round: a panel drew a greyed button whose
        // tooltip blamed the backend for missing a feature it has.
        hasThread || nested || unaddressable
          ? null
          : btn(
              'thread',
              starting ? `${t('act_thread')}…` : t('act_thread'),
              unavailable || starting ? null : onOpenThread,
              unavailable
                ? t('act_thread_missing')
                : starting
                  ? `${t('act_thread')}…`
                  : t('act_thread_new'),
            ),
        // There is no copy button, and that is deliberate. The row this replicates
        // holds react / reply in thread / share / save and an overflow menu — a
        // copy-the-text control is not one of them, because the platform already
        // copies a selection. Ours also had nowhere to show that it worked: the
        // tick lived in the tooltip, so a click looked like nothing happening,
        // which is how the row came to read as three buttons that open nothing.
      ],
    }),
  })
}

// The parsed-milliseconds local is named `ms`, never `t`. `t` is this module's
// imported translator (line 6), and a local of that name shadows it for the whole
// function -- so a later edit that adds a translator call gets a number where it
// expects a function and the page dies with `t is not a function`. That is not a
// hypothetical: `dayName` shipped that way, and because it only reaches the
// translator on TODAY and YESTERDAY, every fixture-dated test passed.

/** Clock on a row, and the full stamp behind it. */
export function rowTime(ts) {
  const ms = Date.parse(ts || '')
  if (!isFinite(ms)) return ''
  return new Date(ms).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function rowTimeTitle(ts) {
  const ms = Date.parse(ts || '')
  return isFinite(ms) ? new Date(ms).toLocaleString() : ''
}

/**
 * The anchor for a row, in the shape `POST /thread` parses (ARCHITECTURE.md §8.2).
 *
 * One fact carries two names across this one call: the REQUEST key is `mid` and
 * the STORED key the response reads back is `main_msg`. This sent the stored
 * name, so `parse_body` saw no `mid` at all and refused every create with
 * "anchor needs both mid and ts" — the Thread button could not work, on any row.
 *
 * A pure function rather than an object literal inside the component, so a test
 * can hand its output to the backend's own parser instead of trusting the two
 * names to agree by eye. `mid` comes back empty for a row the gateway has not
 * minted one for yet, which is a row nothing can anchor; the caller reads that
 * and draws no button rather than sending a create that must fail.
 */
export function threadAnchor(m) {
  const meta = m && typeof m.meta === 'object' && m.meta ? m.meta : {}
  return {
    mid: typeof meta.mid === 'string' ? meta.mid.trim() : '',
    ts: m && typeof m.ts === 'string' ? m.ts : '',
  }
}

function dayKey(ts) {
  const ms = Date.parse(ts || '')
  return isFinite(ms) ? new Date(ms).toDateString() : ''
}

/** Slack names the two days a reader has a word for, and dates the rest. */
function dayName(ts) {
  const ms = Date.parse(ts || '')
  if (!isFinite(ms)) return ''
  const day = new Date(ms)
  const now = new Date()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (day.toDateString() === now.toDateString()) return t('day_today')
  if (day.toDateString() === yesterday.toDateString()) return t('day_yesterday')
  // Any other day is WORDS -- a weekday and a month name -- so it takes the
  // reader's language, not the host's locale. `undefined` here read
  // "Tuesday, September 8" in the middle of a Chinese transcript. The clock on
  // each row stays on the host locale on purpose: those are digits, and their
  // format is the platform's business rather than this app's.
  return day.toLocaleDateString(getLang(), { weekday: 'long', month: 'long', day: 'numeric' })
}

// ─── The item model ──────────────────────────────────────────────────────────
//
// A transcript row is one of four things, and the difference is what the reader
// is owed. Two people talking get a full row. The machinery in between — tool
// calls and reasoning — is folded away, because it is how the answer was reached
// and not the answer. A gate that needs a human is never folded. Anything else
// is one quiet line, so an unrecognised row is still visible rather than
// silently dropped.

export const CONVO_ROLE = { user: 1, assistant: 1, streaming: 1 }
const PROCESS_ROLE = { tool: 1, tool_call: 1, tool_result: 1, thinking: 1 }

// ─────────────────────────────────────────────────────────────────────────────
// Protocol vs. conversation  (§rev7 P0#2)
//
// A thread's session is driven by machinery as well as by people, and the machine's
// half was reaching the reader verbatim: the `[sent by session … via session_send]`
// envelope the gateway prepends to a relayed message, the whole seed brief with its
// internal file paths, and a dispatch thread's run prompt ("You are the Kiro
// `tada-…` agent. Your system prompt is in …"). A thread is meant to read like a
// colleague talking.
//
// The tests below are SHAPE, never a word list. A blacklist is the wrong tool
// twice over: it hides a real sentence that happens to contain a banned word, and
// it misses the next protocol message that says the same thing differently.
//
//  - the envelope is a bracketed machine header at position 0, and nothing else
//    can be there;
//  - a run prompt is second-person instructions addressed to an agent, which in
//    this desk's own generator opens with `You are the …` (an explicitly
//    sanctioned prefix test) OR carries an instruction block -- three or more
//    lines that are an ALL-CAPS label followed by a colon. Nobody writes three
//    `OUTPUT REQUIRED:` headings to a colleague; a form written for a machine to
//    parse is the only thing shaped that way.
//
// Nothing is deleted. A folded message keeps its full text one click away, because
// the reader asked not to be shown protocol, not to be prevented from reading it.
// ─────────────────────────────────────────────────────────────────────────────

/** The gateway's relay header, as its own line at the very start of a message.
 *  Group 1 is the sending session's key, which is who actually spoke. */
const ENVELOPE = /^[ \t]*\[sent by session[ \t]+([^\]\s]+)[^\]\n]*\][ \t]*(?:\r?\n)?/

/** An ALL-CAPS label heading a machine-readable block: `OUTPUT REQUIRED:`. */
const CAPS_LABEL = /^[A-Z][A-Z0-9][A-Z0-9 '()/&,.-]{0,58}:(?:\s|$)/

/**
 * The relay envelope, removed, and who sent it.
 *
 * `relayed` and `sender` are not bookkeeping: a relayed row arrives with
 * `role: 'user'` because the gateway injected it as a turn, but the reader did NOT
 * write it -- in a thread's clone session the first such row is the conductor's own
 * brief. Drawing it as the reader puts a manager's internal instructions in the reader's
 * mouth, which is worse than printing the envelope was. So the sender travels out
 * of here and decides the row's attribution.
 */
export function stripEnvelope(text) {
  const raw = String(text == null ? '' : text)
  const m = raw.match(ENVELOPE)
  if (!m) return { text: raw, relayed: false, sender: '' }
  return {
    text: raw.slice(m[0].length).replace(/^\s*\r?\n/, ''),
    relayed: true,
    sender: m[1] || '',
  }
}

/**
 * Which member a sending session key belongs to (§rev7 P0#3).
 *
 * Two ways, in order of authority. A key the roster currently reports as a
 * member's own session IS that member -- that is the binding itself, not an
 * inference. Otherwise `td-<member>-<epoch>`, the shape this app mints, still names
 * its member after a reset has moved the binding on, which is exactly when the
 * first test stops working.
 *
 * A dashboard key (`chat-N-…`) belongs to no member and returns null on purpose:
 * the caller then draws a neutral author rather than guessing. Guessing here would
 * put words in a named colleague's mouth, which is the same class of error this
 * fixes.
 */
export function senderMember(key, members) {
  const k = String(key || '')
  if (!k) return null
  const list = Array.isArray(members) ? members : []
  const bound = list.find((m) => m && m.slot_key && m.slot_key === k)
  if (bound) return bound
  const m = k.match(/^td-([a-z0-9-]+?)-\d+$/)
  if (!m) return null
  return list.find((x) => x && x.id === m[1]) || null
}

/** Is this message a form written for an agent rather than a line to a person? */
function isProtocolShape(text) {
  const body = String(text || '')
  if (!body.trim()) return false
  if (/^\s*You are the\b/.test(body)) return true
  const labels = body.split(/\r?\n/).filter((l) => CAPS_LABEL.test(l))
  return labels.length >= 3
}

function isStopEvent(m) {
  return !!m && (m.kind === 'stop_event' || (m.meta && m.meta.kind === 'stop_event'))
}

/** One line standing in for a row this view does not draw in full. */
export function quietText(m) {
  const raw = stripEnvelope((m && m.content) || '').text.replace(/\s+/g, ' ').trim()
  if (!raw) return String((m && m.role) || '')
  return raw.length > 160 ? `${raw.slice(0, 160)}…` : raw
}

export function chatItems(messages, opts) {
  const list = Array.isArray(messages) ? messages : []
  // A thread's session opens with a brief somebody wrote FOR the clone, not a line
  // to the reader, so in a panel the first user row folds. In the main chat the
  // first user row is the reader's own sentence and is never touched.
  //
  // `seedHide` drops that row instead of folding it, for the case where the panel
  // ALREADY shows the same account above the replies: the manager's receipt and the
  // brief it dispatched say the same thing, and one panel showing it twice is what
  // made the top of the panel unreadable. The caller only passes it when it has a
  // receipt to show, so a thread without one keeps the brief as its only context.
  const seedFold = !!(opts && opts.seedFold)
  const seedHide = !!(opts && opts.seedHide)
  let seenUser = false
  const items = []
  let day = ''
  let run = null

  const flush = () => {
    if (run) {
      items.push(run)
      run = null
    }
  }

  list.forEach((m, i) => {
    const role = String((m && m.role) || '')
    if (PROCESS_ROLE[role] && !isStopEvent(m)) {
      if (!run) run = { kind: 'process', at: i, rows: [] }
      run.rows.push(m)
      return
    }
    flush()
    const key = dayKey(m && m.ts)
    if (key && key !== day) {
      day = key
      items.push({ kind: 'day', at: i, label: dayName(m.ts) })
    }
    if (isStopEvent(m)) {
      items.push({ kind: 'quiet', at: i, msg: m, text: quietText(m) })
      return
    }
    if (CONVO_ROLE[role]) {
      const env = stripEnvelope(m && m.content)
      const body = env.text
      // A relayed row is not the reader's, so it is not the seed-position "first
      // user message" either -- but in a thread the seed IS relayed, and it is the
      // first one that matters. `first` therefore counts user-position rows in
      // order, which is what "the thread opens with a brief" means.
      const first = role === 'user' && !seenUser
      if (role === 'user') seenUser = true
      // Protocol beats seed: a run prompt is a run prompt wherever it sits, and
      // labelling it the brief would misdescribe what the reader is opening.
      const fold = isProtocolShape(body) ? 'protocol' : seedFold && first ? 'brief' : null
      if (fold === 'brief' && seedHide) return
      items.push({
        kind: 'msg',
        at: i,
        msg: m,
        author: rowAuthor(m),
        cont: isContinuationRow(list, i),
        body,
        fold,
        relayed: env.relayed,
        sender: env.sender,
      })
      return
    }
    if (role === 'error') {
      items.push({ kind: 'error', at: i, msg: m })
      return
    }
    // A permission row is a live human gate, so it is never folded and never
    // abbreviated. This app cannot answer it (§9.1 — the approval buttons are
    // the host composer's), so it says where it can be answered.
    if (role === 'permission') {
      items.push({ kind: 'permission', at: i, msg: m })
      return
    }
    if (role === 'queued') {
      items.push({ kind: 'queued', at: i, msg: m })
      return
    }
    items.push({ kind: 'quiet', at: i, msg: m, text: quietText(m) })
  })

  flush()
  return foldTurns(items)
}

/**
 * A member's turn is one thing they did, so it reads as one row (§13.1).
 *
 * The reader asked one question and got four paragraphs of narration back — "read the
 * skill", "open a thread first", "thread opened, now seed it", "opened thread: …" — with the
 * machinery between them and a reply bar hanging off three of them. Every one of
 * those is the manager THINKING OUT LOUD while working. Only the last paragraph is
 * the answer, and the main conversation is meant to be a result stream: the
 * starting point and the end point, not the walk between them.
 *
 * So one turn collapses to: the author line, one grey `N steps` line holding the
 * intermediate prose AND the tool calls in document order, and the final paragraph.
 *
 * Turn boundaries are NOT a new idea invented here — they are exactly the block
 * boundaries §rev3 already draws: a change of speaker, or a gap past the group
 * window, with machinery transparent to both (`isContinuationRow`). Inventing a
 * second notion of "turn" would let the fold disagree with the author lines.
 *
 * What this deliberately never folds:
 *  - The READER's own rows. Two questions typed a minute apart are two questions;
 *    hiding the first behind a fold labelled "steps" would call the reader's words
 *    machinery and lose one of them.
 *  - Permission rows, errors, day dividers, queued rows. A live approval gate is
 *    the one thing a reader must see (§9 ruling), and it never became a turn item
 *    to begin with.
 */
function foldTurns(items) {
  const out = []
  let pending = []
  let turn = null

  const closeTurn = () => {
    if (!turn) return
    out.push(finishTurn(turn))
    turn = null
  }
  const dropPending = () => {
    pending.forEach((p) => out.push(p))
    pending = []
  }

  items.forEach((it) => {
    if (it.kind === 'process') {
      // Machinery belongs to the turn it runs inside. Before the first paragraph
      // it is buffered, because that work is what the turn is ABOUT to report --
      // the run that produced the answer, not a loose event of its own.
      if (turn) turn.rows.push(it)
      else pending.push(it)
      return
    }
    if (it.kind === 'msg' && it.author !== 'user') {
      if (turn && it.cont) {
        turn.rows.push(it)
        return
      }
      closeTurn()
      turn = { at: it.at, rows: pending.concat([it]) }
      pending = []
      return
    }
    closeTurn()
    dropPending()
    out.push(it)
  })

  closeTurn()
  dropPending()
  return out
}

/**
 * Split one turn into what the reader sees and what goes behind the fold.
 *
 * The visible half is the LAST paragraph — the turn's conclusion. Everything
 * before it, prose and machinery alike, keeps its document order inside the fold,
 * so opening it reads as the walk that actually happened.
 */
function finishTurn(turn) {
  const rows = turn.rows
  let tailAt = -1
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].kind === 'msg') {
      tailAt = i
      break
    }
  }
  const tail = tailAt >= 0 ? rows[tailAt] : null
  const folded = rows.filter((_, i) => i !== tailAt)
  const opener = rows.find((r) => r.kind === 'msg')
  return {
    kind: 'turn',
    at: turn.at,
    rows,
    tail,
    folded,
    // The block's clock is when its author started talking, which is what a Slack
    // header timestamp means. The conclusion can land minutes later.
    ts: ((opener && opener.msg) || (tail && tail.msg) || {}).ts || '',
  }
}

// ─── Markdown ────────────────────────────────────────────────────────────────
//
// The host exports no markdown renderer through the module map (only the
// protocol helpers), so this is the minimal renderer §9.1 calls for: bold,
// italic, inline code, fenced code, headings, lists, blockquotes, links.
//
// It builds React elements and never touches innerHTML, and the link pattern
// admits only http(s) and root-relative targets — so agent output cannot smuggle
// a `javascript:` href into the page.

const MD_INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\((?:https?:\/\/[^)\s]+|\/[^)\s]*)\))/g

const CODE_INLINE = {
  background: C.bg,
  border: hair(C.border),
  borderRadius: R.sm,
  padding: sp(S.hair, S.x1),
  fontFamily: MONO,
  fontSize: QUIET_PX,
}

/** A gateway session key: what a crew writes when it names a thread it opened. */
const SESSION_KEY = /^(?:chat|td)-[A-Za-z0-9]+-\d+$/

/**
 * Prose the reader should not have to decode (§rev9.1 finding 1).
 *
 * A receipt used to read "opened thread: … —— `chat-9301-1700004001` (under `Trading
 * Desk/threads` in the sidebar)", which hands a reader two of our internal facts: a session key
 * and a sidebar path. rev8's prompt work stopped new messages carrying them; this is
 * the rendering-layer floor under the HISTORY, which cannot be rewritten.
 *
 * Shape-based, not a word list: a parenthetical that mentions a folder path is a
 * filing instruction, whoever wrote it and in whichever bracket style.
 */
const SIDEBAR_ASIDE = /[（(][^）)]{0,60}Trading Desk\/[^）)]{0,60}[）)]/g

function stripInternalAsides(text) {
  return String(text == null ? '' : text).replace(SIDEBAR_ASIDE, '')
}

function mdInline(text, base, onOpenSession) {
  const src = String(text == null ? '' : text)
  const re = new RegExp(MD_INLINE.source, 'g')
  const out = []
  let last = 0
  let n = 0
  let m = re.exec(src)
  while (m) {
    if (m.index > last) out.push(src.slice(last, m.index))
    const key = `${base}i${n}`
    n += 1
    if (m[1]) {
      const code = m[1].slice(1, -1)
      // A session key is a door, not a string to read. Rendered as the one thing a
      // reader can do with it, with the key itself in the tooltip for anyone who
      // needs it. Without a handler it still reads as an ordinary code span rather
      // than a button that does nothing.
      // A session key never reads as prose, handler or no handler: with one it is a
      // door, without one it is named in words with the key kept in the tooltip. The
      // panel is the case without -- offering to open the thread you are already
      // reading would be a button that does nothing.
      if (SESSION_KEY.test(code) && !onOpenSession) {
        out.push(_jsx('span', {
          className: 'td-keychip',
          title: code,
          style: { color: C.muted, fontSize: QUIET_PX },
          children: t('this_thread'),
        }, key))
      } else if (SESSION_KEY.test(code) && onOpenSession) {
        out.push(_jsx('button', {
          type: 'button',
          className: 'td-quiet-btn td-keychip',
          title: code,
          onClick: () => onOpenSession(code),
          style: {
            border: hair(C.border),
            borderRadius: R.pill,
            background: C.bg,
            color: C.text,
            font: 'inherit',
            fontSize: QUIET_PX,
            fontWeight: W.medium,
            padding: sp(S.hair, S.x2),
            cursor: 'pointer',
          },
          children: `↗ ${t('reply_open').replace(' ›', '')}`,
        }, key))
      } else {
        out.push(_jsx('code', { style: CODE_INLINE, children: code }, key))
      }
    } else if (m[2]) {
      out.push(_jsx('strong', { style: { fontWeight: 700 }, children: m[2].slice(2, -2) }, key))
    } else if (m[3]) {
      out.push(_jsx('em', { children: m[3].slice(1, -1) }, key))
    } else {
      const cut = m[4].indexOf('](')
      out.push(
        _jsx(
          'a',
          {
            href: m[4].slice(cut + 2, -1),
            target: '_blank',
            rel: 'noreferrer noopener',
            style: { color: C.accent, textDecoration: 'none' },
            children: m[4].slice(1, cut),
          },
          key,
        ),
      )
    }
    last = m.index + m[0].length
    m = re.exec(src)
  }
  if (last < src.length) out.push(src.slice(last))
  return out
}

const MD_LIST = /^\s*([-*]|\d+[.)])\s+(.*)$/
const MD_HEAD = /^(#{1,4})\s+(.*)$/
const MD_QUOTE = /^\s*>\s?/
const MD_FENCE = /^```/

function mdBlocks(text) {
  const lines = String(text == null ? '' : text).split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (MD_FENCE.test(line.trim())) {
      const buf = []
      i += 1
      while (i < lines.length && !MD_FENCE.test(lines[i].trim())) {
        buf.push(lines[i])
        i += 1
      }
      i += 1
      out.push({ t: 'code', text: buf.join('\n') })
      continue
    }
    if (!line.trim()) {
      i += 1
      continue
    }
    const head = line.match(MD_HEAD)
    if (head) {
      out.push({ t: 'head', text: head[2] })
      i += 1
      continue
    }
    if (MD_QUOTE.test(line)) {
      const buf = []
      while (i < lines.length && MD_QUOTE.test(lines[i])) {
        buf.push(lines[i].replace(MD_QUOTE, ''))
        i += 1
      }
      out.push({ t: 'quote', text: buf.join('\n') })
      continue
    }
    const li = line.match(MD_LIST)
    if (li) {
      const ordered = !/^[-*]$/.test(li[1])
      const buf = []
      while (i < lines.length) {
        const next = lines[i].match(MD_LIST)
        if (!next || !/^[-*]$/.test(next[1]) !== ordered) break
        buf.push(next[2])
        i += 1
      }
      out.push({ t: 'list', ordered, items: buf })
      continue
    }
    const buf = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !MD_FENCE.test(lines[i].trim()) &&
      !MD_LIST.test(lines[i]) &&
      !MD_QUOTE.test(lines[i]) &&
      !MD_HEAD.test(lines[i])
    ) {
      buf.push(lines[i])
      i += 1
    }
    out.push({ t: 'p', text: buf.join('\n') })
  }
  return out
}

export const BODY_TEXT = { fontSize: `${BODY_PX}px`, lineHeight: BODY_LH, color: C.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }

/**
 * A "thread receipt": the line a manager writes in the main conversation to say it
 * opened a thread (§15.2).
 *
 * A thread receipt does not belong in the main conversation. The reply bar under the
 * anchor message already says a thread exists, so the sentence saying it again is
 * one fact told twice -- and an older receipt written before the crews were
 * tightened says it in a paragraph, which pushes the conversation the reader came
 * for off screen.
 *
 * Recognised by SHAPE, not by a phrase list: the first line, once the session key and
 * any filing aside are stripped, opens with "opened a thread" in either language. The
 * title is what follows, cut at the em-dash or the full stop the narration starts
 * after. Returns null for anything else, including a message that merely MENTIONS a
 * thread -- "in the thread macro said…" is a report, not a receipt.
 */
const RECEIPT_HEAD = [
  /^已开\s*thread\s*[：:]\s*(.+)$/,
  /^已开线程\s*[：:]\s*(.+)$/,
  /^opened\s+(?:a\s+)?thread\s*[：:]\s*(.+)$/i,
]

export function receiptShape(text) {
  const first = stripInternalAsides(String(text == null ? '' : text)).split('\n')[0].trim()
  for (const re of RECEIPT_HEAD) {
    const m = re.exec(first)
    if (!m) continue
    // The title runs to the em-dash the key used to follow, or to the first full
    // stop, whichever comes first. `。` and `.` both end a sentence here.
    const rest = m[1].trim()
    const cut = rest.search(/\s*——|\s+--\s|。|\.\s|$/)
    const title = rest.slice(0, cut >= 0 ? cut : rest.length).replace(/[`\s]+$/, '').trim()
    if (!title) return null
    return { title }
  }
  return null
}

/** The session keys a message names, which is how a receipt is tied to its thread. */
export function keysNamed(text) {
  const out = []
  const re = /\b((?:chat|td)-[A-Za-z0-9]+-\d+)\b/g
  let m = re.exec(String(text == null ? '' : text))
  while (m) { if (!out.includes(m[1])) out.push(m[1]); m = re.exec(String(text)) }
  return out
}

/**
 * A message body.
 *
 * The host's own `MarkdownRenderer` draws it when it is reachable — the same
 * component the dashboard's chat transcript uses, so a table, a task list, a
 * strikethrough and a fenced diff all render here the way they render there.
 * The self-drawn block walker below is the FALLBACK, kept because it must still
 * work when the app is opened outside a host that publishes its UI kit: it knows
 * six block kinds, which is what made a table arrive as literal pipes.
 *
 * Borrowing it is safe on this app's own palette because the component sets no
 * font-family anywhere and takes every colour from a CSS custom property — the
 * container in `theme.mjs` pins those six variables to this app's tokens, so the
 * host's theme cannot reach in and darken an inline-code chip on a white card.
 */
export function MdBody({ text, onOpenSession }) {
  const kit = uiKit()
  const Renderer = kit && kit.MarkdownRenderer
  const source = stripInternalAsides(text)
  const own = _jsx(MdBodySelf, { source, onOpenSession })
  if (!Renderer) return own
  return _jsx(HostBoundary, {
    resetKey: source,
    fallback: own,
    children: _jsx('div', {
      className: 'td-md td-md-host',
      style: { minWidth: 0, fontSize: `${READ_PX}px`, lineHeight: `${READ_LH_PX}px` },
      children: _jsx(Renderer, {
        content: source,
        // The app resolves a session key its own way (§11.1), so the chip's
        // activation stays with the app rather than the host's router.
        onSessionOpen: onOpenSession,
        collapseDiffs: true,
      }),
    }),
  })
}

/** The app's own markdown, and the fallback when the host's renderer throws. */
function MdBodySelf({ source, onOpenSession }) {
  const blocks = mdBlocks(source)
  return _jsx('div', {
    className: 'td-md',
    // The leading is set here as well as on each block, so anything nested that
    // does not carry BODY_TEXT still inherits the main chat's leading rather than
    // the page's default 1.5.
    style: { minWidth: 0, lineHeight: BODY_LH },
    children: blocks.map((b, n) => {
      const key = `b${n}`
      if (b.t === 'code') {
        return _jsx(
          'pre',
          {
            style: {
              margin: sp(S.x1, '0'),
              padding: S.x2,
              background: C.bg,
              border: hair(C.border),
              borderRadius: R.md,
              overflowX: 'auto',
              fontFamily: MONO,
              fontSize: QUIET_PX,
              lineHeight: 1.6,
              color: C.text,
            },
            children: b.text,
          },
          key,
        )
      }
      if (b.t === 'head') {
        return _jsx(
          'div',
          { style: { ...BODY_TEXT, fontWeight: 700, margin: sp(S.x2, '0', S.half) }, children: mdInline(b.text, key, onOpenSession) },
          key,
        )
      }
      if (b.t === 'quote') {
        return _jsx(
          'div',
          {
            style: { ...BODY_TEXT, color: C.muted, borderLeft: rule(C.border), paddingLeft: S.x2, margin: sp(S.x1, '0') },
            children: mdInline(b.text, key, onOpenSession),
          },
          key,
        )
      }
      if (b.t === 'list') {
        return _jsx(
          b.ordered ? 'ol' : 'ul',
          {
            style: {
              ...BODY_TEXT,
              whiteSpace: 'normal',
              margin: sp(S.x2, '0'),
              paddingLeft: S.x8,
              // The dashboard's CSS reset strips list markers from every ol/ul,
              // so a numbered list rendered as indented lines with no numbers —
              // which loses the ORDER, the only thing an ordered list carries.
              listStyle: b.ordered ? 'decimal outside' : 'disc outside',
            },
            children: b.items.map((it, k) =>
              _jsx('li', { style: { margin: sp(S.x1, '0'), lineHeight: 1.625 }, children: mdInline(it, `${key}l${k}`, onOpenSession) }, `${key}l${k}`),
            ),
          },
          key,
        )
      }
      return _jsx('div', { style: { ...BODY_TEXT, margin: sp(S.x1, '0') }, children: mdInline(b.text, key, onOpenSession) }, key)
    }),
  })
}

// ─── OPTIONS markers ─────────────────────────────────────────────────────────

/**
 * The host's own parser when the module map carries it — its grammar handles a
 * bracket inside a label, which is exactly the case a short regex gets wrong.
 * The fallback covers a gateway whose map predates the protocol export.
 */
export function parseChatOptions(content) {
  const sdk = appSdk()
  if (sdk && typeof sdk.parseOptions === 'function') {
    try {
      return sdk.parseOptions(String(content == null ? '' : content))
    } catch (err) {
      /* fall through to the local reading */
    }
  }
  const src = String(content == null ? '' : content)
  const re = /\[OPTIONS?:\s*([^\]]*)\]/gi
  let last = null
  let m = re.exec(src)
  while (m) {
    last = m
    m = re.exec(src)
  }
  if (!last) return { text: src, options: [], multi: true }
  const sep = last[1].includes('|') ? '|' : ','
  return {
    text: src.replace(/\[OPTIONS?:\s*[^\]]*\]/gi, '').trim(),
    options: last[1].split(sep).map((o) => o.trim()).filter(Boolean),
    multi: /^\[OPTIONS:/i.test(last[0]),
  }
}

/** The choices currently on offer, if any. */
export function followUpsFor(messages, running) {
  if (running) return []
  const list = Array.isArray(messages) ? messages : []
  const sdk = appSdk()
  if (sdk && typeof sdk.deriveFollowUpOptions === 'function') {
    try {
      const d = sdk.deriveFollowUpOptions(list, false)
      if (d && Array.isArray(d.followUpOptions)) return d.followUpOptions
    } catch (err) {
      /* fall through */
    }
  }
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const m = list[i]
    const role = String((m && m.role) || '')
    // A stop event and an empty row are not the agent's answer, so neither closes
    // the offer the answer before them made.
    if (isStopEvent(m) || !String((m && m.content) || '').trim()) continue
    if (role === 'user' || role === 'queued') return []
    if (role === 'assistant') return parseChatOptions(m.content).options
  }
  return []
}

/**
 * What the foot of the transcript owes the reader after they press Enter.
 *
 * Two facts, in the order they become true: the message is IN the conversation,
 * and the other side is working on it. Both were readable only from the
 * composer's placeholder — the wrong place, because it describes the box you type
 * into rather than the message you already sent, and it says the same thing
 * whether you have sent anything or not.
 *
 * `sent` is the landing, so it waits for the optimistic row to be replaced by the
 * real one and is dropped the moment anything comes back — a reply is its own
 * proof of delivery, and a mark under every past line would be noise.
 *
 * `working` is the turn being in flight. It is suppressed once a `streaming` row
 * exists, because that row IS the signal: text arriving under the member's name
 * says more than a line claiming text is coming.
 */
export function tailMarkers(messages, running, unsent) {
  const list = Array.isArray(messages) ? messages : []
  const last = list.length ? list[list.length - 1] : null
  const role = String((last && last.role) || '')
  return {
    sent: !unsent && role === 'user',
    working: !!running && role !== 'streaming',
  }
}

// ─── Process rows: one quiet fold ────────────────────────────────────────────

/** What a tool row was for, in one line. */
function toolLabel(m) {
  const purpose = m && m.meta && typeof m.meta.purpose === 'string' ? m.meta.purpose.trim() : ''
  if (purpose) return purpose
  const first = stripEnvelope((m && m.content) || '').text.split('\n')[0]
  return first.replace(/^🔧\s*/, '').replace(/^Running:\s*/, '').trim() || 'tool call'
}

function toolOutput(m) {
  const out = m && m.meta && typeof m.meta.output === 'string' ? m.meta.output : ''
  const body = stripEnvelope((m && m.content) || '').text.split('\n').slice(1).join('\n')
  return (out || body).trim()
}

export const FOLD_LINE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: S.x1,
  background: 'transparent',
  border: 'none',
  padding: sp(S.half, '0'),
  margin: sp(S.half, '0'),
  cursor: 'pointer',
  color: C.muted,
  fontSize: QUIET_PX,
  fontFamily: 'inherit',
}

/**
 * A message the reader should not have to read, folded (§rev7 P0#2).
 *
 * Same grey line as the machinery fold, because it is the same idea: this row is
 * how the work was set up, not part of the conversation. Nothing is removed --
 * one click gives the whole text, rendered as markdown like any other message, so
 * the brief with its file paths is still there for anyone who wants it.
 */
export function FoldedBody({ text, label, hint }) {
  const [open, setOpen] = useState(false)
  // The table's entries are thunks so the label follows the language switch; a
  // string captured at module load would freeze in whatever language was active
  // when the module was imported.
  const word = typeof label === 'function' ? label() : label
  const tip = typeof hint === 'function' ? hint() : hint
  return _jsxs('div', {
    style: { minWidth: 0 },
    children: [
      _jsxs('button', {
        className: 'td-quiet-btn td-fold td-protofold',
        onClick: () => setOpen((v) => !v),
        title: open ? `${t('walk_close')} · ${word}` : tip,
        style: FOLD_LINE,
        children: [
          _jsx('span', { style: { fontSize: F.micro }, children: open ? '▾' : '▸' }),
          _jsx('span', { children: word }),
        ],
      }),
      open ? _jsx(MdBody, { text }) : null,
    ],
  })
}

/** Several bars under one message stack, and stay on the message's own text
 *  column -- a second indent would read as belonging to something else. */
export const BAR_STACK = { display: 'flex', flexDirection: 'column', gap: S.half }

export const FOLD_WORD = {
  brief: { label: () => t('fold_brief'), hint: () => t('fold_brief_hint') },
  protocol: { label: () => t('fold_protocol'), hint: () => t('fold_protocol_hint') },
}

/**
 * One walk, behind one grey line — the machinery a member ran and the narration
 * they wrote while running it (§13.1).
 *
 * There is deliberately ONE fold component and one vocabulary. Two grey lines that
 * look identical but read differently ("1 tool call" here, "3 steps" there) is
 * the same inconsistency the reader called messy, and to someone who does not want
 * to read either, a paragraph of narration and a tool call are the same thing: a
 * step. So everything is counted in steps.
 *
 * Collapsed by default, which is also how reasoning stays hidden (§9.1) without a
 * second switch to find. Expanded it is plain text in document order — prose as
 * prose, a label and output per call, reasoning in italics. No coloured rail and no
 * status fill down the left of a reply: that decoration is what the reader rejected
 * four rounds running.
 */
export function WalkFold({ steps }) {
  const [open, setOpen] = useState(false)
  const list = steps || []
  if (!list.length) return null

  return _jsxs('div', {
    style: { minWidth: 0 },
    children: [
      _jsxs('button', {
        className: 'td-quiet-btn td-fold',
        onClick: () => setOpen((v) => !v),
        title: open ? t('walk_close') : t('walk_open'),
        style: FOLD_LINE,
        children: [
          _jsx('span', { style: { fontSize: F.micro }, children: open ? '▾' : '▸' }),
          _jsx('span', { children: t('walk_fold', { n: list.length }) }),
        ],
      }),
      open
        ? _jsx('div', {
            style: { margin: sp(S.half, '0', S.x2), display: 'flex', flexDirection: 'column', gap: S.x2 },
            children: list.map((s, n) => {
              const key = `p${n}`
              if (s.prose != null) return _jsx(MdBody, { text: s.prose }, key)
              const r = s.row
              if (r.role === 'thinking') {
                return _jsx(
                  'div',
                  {
                    style: { fontSize: QUIET_PX, lineHeight: 1.6, color: C.muted, fontStyle: 'italic', whiteSpace: 'pre-wrap' },
                    children: String(r.content || '').trim(),
                  },
                  key,
                )
              }
              const out = toolOutput(r)
              return _jsxs(
                'div',
                {
                  style: { minWidth: 0 },
                  children: [
                    _jsx('div', {
                      className: 'td-mono',
                      style: { fontSize: QUIET_PX, color: C.muted, fontFamily: MONO, wordBreak: 'break-word' },
                      children: toolLabel(r),
                    }),
                    out
                      ? _jsx('pre', {
                          style: {
                            margin: sp(S.x1, '0', '0'),
                            padding: sp(S.x1, S.x2),
                            maxHeight: L.scrollCap,
                            overflow: 'auto',
                            background: C.bg,
                            border: hair(C.border),
                            borderRadius: R.sm,
                            fontFamily: MONO,
                            fontSize: QUIET_PX,
                            lineHeight: 1.55,
                            color: C.muted,
                            whiteSpace: 'pre-wrap',
                          },
                          children: out.length > 4000 ? `${out.slice(0, 4000)}\n…` : out,
                        })
                      : null,
                  ],
                },
                key,
              )
            }),
          })
        : null,
    ],
  })
}

/**
 * Flatten what a fold holds into steps.
 *
 * One step per paragraph of narration and one per tool call or reasoning trace, so
 * the count means the same thing wherever the line appears: a run of three calls
 * with no reply yet reads `3 steps`, exactly as three calls inside a turn do.
 */
export function walkSteps(items) {
  const out = []
  ;(items || []).forEach((it) => {
    if (it.kind === 'msg') out.push({ prose: parseChatOptions(it.body).text })
    else (it.rows || []).forEach((r) => out.push({ row: r }))
  })
  return out
}

/** A row this view does not draw in full, and a day boundary. */
export function QuietLine({ text, tone, mono }) {
  return _jsx('div', {
    style: {
      fontSize: QUIET_PX,
      lineHeight: 1.6,
      color: tone === 'danger' ? C.danger : tone === 'warn' ? C.warn : C.muted,
      fontFamily: mono ? MONO : 'inherit',
      padding: sp(S.x1, '0'),
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    },
    children: text,
  })
}

/** Slack's date break: a pill on a rule, and it sticks to the top while you read
 *  the day under it. */
export function DayDivider({ label }) {
  return _jsxs('div', {
    className: 'td-day',
    style: {
      position: 'sticky',
      top: 0,
      zIndex: 3,
      display: 'flex',
      alignItems: 'center',
      gap: S.x2,
      padding: sp(S.x2, ROW_PAD, S.x1),
      fontSize: `${BODY_PX}px`,
      maxWidth: COLUMN,
    },
    children: [
      _jsx('div', { style: { height: S.hair, flex: 1, background: C.border } }),
      _jsx('span', {
        style: {
          fontSize: STAMP_PX,
          fontWeight: 700,
          color: C.text,
          whiteSpace: 'nowrap',
          background: C.card,
          border: hair(C.border),
          borderRadius: R.pill,
          padding: sp(S.x1, S.x3),
        },
        children: label,
      }),
      _jsx('div', { style: { height: S.hair, flex: 1, background: C.border } }),
    ],
  })
}

// ─── Composer ────────────────────────────────────────────────────────────────

const COMPOSER_MAX_H = 200

/**
 * Typing is never blocked while the agent works: `POST /api/chat` on a running
 * slot is queued by the gateway and answered immediately, so the message waits
 * its turn instead of being refused or starting a second one.
 */
export function Composer({ draft, setDraft, running, onSend, sendError, placeholder }) {
  const ref = useRef(null)

  const grow = useCallback(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_H)}px`
  }, [])

  useEffect(grow, [draft, grow])

  const submit = () => {
    const text = draft.trim()
    if (!text) return
    setDraft('')
    onSend(text)
  }

  const onKeyDown = (e) => {
    // A CJK composition ends on Enter. Sending there would post a half-typed
    // sentence and swallow the candidate the user was choosing.
    if (e.key !== 'Enter' || e.shiftKey) return
    if (e.nativeEvent && e.nativeEvent.isComposing) return
    e.preventDefault()
    submit()
  }

  return _jsxs('div', {
    style: { borderTop: hair(C.border), padding: sp(S.x2, ROW_PAD, S.x3) },
    children: [
      sendError ? _jsx(QuietLine, { text: sendError, tone: 'danger' }) : null,
      _jsxs('div', {
        className: 'td-composer td-box',
        style: {
          borderRadius: R.lg,
          background: C.bg,
          padding: S.x2,
          display: 'flex',
          flexDirection: 'column',
          gap: S.x1,
          fontSize: `${BODY_PX}px`,
          // The box spans the column it sits in. It was capped at the
          // conversation's own width on the reasoning that "a composer as wide as
          // the window under an 810px column reads as an empty runway" — but the
          // cap is what produced a runway: with the thread panel closed the
          // middle column is ~1240px, so an 868px box left ~370px of white to the
          // right of it with a border floating mid-air. The measure exists to keep
          // a LINE trackable, which is a fact about reading a paragraph and not
          // about the width of a text field.
        },
        children: [
          _jsx('textarea', {
            ref,
            className: 'td-input',
            rows: 1,
            value: draft,
            onChange: (e) => setDraft(e.target.value),
            onKeyDown,
            placeholder: running ? t('composer_queued') : placeholder || t('composer_plain'),
            style: {
              width: '100%',
              resize: 'none',
              border: 'none',
              outline: 'none',
              background: 'transparent',
              color: C.text,
              fontFamily: 'inherit',
              fontSize: `${BODY_PX}px`,
              lineHeight: BODY_LH,
              maxHeight: `${COMPOSER_MAX_H}px`,
              overflowY: 'auto',
            },
          }),
          // Slack's toolbar row inside the box: attachments on the left, send on
          // the right. The `+` is deliberately dead — an app cannot attach a file
          // (that is the host composer's @file), and a button that looks live and
          // does nothing is worse than one that says it is not.
          _jsxs('div', {
            style: { display: 'flex', alignItems: 'center', gap: S.x2 },
            children: [
              _jsx('button', {
                disabled: true,
                title: t('attach_tip'),
                style: {
                  background: 'transparent',
                  border: hair(C.border),
                  borderRadius: R.md,
                  color: C.borderStrong,
                  width: L.glyphBtn,
                  height: L.glyphBtn,
                  fontSize: F.quiet,
                  lineHeight: 1,
                  fontFamily: 'inherit',
                  cursor: 'default',
                },
                children: '+',
              }),
              _jsx('div', { style: { marginLeft: 'auto' } }),
              _jsx('button', {
                onClick: submit,
                disabled: !draft.trim(),
                title: running ? t('composer_queued') : t('send'),
                style: {
                  background: draft.trim() ? C.accent : 'transparent',
                  color: draft.trim() ? C.accentFg : C.muted,
                  border: draft.trim() ? 'none' : hair(C.border),
                  borderRadius: R.md,
                  padding: sp(S.x1, S.x3),
                  fontSize: F.quiet,
                  fontFamily: 'inherit',
                  cursor: draft.trim() ? 'pointer' : 'default',
                },
                children: running ? t('queue') : t('send'),
              }),
            ],
          }),
        ],
      }),
      // Slack keeps the shortcut line under the box, not in it. Said plainly
      // rather than imitated: the capabilities named in the tooltip are the host
      // composer's and this app has no access to them (ARCHITECTURE.md §9.1).
      _jsx('div', {
        style: { display: 'flex', justifyContent: 'flex-end', padding: sp(S.x1, S.half, '0') },
        children: _jsx('span', {
          style: { fontSize: F.meta, color: C.muted },
          title: t('composer_more_tip'),
          children: t('composer_hint'),
        }),
      }),
    ],
  })
}

/** The choices an agent offered. One click sends that text (ARCHITECTURE.md §9.1). */
export function FollowUps({ options, onPick }) {
  if (!options || !options.length) return null
  return _jsx('div', {
    className: 'td-chips',
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: S.x1,
      padding: sp(S.x2, ROW_PAD, 0),
      fontSize: `${BODY_PX}px`,
      maxWidth: `calc(${ROW_PAD}px + ${COLUMN})`,
    },
    children: options.map((o, n) =>
      _jsx(
        'button',
        {
          onClick: () => onPick(o),
          style: {
            background: C.accentSubtle,
            color: C.text,
            border: hair(C.border),
            borderRadius: R.pill,
            padding: sp(S.x1, S.x3),
            fontSize: F.quiet,
            fontFamily: 'inherit',
            cursor: 'pointer',
            maxWidth: '100%',
          },
          children: o,
        },
        `o${n}`,
      ),
    ),
  })
}

export function ChatHead({ member, agent, onProfile, onReset, extra }) {
  const kind = memberKind(member)
  return _jsxs('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: S.x3,
      padding: sp(S.x3, S.x4),
      borderBottom: hair(C.border),
    },
    children: [
      _jsx(Avatar, { letter: memberLetter(member), kind }),
      _jsxs('div', {
        style: { minWidth: 0 },
        children: [
          _jsxs('div', {
            style: { display: 'flex', alignItems: 'baseline', gap: S.x2, minWidth: 0 },
            children: [
              // ONE name on the header (§rev9.1 finding 2). The agent id used to sit
              // beside it, so a reader saw the same colleague twice under two names,
              // one of them an internal id. It is the name's tooltip now, and the
              // profile page still states it in full.
              _jsx('span', {
                style: { fontSize: F.body, fontWeight: W.medium, color: C.text },
                title: agent || undefined,
                children: member.name,
              }),
            ],
          }),
          _jsxs('div', {
            style: {
              display: 'flex',
              alignItems: 'center',
              gap: S.x1,
              fontSize: F.micro,
              color: C.muted,
            },
            children: [
              _jsx(Dot, { state: member.state }),
              _jsx('span', { children: phrase(member.state_msg) || member.title || '' }),
            ],
          }),
        ],
      }),
      _jsxs('div', {
        style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: S.x2 },
        children: [
          extra || null,
          _jsx(ResetButton, { memberId: member.id, onReset }, member.id),
          _jsx(Ghost, { onClick: onProfile, children: t('view_profile') }),
        ],
      }),
    ],
  })
}



export const GUTTER_STYLE = {
  paddingLeft: `${ROW_PAD + ROW_GUTTER}px`,
  paddingRight: `${ROW_PAD}px`,
  minWidth: 0,
  fontSize: `${BODY_PX}px`,
  // Same text column as a message body: the row's padding, the gutter it starts
  // after, and the measure — so a tool output block wraps where the prose above
  // it wraps.
  maxWidth: `calc(${ROW_PAD}px + ${COLUMN})`,
}
