/** The Chat page: member rail, transcript, thread panel. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { phrase, t as say } from './i18n.mjs'
import { SHAPE, ChatBoundary, clampPanel, readShell, writeShell, asQuote, countSent, createThread, load, markThreadRouteMissing, postJson, resolveSlotKey, sendToSlot, threadRouteMissing, useLoader, useQuote, useSession, useTranscript } from './data.mjs'
import { BAR_STACK, BODY_TEXT, COLUMN, CONVO_ROLE, ChatHead, Composer, DayDivider, FOLD_LINE, FOLD_WORD, FoldedBody, FollowUps, GUTTER_STYLE, MdBody, QUIET_PX, QuietLine, ROW_GUTTER, ROW_PAD, RowActions, STAMP_PX, SlackRow, WalkFold, chatItems, followUpsFor, keysNamed, receiptShape, parseChatOptions, quietText, rowTime, rowTimeTitle, senderMember, stripEnvelope, walkSteps } from './parts.mjs'
import { Avatar, C, Card, Dot, F, Ghost, L, LoadError, Loading, MONO, Notice, Pill, R, S, SHADOW, StaleBar, W, agentFor, findMember, hair, memberKind, memberLetter, sp } from './theme.mjs'

/**
 * The conversation.
 *
 * Reads `GET /api/chat/slots/{key}`, sends with `POST /api/chat`, and draws every
 * row itself. The reference image is design/refs/slack-ref-thread-reply.png: one
 * text column, an author line only when the speaker or the hour changes, the
 * machinery folded into a grey line, and the thread entry sitting under the
 * message that opened it.
 */
/**
 * The main conversation: the member's own session, plus the reply bars.
 *
 * A member with no session bound has nothing to read, and that is not an error —
 * it has simply not been given work yet.
 */
function TdChat({ member, agent, members, threads, threadFor, openThreadId, onOpenThread, onStartThread, onThreadsPlaced, onOpenSession, onReceipts }) {
  if (!member.slot_key) {
    return _jsx('div', {
      style: {
        flex: 1,
        minHeight: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: S.x8,
        textAlign: 'center',
      },
      children: _jsxs('div', {
        children: [
          _jsx('div', { style: { color: C.text, fontSize: F.quiet, marginBottom: S.x1 }, children: say('chat_empty_title') }),
          _jsx('div', {
            style: { color: C.muted, fontSize: F.meta },
            children: say('chat_empty_body', { name: member.name }),
          }),
        ],
      }),
    })
  }
  return _jsx(ChatStream, {
    slotKey: member.slot_key,
    member,
    agent,
    members,
    threads,
    threadFor,
    openThreadId,
    onOpenThread,
    onStartThread,
    onThreadsPlaced,
    onOpenSession,
    onReceipts,
  }, member.slot_key)
}

/**
 * One session's conversation: read it, draw it, send to it (ARCHITECTURE.md §11.2).
 *
 * Pointed at a member's own session this is the main chat; pointed at a thread's
 * clone session it is the thread panel. Same rows, same fold, same chips, same
 * markdown, same queue-while-running — a thread is not a different kind of
 * conversation, it is the same conversation with another session behind it, so
 * there is one implementation and the caller says which session.
 *
 * The thread wiring (`threadFor` and friends) is the main chat's alone: a thread
 * does not open threads of its own, and passing nothing simply draws no reply
 * bars.
 */
function ChatStream({ slotKey, member, agent, members, threads, threadFor, openThreadId, onOpenThread, onStartThread, onThreadsPlaced, onOpenSession, onReceipts, hideSeed }) {
  const box = { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }
  // Creates the session behind a bound key and binds the member's agent to it.
  // Still required for the main chat: `POST /api/chat` would create it too, but
  // with whatever agent the send carries, and the transcript read is a 404 until
  // something does. For a thread the session already exists, so the probe answers
  // 200 and nothing is created.
  useSession(slotKey, agent)
  const t = useTranscript(slotKey)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState([])
  const [sendError, setSendError] = useState('')
  // Which row is waiting on `POST /thread`, and what went wrong if it did. Keyed
  // by the row's own stamp so two rows cannot share one spinner.
  const [starting, setStarting] = useState('')
  const [threadError, setThreadError] = useState('')
  const scroller = useRef(null)
  const atBottom = useRef(true)
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  const quote = useQuote(scroller)

  const landed = countSent(t.messages)
  const waiting = pending.filter((p) => landed <= p.base)

  // Drop a placeholder once its row is really in the transcript, so the list does
  // not grow for the life of the session.
  useEffect(() => {
    if (pendingRef.current.some((p) => landed > p.base)) {
      setPending((list) => list.filter((p) => landed <= p.base))
    }
  }, [landed])

  const send = useCallback(
    async (text) => {
      if (!slotKey) return
      setSendError('')
      const id = `p${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const base = countSent(t.messages) + pendingRef.current.length
      setPending((list) => [...list, { id, text, base }])
      const res = await sendToSlot(slotKey, agent, text)
      if (res && res.error) {
        setPending((list) => list.filter((p) => p.id !== id))
        setSendError(res.error)
        // Hand the text back rather than losing it, unless something else has
        // been typed in the meantime.
        setDraft((d) => d || text)
        return
      }
      t.refresh()
    },
    [slotKey, agent, t],
  )

  /**
   * Open a thread on a row that has none (§rev7 B).
   *
   * The anchor is sent as rev5.1 ruled — `main_msg` from the gateway-minted
   * `meta.mid`, `ts` verbatim — and the draft, if there is one, becomes the
   * thread's first message and is cleared from the composer, because leaving it
   * behind would let the same sentence be sent twice.
   */
  const startThread = useCallback(
    async (m) => {
      if (!onStartThread || starting) return
      const key = String(m.ts || '')
      const anchor = {
        main_msg: (m.meta && m.meta.mid) || '',
        ts: m.ts || '',
        preview: stripEnvelope(m.content).text.slice(0, 80),
      }
      const seed = draft.trim()
      setStarting(key)
      setThreadError('')
      const res = await onStartThread(anchor, seed)
      setStarting('')
      if (res && res.missing) {
        // The route is absent from this build. Say it once here; every row's
        // tooltip carries the explanation from now on.
        setThreadError(say('thread_route_note'))
        return
      }
      if (res && res.error) {
        setThreadError(res.error)
        return
      }
      if (seed) setDraft('')
    },
    [onStartThread, starting, draft],
  )

  // `threadFor` is the main chat's alone, so its absence is what says this stream
  // is a thread panel -- the surface whose first user row is a brief written for
  // the clone rather than a line the reader typed.
  const seedFold = !threadFor
  const items = useMemo(
    () => chatItems(t.messages, { seedFold, seedHide: seedFold && !!hideSeed }),
    [t.messages, seedFold, hideSeed],
  )
  /**
   * Which row carries which reply bars — decided once, for the whole transcript,
   * because that is the only scope in which "never twice" can be enforced (§13.2).
   *
   * Two rules live here. A thread gets ONE bar: keyed on its slot_key, the first
   * row that anchors it wins and any later anchor for the same session is dropped
   * rather than drawn again, so a backend that hands back two anchors for one
   * thread still reads as one thread. And only a VISIBLE row can carry a bar: a
   * paragraph folded into the steps fold is not a place a reader can see, so a thread anchored
   * there stays unplaced and reaches them through the header entry instead.
   */
  const bars = useMemo(() => {
    const byKey = new Map()
    const ids = []
    if (!threadFor) return { byKey, ids }
    const seen = new Set()
    items.forEach((it) => {
      const m = it.kind === 'turn' ? it.tail && it.tail.msg : it.kind === 'msg' ? it.msg : null
      if (!m || !CONVO_ROLE[String(m.role || '')]) return
      const mine = []
      ;(threadFor(m) || []).forEach((th) => {
        const key = threadKey(th)
        if (seen.has(key)) return
        seen.add(key)
        mine.push(th)
        if (!ids.includes(key)) ids.push(key)
      })
      if (mine.length) byKey.set(`${it.kind}${it.at}`, mine)
    })
    return { byKey, ids }
  }, [items, threadFor])
  /**
   * Receipts to fold away, and the text each one carries (§15.2).
   *
   * The condition is the contract's: a receipt is hidden only when the thread it
   * announces already has its reply bar on ANOTHER row. If the receipt is itself the
   * anchor, hiding it would take the only way into that thread with it -- so it
   * stays, and the duplication is the lesser fault.
   *
   * Nothing is discarded: the text goes up to the panel, which shows it above the
   * replies, so a historical receipt's paragraph of reasoning is still readable where
   * it belongs instead of in the middle of the conversation.
   */
  const receipts = useMemo(() => {
    const hide = new Set()
    const notes = {}
    if (!threadFor) return { hide, notes }
    const carrier = new Map()
    bars.byKey.forEach((ths, itemKey) => ths.forEach((th) => carrier.set(threadKey(th), itemKey)))
    items.forEach((it) => {
      const src = it.kind === 'turn' ? it.tail : it
      const m = src && src.msg
      if (!m || m.role !== 'assistant') return
      const shape = receiptShape(src.body !== undefined ? src.body : m.content)
      if (!shape) return
      const named = keysNamed(m.content)
      const mine = (threads || []).filter((th) => {
        const key = threadKey(th)
        return named.includes(th.slot_key) || named.includes(key) ||
          (th.title && shape.title && String(th.title).trim() === shape.title)
      })
      if (!mine.length) return
      const itemKey = `${it.kind}${it.at}`
      const elsewhere = mine.filter((th) => {
        const at = carrier.get(threadKey(th))
        return at && at !== itemKey
      })
      if (!elsewhere.length) return
      hide.add(itemKey)
      elsewhere.forEach((th) => { notes[threadKey(th)] = src.body !== undefined ? src.body : m.content })
    })
    return { hide, notes }
  }, [items, bars, threadFor, threads])

  const noteKey = Object.keys(receipts.notes).sort().join('|')
  useEffect(() => {
    if (onReceipts) onReceipts(receipts.notes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteKey, onReceipts])

  const placedIds = bars.ids
  const placedKey = placedIds.join('|')
  useEffect(() => {
    if (onThreadsPlaced) onThreadsPlaced(placedIds)
    // placedIds is derived from placedKey; depending on the key keeps this from
    // firing on every poll that returns the same set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placedKey, onThreadsPlaced])
  const follow = useMemo(() => followUpsFor(t.messages, t.running), [t.messages, t.running])
  const tail = t.messages.length ? String(t.messages[t.messages.length - 1].content || '').length : 0

  // Stay pinned to the newest row unless the reader has scrolled up to read.
  useEffect(() => {
    const el = scroller.current
    if (el && atBottom.current) el.scrollTop = el.scrollHeight
  }, [t.messages.length, tail, waiting.length])

  const onScroll = useCallback(() => {
    const el = scroller.current
    if (el) atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }, [])

  const rows = []

  if (t.error) rows.push(_jsx(StaleBar, { message: t.error, detail: t.detail }, 'stale'))

  if (t.hasMore) {
    rows.push(
      _jsx('button', {
        className: 'td-quiet-btn',
        onClick: t.widen,
        style: { ...FOLD_LINE, display: 'block', margin: sp(S.x1, 'auto'), maxWidth: COLUMN },
        children: say('load_older'),
      }, 'more'),
    )
  }

  /**
   * One conversation row, whether it came from a single message or from a whole
   * folded turn. Both shapes share every decision that matters — who spoke, which
   * reply bars hang under it, what the hover actions can do — so they share one
   * builder rather than two that drift.
   */
  const pushConvo = (it) => {
    const key = `${it.kind}${it.at}`
    // §15.2: the reply bar already said this. The row is not drawn at all.
    if (receipts.hide.has(key)) return
    const src = it.kind === 'turn' ? it.tail : it
    const m = src.msg
    const isUser = m.role === 'user'
    // `src.body` already has the relay envelope off it (§rev7 P0#2); the OPTIONS
    // marker is stripped too and re-offered as chips above the composer, so the
    // reader never sees `[sent by session …]` or `[OPTIONS: …]` as prose.
    const body = isUser ? src.body : parseChatOptions(src.body).text
    const threads = bars.byKey.get(key) || []
    const streaming = m.role === 'streaming'
    const folded = it.kind === 'turn' ? it.folded : []
    rows.push(
      _jsx(
        SlackRow,
        {
          member,
          agent,
          isUser,
          relay: src.relayed ? senderMember(src.sender, members) : null,
          relayed: src.relayed,
          timestamp: rowTime(it.kind === 'turn' ? it.ts : m.ts),
          timestampTitle: rowTimeTitle(it.kind === 'turn' ? it.ts : m.ts),
          cont: it.kind === 'turn' ? false : it.cont,
          actions: _jsx(RowActions, {
            onQuote: () => setDraft((d) => asQuote(body) + d),
            hasThread: threads.length > 0,
            starting: starting === String(m.ts || ''),
            // A thread panel draws no reply bars and opens no threads, so it
            // passes no `onStartThread`. That is what tells the two refusals
            // apart: no handler here means we are inside a panel and a thread
            // cannot nest, while the route flag means the gateway itself has no
            // `POST /thread`. Reported separately so the tooltip is true.
            nested: !threads.length && !onStartThread,
            unavailable: !threads.length && !!onStartThread && threadRouteMissing(),
            onOpenThread: threads.length
              ? () => onOpenThread(threads[0].id)
              : onStartThread
                ? () => startThread(m)
                : null,
          }),
          children: _jsxs(_Fragment, {
            children: [
              // The walk sits ABOVE the conclusion so that opening it reads
              // forwards: machinery, narration, then the answer it arrived at.
              folded.length ? _jsx(WalkFold, { steps: walkSteps(folded) }, 'pf') : null,
              streaming && !body
                ? _jsx('div', {
                    style: { ...BODY_TEXT, color: C.muted, animation: 'td-pulse 1.4s ease-in-out infinite' },
                    children: say('writing'),
                  }, 'w')
                : src.fold
                  ? _jsx(FoldedBody, { text: body, ...FOLD_WORD[src.fold] }, 'b')
                  : _jsx(MdBody, { text: body, onOpenSession }, 'b'),
              threads.length
                ? _jsx('div', {
                    style: BAR_STACK,
                    children: threads.map((th) =>
                      _jsx(ThreadMarker, {
                        thread: th,
                        members,
                        active: th.id === openThreadId,
                        onOpen: onOpenThread,
                      }, th.id),
                    ),
                  }, 'th')
                : null,
            ],
          }),
        },
        key,
      ),
    )
  }

  items.forEach((it) => {
    const key = `${it.kind}${it.at}`
    if (it.kind === 'day') {
      rows.push(_jsx(DayDivider, { label: it.label }, key))
      return
    }
    if (it.kind === 'turn' || it.kind === 'msg') {
      if (it.kind === 'turn' && !it.tail) return
      pushConvo(it)
      return
    }
    if (it.kind === 'process') {
      rows.push(_jsx('div', { style: GUTTER_STYLE, children: _jsx(WalkFold, { steps: walkSteps([it]) }) }, key))
      return
    }
    if (it.kind === 'error') {
      rows.push(
        _jsx('div', { style: GUTTER_STYLE, children: _jsx(QuietLine, { text: quietText(it.msg), tone: 'danger' }) }, key),
      )
      return
    }
    if (it.kind === 'permission') {
      // v1 has no approval buttons (§9.1). Saying where the gate can be answered
      // is the honest degradation; a button that cannot decide would be worse.
      rows.push(
        _jsx('div', {
          style: GUTTER_STYLE,
          children: _jsx(QuietLine, {
            text: say('perm_await', { msg: quietText(it.msg) }),
            tone: 'warn',
          }),
        }, key),
      )
      return
    }
    if (it.kind === 'queued') {
      rows.push(
        _jsx('div', { style: GUTTER_STYLE, children: _jsx(QuietLine, { text: say('queued_line', { msg: quietText(it.msg) }) }) }, key),
      )
      return
    }
    rows.push(_jsx('div', { style: GUTTER_STYLE, children: _jsx(QuietLine, { text: it.text }) }, key))
  })

  waiting.forEach((p) => {
    rows.push(
      _jsx(
        SlackRow,
        {
          member,
          agent,
          isUser: true,
          timestamp: '',
          timestampTitle: '',
          cont: false,
          children: _jsxs('div', {
            style: { opacity: 0.6 },
            children: [
              _jsx(MdBody, { text: p.text }, 'b'),
              _jsx('div', { style: { fontSize: QUIET_PX, color: C.muted }, children: say('sending') }, 's'),
            ],
          }),
        },
        p.id,
      ),
    )
  })

  if (!rows.length) {
    rows.push(
      _jsx('div', {
        style: { color: C.muted, fontSize: QUIET_PX, padding: sp(S.x2, ROW_PAD + ROW_GUTTER) },
        children: t.loaded ? say('transcript_empty') : say('reading_session'),
      }, 'empty'),
    )
  }

  return _jsx(ChatBoundary, {
    slotKey,
    children: _jsxs('div', {
      className: 'td-chat',
      style: box,
      children: [
        _jsxs('div', {
          ref: scroller,
          // Named so the divider's drag can pin it without a ref crossing components.
          className: 'td-scroll',
          onScroll,
          onMouseUp: quote.onMouseUp,
          style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: sp('0', '0', S.x2), position: 'relative' },
          children: [
            _jsx('div', { style: { minWidth: 0 }, children: rows }, 'rows'),
            quote.sel
              ? _jsx('button', {
                  onClick: () => {
                    setDraft((d) => asQuote(quote.sel.text) + d)
                    quote.clear()
                  },
                  style: {
                    position: 'absolute',
                    top: `${quote.sel.top}px`,
                    left: `${quote.sel.left}px`,
                    background: C.card,
                    color: C.text,
                    border: hair(C.borderStrong),
                    borderRadius: R.md,
                    padding: sp(S.x1, S.x2),
                    fontSize: F.quiet,
                    fontFamily: 'inherit',
                    cursor: 'pointer',
                    zIndex: 3,
                  },
                  children: say('act_quote'),
                }, 'quote')
              : null,
          ],
        }),
        _jsx(FollowUps, { options: follow, onPick: send }, 'follow'),
        _jsx(Composer, { draft, setDraft, running: t.running, onSend: send, sendError: sendError || threadError }, 'composer'),
      ],
    }),
  })
}

/**
 * Which session this member's chat is bound to.
 *
 * `/org` is authoritative — the backend persists a reset into `data/config.json`
 * and reports it back. Two cases still need the locally remembered key: the poll
 * that is still in flight right after a reset (its payload predates the reset, so
 * it would answer with the key we just replaced), and a stale payload the page is
 * still showing because a later read failed. Comparing the payload's read time
 * against the reset's means the local value is preferred only while it is
 * genuinely newer, and stops mattering as soon as the two agree.
 */

// ─── The left rail: Slack's DM list ──────────────────────────────────────────
//
// Slack picks a conversation from a rail, not from a separate page, so this is
// where a member is chosen now (ARCHITECTURE.md §10.1). The Desk page keeps its own
// tree — it answers a different question (who reports to whom) — but it is no
// longer the only way to switch.

const RAIL_W = L.rail
const THREAD_W = L.panel

/**
 * The two Slack sidebar sections: the standing chain, then the pods.
 *
 * An IC is deliberately NOT here. This rail is the DM list — who you open a
 * conversation with — and the reader is the CEO, who briefs the fund manager;
 * a pod's sentiment analyst is not someone they message. Ninety rows nobody
 * clicks is what pushed the fifteen that ARE clicked off the screen. The ICs
 * live on the Desk page, which answers a different question: what the org looks
 * like and who is working right now.
 *
 * The labels come from `say()`. They were hardcoded Chinese, which is why the
 * language switch left this rail behind while the rest of the page turned.
 */
function railGroups(members) {
  const list = Array.isArray(members) ? members : []
  const roster = list.filter((m) => !String(m.id).startsWith('ic-'))
  const isLm = (m) => String(m.id).startsWith('lm-')
  const pods = roster.filter(isLm)
  return [
    { key: 'chain', label: say('rail_chain'), rows: roster.filter((m) => !isLm(m)) },
    { key: 'pods', label: say('rail_pods', { n: pods.length }), rows: pods },
  ].filter((g) => g.rows.length)
}

function RailRow({ member, selected, onSelect }) {
  return _jsxs('button', {
    className: 'td-rail-row',
    onClick: () => onSelect(member.id),
    title: phrase(member.state_msg) || member.title || member.name,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: S.x2,
      width: '100%',
      padding: sp(S.x1, S.x2, S.x1, S.x2),
      border: 'none',
      borderRadius: R.md,
      background: selected ? C.accentSubtle : 'transparent',
      cursor: 'pointer',
      fontFamily: 'inherit',
      textAlign: 'left',
    },
    children: [
      _jsx(Avatar, { letter: memberLetter(member), kind: memberKind(member), size: L.avatarSm, radius: R.sm }),
      _jsx('span', {
        style: {
          flex: 1,
          minWidth: 0,
          fontSize: F.quiet,
          // Slack bolds a conversation with something unread. There is no unread
          // signal in `/org`, so weight is spent on the SELECTED row instead of
          // faking one.
          fontWeight: selected ? 700 : 400,
          color: selected ? C.text : C.muted,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        },
        children: member.name,
      }),
      _jsx(Dot, { state: member.state }),
    ],
  })
}

/**
 * A Slack sidebar section header: a small label that folds its group.
 *
 * The caret leads the label and the whole header is the hit target, which is how
 * Slack's own section headers behave. `count` shows only while folded — an open
 * section is already counting itself on screen.
 */
function RailSection({ label, count, folded, onToggle }) {
  return _jsxs('button', {
    onClick: onToggle,
    'aria-expanded': !folded,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: S.x1,
      width: '100%',
      background: 'none',
      border: 'none',
      font: 'inherit',
      textAlign: 'left',
      cursor: 'pointer',
      borderRadius: R.sm,
      fontSize: F.micro,
      fontWeight: 700,
      letterSpacing: '0.06em',
      color: C.muted,
      padding: sp(S.x1, S.x2),
    },
    children: [
      _jsx('span', {
        style: { width: `${S.x3}px`, flexShrink: 0, lineHeight: 1 },
        children: folded ? '▸' : '▾',
      }),
      _jsx('span', { style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }, children: label }),
      folded && count
        ? _jsx('span', {
            style: {
              marginLeft: 'auto',
              fontWeight: 400,
              letterSpacing: 0,
              fontVariantNumeric: 'tabular-nums',
              flexShrink: 0,
            },
            children: String(count),
          })
        : null,
    ],
  })
}

function MemberRail({ members, selectedId, onSelect }) {
  const groups = railGroups(members)
  // The pods start folded and the standing chain does not: the reader is the CEO,
  // who briefs the standing roles daily and reaches for a line-manager only
  // sometimes. Keyed by section so a pod list opened once stays open.
  const [folded, setFolded] = useState(() => new Set(['pods']))
  const toggle = (key) =>
    setFolded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  return _jsx('div', {
    className: 'td-rail',
    style: {
      width: `${RAIL_W}px`,
      flexShrink: 0,
      minHeight: 0,
      borderRight: hair(C.line2),
      overflowY: 'auto',
      background: C.bg,
      padding: S.x2,
      display: 'flex',
      flexDirection: 'column',
      gap: S.half,
    },
    children: groups.map((g) => {
      // A folded section still shows the row you are looking at, so selecting a
      // line-manager and folding the pods does not hide the conversation open in
      // the middle column.
      const isFolded = folded.has(g.key) && !g.rows.some((m) => m.id === selectedId)
      return _jsxs('div', {
        style: { marginBottom: S.x2 },
        children: [
          _jsx(RailSection, {
            label: g.label,
            count: g.rows.length,
            folded: isFolded,
            onToggle: () => toggle(g.key),
          }),
          isFolded
            ? null
            : _jsx('div', {
                style: { display: 'flex', flexDirection: 'column', gap: S.hair },
                children: g.rows.map((m) =>
                  _jsx(RailRow, { member: m, selected: m.id === selectedId, onSelect }, m.id),
                ),
              }),
        ],
      }, g.key)
    }),
  })
}

export function ChatPage({ org, orgAt, selectedId, onProfile, onOpenMember, onSelectMember, onOpenFile, rememberedSlots, onReset }) {
  // §rev9.1 addendum: the shell's shape belongs to the reader. Restored from this
  // browser's own storage and re-clamped against THIS viewport, so a width chosen
  // on a 3440px monitor does not swallow a 1280px laptop.
  const shellRef = useRef(null)
  // The panel's budget is the SHELL's width, not the window's. The app is embedded in
  // the dashboard's own pane, which at a 1440px window is 1204px: measuring the
  // window made "45% max" resolve to 54% of the space actually available and squeezed
  // the conversation to 296px. Falls back to the window only for the first render,
  // before there is a node to measure -- the mount effect re-clamps immediately after.
  const budget = () => {
    const el = shellRef.current
    const w = el && typeof el.getBoundingClientRect === 'function' ? Math.round(el.getBoundingClientRect().width) : 0
    if (w > 0) return w
    return typeof window === 'undefined' ? 0 : window.innerWidth
  }
  const [shell, setShell] = useState(() => readShell(typeof window === 'undefined' ? 0 : window.innerWidth))
  useEffect(() => {
    // Feature-checked rather than assumed: the test renderer has a `window` with no
    // event target on it, and a shell that throws on mount takes the page with it.
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return undefined
    const onResize = () => setShell((cur) => {
      const fit = clampPanel(cur.panel, budget())
      return fit === cur.panel ? cur : { ...cur, panel: fit }
    })
    // Watching the SHELL, not just the window: the pane can change width without the
    // window doing anything (the dashboard's own sidebar opening, a zoom change), and
    // on the very first paint the shell has not been laid out yet -- which is how a
    // remembered 560 survived a ceiling of 542 until the next window resize.
    onResize()
    window.addEventListener('resize', onResize)
    let ro = null
    if (typeof ResizeObserver === 'function' && shellRef.current) {
      ro = new ResizeObserver(onResize)
      ro.observe(shellRef.current)
    }
    return () => {
      window.removeEventListener('resize', onResize)
      if (ro) ro.disconnect()
    }
  }, [])

  const members = (org && org.members) || []
  const base = findMember(members, selectedId) || members[0]
  const [openThread, setOpenThread] = useState({ member: '', id: '' })
  const [followUp, setFollowUp] = useState('')
  // Which thread SESSIONS the transcript actually drew a reply bar for. Reported back
  // by TdChat because it is the only place that knows: the header entry has to offer
  // everything the conversation did NOT place, not everything with a null anchor.
  const [placed, setPlaced] = useState([])
  // The receipts the conversation folded away (§15.2), keyed by thread, so the panel
  // can show what the manager said when it opened this one.
  const [notes, setNotes] = useState({})

  const threadsLoader = useCallback(
    (signal) => load(`/threads?member=${encodeURIComponent(selectedId || '')}`, SHAPE.threads, signal),
    [selectedId],
  )
  const threads = useLoader(threadsLoader, [selectedId], 20000)

  if (!base) return _jsx(Notice, { tone: 'info', children: say('no_members') })

  const slotKey = resolveSlotKey(base, rememberedSlots, orgAt)
  const member = slotKey === base.slot_key ? base : { ...base, slot_key: slotKey }
  const agent = agentFor(org, base.id)
  const openId = openThread.member === base.id ? openThread.id : ''
  const list = (threads.data && threads.data.threads) || []
  const openFor = (id) => setOpenThread({ member: base.id, id: id === openId ? '' : id })

  // Slack's shape: the marker lives under the message that started the work, so
  // the conversation itself tells you a thread is there. TdChat draws it inside
  // the message's own text column, which is why this hands back the thread rather
  // than a rendered node.
  const threadFor = (msg) => threadsForMessage(list, msg)

  /**
   * Ask the backend to open a thread on a message that has none (§rev7 B), then
   * show it. The list is re-read rather than patched locally: `/threads` is the
   * authority on a thread's id, anchor and kind, and a locally minted row would
   * disagree with it the moment the next poll landed.
   */
  const startThread = async (anchor, text) => {
    const res = await createThread(base.id, anchor, text)
    if (res.missing) {
      markThreadRouteMissing()
      return res
    }
    if (res.error) return res
    threads.reload()
    setOpenThread({ member: base.id, id: res.id })
    return res
  }

  // The three columns of design/mockups/option-a.html, which is this page's pixel
  // baseline: 260 rail / the conversation / 380 thread panel, filling the page and
  // divided by hairlines. rev8 drew them inside a rounded card on a dark surface;
  // a card inside a page that is already white is a border for its own sake, and
  // the card's `calc(100vh - chrome)` height fought the shell's own flexbox --
  // which is how the conversation column ended up 912px wide in a 3204px pane.
  const stream = _jsxs('div', {
    style: { minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: C.bg },
    children: [
      _jsx(ChatHead, {
        member,
        agent,
        onProfile,
        onReset,
        extra: _jsx(UnanchoredThreads, { threads: unplacedThreads(list, placed), openId, onOpen: openFor }),
      }),
      followUp
        ? _jsx(FollowUpHint, { text: followUp, onDismiss: () => setFollowUp('') })
        : null,
      _jsx(TdChat, {
        member,
        agent,
        members,
        threads: list,
        threadFor,
        openThreadId: openId,
        onOpenThread: openFor,
        onStartThread: startThread,
        onThreadsPlaced: setPlaced,
        onReceipts: setNotes,
        // A session key written into a receipt becomes a door: clicking it opens
        // that thread's panel. A key naming a session this member does not own
        // resolves to nothing and the chip stays inert rather than lying.
        onOpenSession: (key) => {
          const hit = list.find((th) => th.slot_key === key)
          if (hit) openFor(hit.id)
        },
      }),
    ],
  })

  return _jsxs('div', {
    className: 'td-shell',
    ref: shellRef,
    style: {
      // Both variable columns are custom properties so the drag and the rail toggle
      // can move them on the node without re-rendering the conversation.
      '--td-panel': `${shell.panel}px`,
      '--td-rail': shell.rail === 'off' ? '0px' : `${RAIL_W}px`,
      display: 'grid',
      position: 'relative',
      gridTemplateColumns: openId
        ? 'var(--td-rail) minmax(0, 1fr) var(--td-panel)'
        : 'var(--td-rail) minmax(0, 1fr)',
      // ONE row, bounded by the shell. Without this the row is auto-sized: it takes
      // the tallest column's CONTENT height -- 1,331px in a 900px viewport once the
      // transcript is long -- so the columns' own scrollers never engage, the white
      // surface stops where the root ends, and everything below it is the
      // dashboard's dark page showing through. The panel's lower half goes off
      // screen the same way. Both defects trace to this one line.
      gridTemplateRows: 'minmax(0, 1fr)',
      flex: 1,
      minWidth: 0,
      minHeight: 0,
      height: '100%',
      overflow: 'hidden',
      background: C.bg,
    },
    children: _jsxs(_Fragment, {
      children: [
        shell.rail === 'off'
          ? null
          : _jsx(MemberRail, { members, selectedId: base.id, onSelect: onSelectMember || (() => {}) }),
        // An optional extra: with the member list away the conversation gets those
        // 260px back. Positioned on the shell rather than in the rail, because a
        // 0px-wide rail cannot hold the control that reopens it.
        _jsx('button', {
          type: 'button',
          className: 'td-quiet-btn td-rail-toggle',
          title: shell.rail === 'off' ? say('rail_show') : say('rail_hide'),
          'aria-expanded': shell.rail !== 'off',
          onClick: () => {
            const next = { ...shell, rail: shell.rail === 'off' ? 'on' : 'off' }
            setShell(next)
            writeShell(next)
          },
          style: {
            position: 'absolute',
            top: S.x2,
            left: shell.rail === 'off' ? S.x2 : RAIL_W - 26,
            zIndex: 4,
            width: 22,
            height: 22,
            display: 'grid',
            placeItems: 'center',
            border: hair(C.border),
            borderRadius: R.sm,
            background: C.card,
            color: C.muted,
            cursor: 'pointer',
            fontSize: F.micro,
            lineHeight: 1,
          },
          children: shell.rail === 'off' ? '›' : '‹',
        }),
        stream,
        openId
          ? _jsxs('div', {
              // The grid item, so the column's height and clipping stay exactly as
              // §5d878f6 left them; `relative` is what the grip anchors to.
              style: { position: 'relative', minWidth: 0, minHeight: 0, height: '100%', overflow: 'hidden' },
              children: [
                _jsx(PanelGrip, {
                  shellRef,
                  width: shell.panel,
                  onCommit: (px) => {
                    const next = { ...shell, panel: px }
                    setShell(next)
                    writeShell(next)
                  },
                }),
                _jsx(ThreadDrawer, {
              threadId: openId,
              thread: findThread(list, openId),
              // What the conversation folded away when this thread was opened
              // (§15.2) -- shown here so nothing is lost by hiding the receipt.
              note: notes[openId] || notes[threadKey(findThread(list, openId) || {})] || '',
              member,
              agent,
              members,
              onClose: () => setOpenThread({ member: '', id: '' }),
              onProfile: onOpenMember,
              onOpenFile,
                  onFollowUp: (t) => {
                    setFollowUp(say('followup_prefix', { title: t.title }))
                    setOpenThread({ member: '', id: '' })
                  },
                }, openId),
              ],
            })
          : null,
      ],
    }),
  })
}

/**
 * The follow-up placeholder's landing spot. An app cannot write into the embed's
 * composer, so the line is handed over here to copy into the main conversation.
 */
function FollowUpHint({ text, onDismiss }) {
  return _jsxs('div', {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: S.x2,
      padding: sp(S.x2, S.x4),
      borderBottom: hair(C.border),
      background: C.accentSubtle,
    },
    children: [
      _jsx('span', { style: { fontSize: F.meta, color: C.muted, flexShrink: 0 }, children: say('followup_label') }),
      _jsx('input', {
        readOnly: true,
        value: text,
        onFocus: (e) => e.target.select(),
        style: {
          flex: 1,
          minWidth: 0,
          background: C.bg,
          color: C.text,
          border: hair(C.border),
          borderRadius: R.md,
          padding: sp(S.x1, S.x2),
          fontSize: F.meta,
          fontFamily: 'inherit',
        },
      }),
      _jsx(Ghost, { onClick: onDismiss, children: say('dismiss') }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 8b. Threads (M2)
//
// The main conversation stays the user's conversation with one crew member; the
// work happens in threads. This layer is the ONLY process view: nothing here is
// copied into the main transcript, and a thread's own entries are reached by
// opening it, never by restating them.
// ─────────────────────────────────────────────────────────────────────────────

const THREAD_STATE_TONE = { running: 'accent', done: 'ok', failed: 'danger' }
const THREAD_STATE_KEY = { running: 'state_work', done: 'state_done', failed: 'state_fail' }

/** A thread's state in a word the reader uses. Falls back to whatever the backend
 *  said rather than showing a blank, but never shows a key. */
function threadStateWord(state) {
  const key = THREAD_STATE_KEY[state]
  return key ? say(key) : String(state || '')
}

const ENTRY_KIND = {
  dispatch: { label: () => say('entry_dispatch'), tone: 'accent' },
  report: { label: () => say('entry_report'), tone: 'ok' },
  steer: { label: () => say('entry_steer'), tone: 'warn' },
  close: { label: () => say('entry_done'), tone: 'ok' },
}

function memberName(members, id) {
  const m = findMember(members, id)
  return (m && m.name) || id || ''
}

/** `POST /thread/{id}/say` — a line typed in a thread goes straight into the
 *  session doing the work. No separate steer button, by design. */
async function sayInThread(id, text) {
  try {
    const { ok, status, data } = await postJson(`/thread/${encodeURIComponent(id)}/say`, { text })
    if (!ok) return { error: (data && data.error) || say('send_failed_http', { status }) }
    return { deliveredTo: (data && data.delivered_to) || '' }
  } catch (err) {
    return { error: String((err && err.message) || err) }
  }
}

/**
 * The user takes part in threads too — their steer is an entry — but the CEO is not
 * a member: CONTRACT §2 keeps them out of the roster, so there is no name to look
 * up and no profile to open.
 */
const CEO_ACTOR = 'ceo'

/**
 * A crew name that opens that crew's profile, the same move as the Desk page.
 * Anyone not in the roster stays plain text: a link that silently lands on some
 * other crew's profile is worse than no link.
 */
function ActorName({ id, members, onProfile }) {
  if (id === CEO_ACTOR) {
    return _jsx('span', { style: { color: C.text, fontSize: F.meta }, children: say('you') })
  }
  if (!findMember(members, id)) {
    return _jsx('span', { style: { color: C.muted, fontSize: F.meta }, children: String(id || '') })
  }
  return _jsx('button', {
    onClick: () => onProfile(id),
    title: say('profile_tooltip', { who: memberName(members, id) }),
    style: {
      background: 'none',
      border: 'none',
      padding: 0,
      color: C.accent,
      fontSize: F.meta,
      fontFamily: 'inherit',
      cursor: 'pointer',
      whiteSpace: 'nowrap',
    },
    children: memberName(members, id),
  })
}

/**
 * The thread anchored to a given transcript row.
 *
 * Rows are matched on `ts`, which is the identity ChatMessageList itself uses for
 * a single row (`hiddenRow`). `anchor.main_msg` is the ledger's own id and is
 * deliberately not used here yet (ruling 2026-09-14).
 */
/**
 * The thread that hangs under this message, matched on BOTH of the anchor's keys.
 *
 * `main_msg` is the row's `meta.mid` — the identity the gateway mints, and the
 * only one that cannot drift. `ts` is the fallback, and it is an exact string
 * compare against a timestamp the backend copies verbatim out of the transcript
 * (backend/threads.py `_anchor`): any reformatting on either side and it stops
 * matching, which is precisely why the mid is tried first.
 */
function threadsForMessage(threads, msg) {
  if (!msg) return []
  const list = threads || []
  const mid = msg.meta && msg.meta.mid
  const ts = msg.ts
  // Both keys, and the union of them: two topics raised in one sentence are two
  // threads and earn a bar each (§13.2). Same thread matched by both keys is still
  // one bar, which is what the identity check here is for.
  const out = []
  list.forEach((t) => {
    const a = t && t.anchor
    if (!a) return
    if ((mid && a.main_msg === mid) || (ts && a.ts === ts)) {
      if (!out.includes(t)) out.push(t)
    }
  })
  return out
}

/**
 * Threads the conversation shows no bar for, which is what the header entry is
 * for.
 *
 * Not "threads with no anchor": an anchor whose row is outside the loaded window,
 * whose `ts` no longer matches, or whose paragraph folded into the steps fold (§13.1), leaves a
 * thread that is anchored on paper and unreachable on screen. So the set is computed
 * from what actually got a bar — `shownKeys` comes back from the transcript, which is
 * the only place that knows — and it is keyed on the SESSION, or a thread deduped out
 * of the conversation would reappear here as a second copy of itself.
 *
 * Worth knowing while reading this: on the live desk today NOTHING is anchored.
 * `_anchor` needs a `DISPATCHED ->` line in the member's own reply to find the
 * instruction a dispatch hangs under, and no session on disk carries one, so the
 * backend returns `anchor: null` for every thread and this entry is the only way
 * in. It is not a fallback in practice; it is the path.
 */
function unplacedThreads(threads, shownKeys) {
  const shown = shownKeys instanceof Set ? shownKeys : new Set(shownKeys || [])
  return (threads || []).filter((t) => !shown.has(threadKey(t)))
}

/**
 * What makes two thread records the same thread: the session they talk to (§13.2).
 *
 * Keyed on the session and not on the record id, because a backend that anchors one
 * thread twice hands back two records with two ids and one slot_key — and drawing
 * that as two threads is the bug. The id is the fallback for a record with no
 * session yet, where it is the only identity there is.
 */
function threadKey(t) {
  return (t && (t.slot_key || t.id)) || ''
}

/** Threads with no message to hang under. They reach the user through the
 *  header's own entry instead of a row footer. */
function markerTime(thread) {
  const raw = thread.last_ts || thread.opened_at || ''
  const m = String(raw).match(/(\d{2}:\d{2})/)
  return m ? m[1] : ''
}

/** A thread's reply count from whichever field the payload carries it in. */
function entryCount(data) {
  const n = data && (typeof data.entry_count === 'number' ? data.entry_count
    : Array.isArray(data.entries) ? data.entries.length
    : Array.isArray(data.messages) ? data.messages.length : null)
  return typeof n === 'number' && n >= 0 ? n : 0
}

function markerCount(thread) {
  const n = thread.entry_count
  return typeof n === 'number' && n >= 0 ? n : null
}

/**
 * The Slack-shaped line under the message that started the work. Reading it is
 * how you learn a thread exists; the thread's content stays inside the thread.
 */
/**
 * Slack's reply bar: who is in the thread, how many replies, when the last one
 * landed — and on hover it turns into the invitation to open it.
 *
 * An actor who is not on the roster (the reader themselves) still gets a face:
 * `findMember` misses, so the CEO letter stands in rather than a '?'.
 */
function replyFace(members, id) {
  const m = findMember(members || [], id)
  return m
    ? { letter: memberLetter(m), kind: memberKind(m) }
    : { letter: 'R', kind: 'ceo' }
}

function ThreadMarker({ thread, members, active, onOpen }) {
  const n = markerCount(thread)
  const at = markerTime(thread)
  const people = (thread.participants || []).slice(0, 3)
  return _jsxs('button', {
    className: 'td-reply',
    onClick: () => onOpen(thread.id),
    title: stripEnvelope(thread.last_msg || thread.title).text,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: S.x2,
      margin: sp(S.x1, '0', S.x1),
      padding: sp(S.x1, S.x2, S.x1, S.x1),
      background: active ? C.accentSubtle : 'transparent',
      border: hair(active ? C.accent : 'transparent'),
      borderRadius: R.lg,
      cursor: 'pointer',
      fontFamily: 'inherit',
      maxWidth: '100%',
    },
    children: [
      people.length
        ? _jsx('span', {
            style: { display: 'inline-flex', gap: S.half },
            children: people.map((id, i) => {
              const f = replyFace(members, id)
              return _jsx(Avatar, { letter: f.letter, kind: f.kind, size: L.avatarSm, radius: R.sm }, `${id}${i}`)
            }),
          })
        : null,
      _jsxs('span', {
        className: 'td-reply-main',
        // `display` is deliberately NOT inline here: the hover rule that swaps
        // this for the invitation is a stylesheet rule, and an inline display
        // beats it. Set in injectKeyframes with the swap it belongs to.
        style: { alignItems: 'baseline', gap: S.x2, minWidth: 0 },
        children: [
          _jsx('span', {
            style: { fontSize: F.quiet, color: C.accent, fontWeight: 700, whiteSpace: 'nowrap' },
            children: n === null ? say('reply_view') : say('reply_n', { n }),
          }),
          at
            ? _jsx('span', { style: { fontSize: STAMP_PX, color: C.muted, whiteSpace: 'nowrap' }, children: say('reply_latest', { time: at }) })
            : null,
          // Which kind of thread this is (§11.1): the conductor's own clone, or a
          // session it opened for someone else. Absent from an older payload, in
          // which case nothing is claimed.
          threadKindWord(thread)
            ? _jsx(Pill, { tone: 'quiet', children: threadKindWord(thread) })
            : null,
          thread.state !== 'running'
            ? _jsx(Pill, { tone: THREAD_STATE_TONE[thread.state] || 'quiet', children: threadStateWord(thread.state) })
            : null,
        ],
      }),
      _jsx('span', {
        className: 'td-reply-hint',
        style: { fontSize: F.quiet, color: C.muted, whiteSpace: 'nowrap' },
        // Not the "View thread" wording: that is what the bar says when the payload carries no
        // count, and two different states must not read identically.
        children: say('reply_open'),
      }),
    ],
  })
}

/**
 * Threads that could not be anchored to a message. Not a chips bar: one quiet
 * header entry that opens a list, so an un-anchored thread is still reachable
 * without putting a rail of them above the conversation.
 */
function UnanchoredThreads({ threads, openId, onOpen }) {
  const [open, setOpen] = useState(false)
  const list = threads || []
  if (!list.length) return null

  return _jsxs('div', {
    style: { position: 'relative' },
    children: [
      _jsx(Ghost, {
        onClick: () => setOpen(!open),
        active: open,
        title: say('unanchored_title'),
        children: say('work_in_progress', { n: list.length }),
      }),
      open
        ? _jsx('div', {
            style: {
              position: 'absolute',
              top: '100%',
              right: 0,
              marginTop: S.x1,
              zIndex: 5,
              minWidth: L.menuMin,
              maxWidth: L.menu,
              background: C.card,
              border: hair(C.border),
              borderRadius: R.lg,
              padding: S.x1,
              display: 'flex',
              flexDirection: 'column',
              gap: S.half,
              boxShadow: SHADOW.menu,
            },
            children: list.map((t) =>
              _jsxs('button', {
                onClick: () => {
                  setOpen(false)
                  onOpen(t.id)
                },
                title: stripEnvelope(t.last_msg || t.title).text,
                style: {
                  display: 'flex',
                  alignItems: 'center',
                  gap: S.x2,
                  textAlign: 'left',
                  background: t.id === openId ? C.accentSubtle : 'transparent',
                  border: 'none',
                  borderRadius: R.md,
                  padding: sp(S.x1, S.x2),
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                },
                children: [
                  _jsx(Dot, { state: t.state === 'running' ? 'work' : t.state === 'failed' ? 'fail' : 'done' }),
                  _jsx('span', {
                    style: { fontSize: F.meta, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
                    children: t.title,
                  }),
                  _jsxs('span', {
                    style: { marginLeft: 'auto', flexShrink: 0, display: 'flex', gap: S.x1 },
                    children: [
                      threadKindWord(t) ? _jsx(Pill, { tone: 'quiet', children: threadKindWord(t) }) : null,
                      _jsx(Pill, { tone: THREAD_STATE_TONE[t.state] || 'quiet', children: threadStateWord(t.state) }),
                    ],
                  }),
                ],
              }, t.id),
            ),
          })
        : null,
    ],
  })
}

/**
 * A readable, DISTINGUISHABLE label for an artifact path. Every team's daily file
 * is named by date, so the file name alone renders two different reports in one
 * thread as the same "2026-09-09.md"; the last few segments say whose it is.
 */
function refLabel(path) {
  const parts = String(path).split('/').filter(Boolean)
  return parts.slice(-3).join('/')
}

function EntryRow({ entry, members, onProfile, onOpenFile }) {
  const kind = ENTRY_KIND[entry.kind] || { label: () => entry.kind, tone: 'quiet' }
  return _jsxs('div', {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: S.x1,
      padding: sp(S.x2, '0'),
      borderBottom: hair(C.border),
    },
    children: [
      _jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: S.x2, flexWrap: 'wrap' },
        children: [
          _jsx('span', { style: { color: C.muted, fontSize: F.micro, fontFamily: MONO }, children: entry.ts }),
          _jsx(ActorName, { id: entry.actor, members, onProfile }),
          _jsx(Pill, { tone: kind.tone, children: kind.label() }),
        ],
      }),
      _jsx('div', {
        style: { color: C.text, fontSize: F.quiet, lineHeight: 1.6, whiteSpace: 'pre-wrap' },
        children: stripEnvelope(entry.text).text,
      }),
      entry.ref
        ? _jsx('button', {
            onClick: () => onOpenFile(entry.ref),
            title: entry.ref,
            style: {
              alignSelf: 'flex-start',
              background: 'none',
              border: 'none',
              padding: 0,
              color: C.accent,
              fontSize: F.meta,
              fontFamily: 'inherit',
              cursor: 'pointer',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: '100%',
              whiteSpace: 'nowrap',
            },
            children: `📄 ${refLabel(entry.ref)}`,
          })
        : null,
    ],
  })
}

/** A line typed here IS the steer — there is deliberately no separate button. */
function ThreadSay({ threadId, members, onSaid }) {
  const [ui, setUi] = useState({ text: '', busy: false, error: '', note: '' })

  async function send() {
    const text = ui.text.trim()
    if (!text || ui.busy) return
    setUi({ text, busy: true, error: '', note: '' })
    const res = await sayInThread(threadId, text)
    if (res.error) {
      setUi({ text, busy: false, error: res.error, note: '' })
      return
    }
    const who = res.deliveredTo ? memberName(members, res.deliveredTo) : ''
    setUi({ text: '', busy: false, error: '', note: who ? say('sent_to', { who }) : say('sent') })
    onSaid()
  }

  return _jsxs('div', {
    style: { borderTop: hair(C.border), padding: sp(S.x2, '0', '0'), display: 'flex', flexDirection: 'column', gap: S.x1 },
    children: [
      ui.error ? _jsx('span', { style: { fontSize: F.micro, color: C.danger }, children: ui.error }) : null,
      ui.note ? _jsx('span', { style: { fontSize: F.micro, color: C.muted }, children: ui.note }) : null,
      _jsxs('div', {
        className: 'td-box',
        style: { display: 'flex', gap: S.x2, alignItems: 'flex-end', borderRadius: R.xl, padding: S.x2 },
        children: [
          _jsx('textarea', {
            value: ui.text,
            rows: 2,
            placeholder: say('reply_here'),
            onChange: (e) => setUi({ ...ui, text: e.target.value }),
            onKeyDown: (e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            },
            style: {
              flex: 1,
              minWidth: 0,
              resize: 'vertical',
              background: C.bg,
              color: C.text,
              border: hair(C.border),
              borderRadius: R.lg,
              padding: S.x2,
              fontSize: F.quiet,
              fontFamily: 'inherit',
              lineHeight: 1.5,
            },
          }),
          _jsx(Ghost, { onClick: send, disabled: ui.busy || !ui.text.trim(), children: ui.busy ? say('sending') : say('send') }),
        ],
      }),
    ],
  })
}

/**
 * A finished thread takes no more steering. The follow-up entry is a PLACEHOLDER:
 * it hands the line back for the main conversation, because an app cannot put text
 * into the embed's composer — ChatEmbed exposes no draft prop and
 * `useComposerDraft` persists nothing an app could write.
 */
function ThreadDone({ thread, onFollowUp }) {
  return _jsxs('div', {
    style: { borderTop: hair(C.border), padding: sp(S.x2, '0', '0'), display: 'flex', flexDirection: 'column', gap: S.x2 },
    children: [
      _jsx('span', { style: { fontSize: F.meta, color: C.muted }, children: say('thread_finished') }),
      _jsx('div', {
        children: _jsx(Ghost, { onClick: () => onFollowUp(thread), children: say('add_followup') }),
      }),
    ],
  })
}

/**
 * Which fields of a thread rev6 reads, and what each is for.
 *
 * `slot_key` is the clone session behind the thread — with it the panel IS that
 * conversation (§11.2). Without it there is nothing to read, and the panel falls
 * back to M2's boundary timeline rather than showing an empty box: backend is
 * still moving the anchor source to key-mention, and a thread built the old way
 * still has to open.
 *
 * `kind` labels it a clone or a dispatch; `member` and `agent` say whose voice the
 * rows are in, which for a clone is the conductor's own (§11.1 — same agent) and for
 * a dispatch is the subordinate's. All four are optional and each degrades to
 * something true rather than to a guess.
 *
 * The spellings are the BACKEND's, read off its own emitter rather than chosen
 * here: `kind` is `thread` for the conductor's own clone (not `clone`), and the
 * member a session belongs to is `member` (not `owner`). `clone` and `owner` are
 * accepted too — a one-line map costs nothing and this app's fixtures were written
 * before that emitter landed — but the backend's name is the authoritative one.
 */
const THREAD_KIND_WORD = {
  thread: () => say('thread_kind_clone'),
  clone: () => say('thread_kind_clone'),
  dispatch: () => say('thread_kind_dispatch'),
}

function threadKindWord(thread) {
  const fn = thread && THREAD_KIND_WORD[thread.kind]
  return fn ? fn() : ''
}

function threadFace(thread, members, member) {
  const id = thread && (thread.member || thread.owner)
  return (id && findMember(members || [], id)) || member
}

/**
 * The divider between the conversation and the thread panel.
 *
 * The drag deliberately does NOT go through React. On every pointermove it writes
 * one custom property onto the shell node; the conversation column is not
 * re-rendered, so its 31 rows of markdown are not rebuilt 60 times a second, and
 * because the measure stays capped at `L.measure` and centred, the text does not
 * re-wrap at any panel width -- only the whitespace either side of it moves. React
 * learns the final number once, on release, which is also when it is persisted.
 *
 * `setPointerCapture` is what makes the drag survive the pointer leaving the 6px
 * strip: without it, moving faster than the layout can follow drops the drag.
 */
function PanelGrip({ shellRef, width, onCommit }) {
  const onDown = (e) => {
    const shell = shellRef.current
    const grip = e.currentTarget
    if (!shell) return
    e.preventDefault()
    const startX = e.clientX
    const startW = width
    let next = width
    // A wider panel means a narrower conversation, and at 1440 the conversation is
    // already under the 820 measure -- so the text genuinely re-wraps, exactly as it
    // does in Slack. What must NOT happen is the rows the reader is looking at
    // jumping: re-wrapping earlier messages changes the height above them. The
    // conversation is bottom-anchored, so the scroller is pinned as the width moves,
    // which keeps the newest rows still and lets the re-wrap happen above the fold.
    const scroller = shell.querySelector('.td-scroll')
    const pinned = scroller ? scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80 : false
    const move = (ev) => {
      // The panel is on the right, so dragging LEFT makes it wider.
      next = clampPanel(startW + (startX - ev.clientX), Math.round(shell.getBoundingClientRect().width))
      shell.style.setProperty('--td-panel', `${next}px`)
      if (pinned && scroller) scroller.scrollTop = scroller.scrollHeight
    }
    const end = () => {
      grip.removeEventListener('pointermove', move)
      grip.removeEventListener('pointerup', end)
      grip.removeEventListener('pointercancel', end)
      delete grip.dataset.drag
      onCommit(next)
    }
    try {
      grip.setPointerCapture(e.pointerId)
    } catch (err) {
      /* a browser without capture still works, it just loses a fast drag */
    }
    grip.dataset.drag = '1'
    grip.addEventListener('pointermove', move)
    grip.addEventListener('pointerup', end)
    grip.addEventListener('pointercancel', end)
  }

  // Keyboard is not decoration here: a pointer drag is the one interaction a
  // keyboard user cannot perform at all, so the same edge takes arrow keys.
  const onKey = (e) => {
    const step = e.shiftKey ? 64 : 16
    const el = shellRef.current
    const span = el && typeof el.getBoundingClientRect === 'function'
      ? Math.round(el.getBoundingClientRect().width)
      : (typeof window === 'undefined' ? 0 : window.innerWidth)
    if (e.key === 'ArrowLeft') onCommit(clampPanel(width + step, span))
    else if (e.key === 'ArrowRight') onCommit(clampPanel(width - step, span))
    else return
    e.preventDefault()
  }

  return _jsx('div', {
    className: 'td-grip',
    role: 'separator',
    'aria-orientation': 'vertical',
    'aria-label': say('panel_resize'),
    tabIndex: 0,
    onPointerDown: onDown,
    onKeyDown: onKey,
    style: {
      position: 'absolute',
      top: 0,
      bottom: 0,
      left: -3,
      width: 6,
      zIndex: 3,
    },
  })
}

function ThreadDrawer({ threadId, thread, note, member, agent, members, onClose, onProfile, onOpenFile, onFollowUp }) {
  const loader = useCallback(
    // rev6 §11.2 detail shape: metadata + slot_key, NO entries (the panel renders
    // the clone session's live transcript itself). entries stays accepted for the
    // dispatch-thread fallback timeline. Requiring entries alone is what rejected
    // every §11.2 response as "the response shape is wrong".
    (signal) => load(`/thread/${encodeURIComponent(threadId)}`, SHAPE.thread, signal),
    [threadId],
  )
  const { data, error, reload, detail } = useLoader(loader, [threadId], 15000)

  // The receipt starts folded: it is the manager's account of what it dispatched,
  // which is process rather than the subject of the thread. Reset per thread so
  // opening a second one does not inherit the first one's disclosure.
  const [noteOpen, setNoteOpen] = useState(false)
  useEffect(() => { setNoteOpen(false) }, [threadId])

  const kind = threadKindWord(thread) || threadKindWord(data)
  const head = _jsxs('div', {
    style: { display: 'flex', alignItems: 'flex-start', gap: S.x2, paddingBottom: S.x2, borderBottom: hair(C.line2) },
    children: [
      _jsx('span', {
        className: 'td-clamp2',
        style: { fontSize: F.title, fontWeight: W.bold, color: C.text, minWidth: 0, lineHeight: 1.35 },
        title: (data && data.title) || '',
        children: (data && data.title) || say('what_thread'),
      }),
      kind ? _jsx(Pill, { tone: 'quiet', children: kind }) : null,
      data ? _jsx(Pill, { tone: THREAD_STATE_TONE[data.state] || 'quiet', children: threadStateWord(data.state) }) : null,
      _jsx('span', { style: { marginLeft: 'auto' }, children: _jsx(Ghost, { onClick: onClose, children: say('thread_close') }) }),
    ],
  })

  const cloneKey = (thread && thread.slot_key) || (data && data.slot_key) || ''

  let body
  if (error && !data) body = _jsx(LoadError, { message: error, detail, what: say('what_thread'), onRetry: reload })
  else if (!data) body = _jsx(Loading, { what: say('what_thread') })
  else {
    // Slack's thread panel opens with the message the thread hangs off, then the
    // replies, then the box. The anchor's own preview is that message; a thread
    // the backend could not anchor falls back to its title, which is the only
    // other thing that says what this thread is about.
    const opener = stripEnvelope((data.anchor && data.anchor.preview) || data.title || '').text
    body = _jsxs(_Fragment, {
      children: [
        _jsx(StaleBar, { message: error, detail, onRetry: reload }),
        opener
          ? _jsxs('div', {
              style: { padding: sp(S.x3, '0'), borderBottom: hair(C.border), minWidth: 0 },
              children: [
                // Slack quotes the message a thread hangs off rather than labelling
                // it. The label used to say "the thread opened from this message" above the text, which
                // spent a line restating what the quote's own shape says — and it
                // was hardcoded Chinese, so an English reader got it in Chinese
                // directly above an English one from `receipt_note`.
                //
                // The anchor is by definition the user message the manager
                // dispatched from (§8.1), so the attribution is the reader.
                _jsxs('div', {
                  style: {
                    fontSize: F.micro,
                    color: C.muted,
                    marginBottom: '2px',
                    display: 'flex',
                    gap: S.x2,
                  },
                  children: [
                    _jsx('span', { children: data.anchor && data.anchor.preview ? say('ceo_you') : say('what_thread') }),
                    data.anchor && data.anchor.ts
                      ? _jsx('span', { title: rowTimeTitle(data.anchor.ts), children: rowTime(data.anchor.ts) })
                      : null,
                  ],
                }),
                _jsx('div', {
                  style: {
                    borderLeft: `2px solid ${C.border}`,
                    paddingLeft: S.x3,
                    fontSize: F.quiet,
                    lineHeight: 1.5,
                    color: C.mutedStrong,
                    wordBreak: 'break-word',
                  },
                  children: opener,
                }),
                // The receipt the main conversation folded away (§15.2). It is the
                // manager's own account of what it dispatched — process, not the
                // subject — so it collapses to one line. Kept whole behind it, and
                // rendered the same way it was rendered there, so hiding the row in
                // the main conversation still costs the reader nothing.
                note
                  ? _jsxs('div', {
                      style: { marginTop: S.x2, minWidth: 0 },
                      children: [
                        _jsxs('button', {
                          onClick: () => setNoteOpen((v) => !v),
                          'aria-expanded': noteOpen,
                          style: {
                            display: 'flex',
                            alignItems: 'center',
                            gap: S.x1,
                            background: 'none',
                            border: 'none',
                            padding: 0,
                            font: 'inherit',
                            fontSize: F.micro,
                            color: C.muted,
                            cursor: 'pointer',
                          },
                          children: [
                            _jsx('span', { style: { lineHeight: 1 }, children: noteOpen ? '▾' : '▸' }),
                            _jsx('span', { children: say('receipt_note') }),
                          ],
                        }),
                        noteOpen
                          ? _jsx('div', {
                              style: { marginTop: S.x1, paddingLeft: S.x3, borderLeft: `2px solid ${C.line2}` },
                              children: _jsx(MdBody, { text: note }),
                            })
                          : null,
                      ],
                    })
                  : null,
              ],
            })
          : null,
        // The rule between the message a thread came from and the thread itself
        // (§15.1, second reference frame). It states the count, which is the one fact
        // the reader wants before they start scrolling.
        _jsxs('div', {
          className: 'td-replies-rule',
          style: {
            display: 'flex', alignItems: 'center', gap: S.x2,
            padding: sp(S.x2, '0', S.x1), fontSize: F.meta, color: C.muted,
          },
          children: [
            _jsx('span', { style: { flexShrink: 0 }, children: say('reply_n', { n: entryCount(data) }) }),
            _jsx('span', { style: { flex: 1, height: 1, background: C.border } }),
          ],
        }),
        // §11.2: the panel IS the clone's conversation. Talking here talks to the
        // clone — which is why the composer comes from the same stack as the main
        // chat's rather than from ThreadSay's one-line steer.
        cloneKey
          ? _jsx(ChatStream, {
              slotKey: cloneKey,
              member: threadFace(thread || data, members, member),
              agent: (thread && thread.agent) || data.agent || agent,
              members,
              // The receipt above the replies already carries what the brief says,
              // so the folded brief row would be the same account a second time.
              hideSeed: !!note,
            }, cloneKey)
          : _jsxs(_Fragment, {
              children: [
                _jsx('div', {
                  style: { flex: 1, minHeight: 0, overflowY: 'auto' },
                  children: (data.entries || []).length
                    ? (data.entries || []).map((e, i) =>
                        _jsx(EntryRow, { entry: e, members, onProfile, onOpenFile }, `${e.ts}-${i}`))
                    : _jsx('div', { style: { color: C.muted, fontSize: F.meta, padding: sp(S.x3, '0') }, children: say('thread_empty') }),
                }),
                data.state === 'running'
                  ? _jsx(ThreadSay, { threadId, members, onSaid: reload })
                  : _jsx(ThreadDone, { thread: data, onFollowUp }),
              ],
            }),
      ],
    })
  }

  return _jsx(Card, {
    className: 'td-panel',
    // The panel is the shell's third grid column, so it takes the column's height.
    // It used to size itself with `calc(100vh - chrome)`, which is a guess about
    // the page's furniture -- and the guess plus the grid's unbounded row is how
    // the panel ended up taller than the viewport with its bottom half off screen.
    style: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: 0,
      overflow: 'hidden',
      border: 'none',
      borderLeft: hair(C.line2),
      borderRadius: 0,
      background: C.bg,
    },
    children: _jsxs(_Fragment, { children: [head, body] }),
  })
}

/** The thread a list item id names. */
function findThread(threads, id) {
  return (threads || []).find((t) => t.id === id) || null
}

// ─────────────────────────────────────────────────────────────────────────────
// 9. Desk page
// ─────────────────────────────────────────────────────────────────────────────
