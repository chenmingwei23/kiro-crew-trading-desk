/** The Run page — today's chain of work. */

import { useCallback, useEffect, useState } from 'react'
import { t } from './i18n.mjs'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { DELIVERY_WORD, load, useLoader, SHAPE } from './data.mjs'
import { ROW_GUTTER } from './parts.mjs'
import { C, Card, Dot, F, Ghost, L, LoadError, Loading, MONO, Notice, Pill, R, S, STATE_COLOR, Sect, StaleBar, hair, sp } from './theme.mjs'

function stageState(stage, podState) {
  const total = Number(stage.total) || 0
  const done = Number(stage.done) || 0
  if (total > 0 && done >= total) return 'done'
  if (podState === 'fail' && done < total) return 'fail'
  if (done > 0) return 'work'
  return 'todo'
}

const MARK = { done: '✓', fail: '✕' }

function PBar({ done, total }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  return _jsx('span', {
    style: {
      display: 'inline-block',
      width: S.x12,
      height: S.x1,
      borderRadius: R.pill,
      background: C.border,
      overflow: 'hidden',
      flexShrink: 0,
    },
    children: _jsx('span', {
      style: { display: 'block', height: '100%', width: `${pct}%`, background: C.accent },
    }),
  })
}

function Step({ state, label, done, total }) {
  const color = state === 'todo' ? C.muted : state === 'work' ? C.accent : C.text
  return _jsxs('span', {
    className: 'td-mono',
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: S.x1,
      whiteSpace: 'nowrap',
      fontSize: F.meta,
      opacity: state === 'todo' ? 0.45 : 1,
      color,
      // declared machine label (a date, a run id) -- not prose
      fontFamily: MONO,
    },
    children: [
      MARK[state]
        ? _jsx('span', { style: { color: STATE_COLOR[state], fontSize: F.meta }, children: MARK[state] })
        : state === 'work'
          ? total
            ? _jsx(PBar, { done, total })
            : _jsx(Dot, { state: 'work' })
          : null,
      _jsx('span', { children: label }),
    ],
  })
}

function Arrow() {
  return _jsx('span', {
    className: 'td-mono',
    style: { color: C.border, margin: sp('0', S.x2), flexShrink: 0, fontFamily: MONO },
    children: '─▶',
  })
}

function DeliveryPill({ state, at }) {
  const tone = state === 'done' ? 'ok' : state === 'fail' ? 'danger' : 'quiet'
  const word = DELIVERY_WORD[state] || DELIVERY_WORD.work
  return _jsx(Pill, { tone, children: at ? `${word} · ${at}` : word })
}

function Lane({ head, headTone, children }) {
  return _jsxs('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: `minmax(0, ${L.keyCol}px) minmax(0, 1fr)`,
      borderBottom: hair(C.border),
      alignItems: 'center',
    },
    children: [
      _jsx('div', {
        className: 'td-mono',
        style: {
          padding: sp(S.x2, S.x3),
          borderRight: hair(C.border),
          fontSize: F.meta,
          alignSelf: 'stretch',
          display: 'flex',
          alignItems: 'center',
          // declared machine label (a date, a run id) -- not prose
          fontFamily: MONO,
          color: headTone || C.text,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        },
        children: head,
      }),
      _jsx('div', {
        style: { display: 'flex', alignItems: 'center', padding: sp(S.x2, S.x3), overflowX: 'auto' },
        children,
      }),
    ],
  })
}

/** Interleave steps with arrows without nesting the whole lane in one expression. */
function withArrows(nodes) {
  const out = []
  nodes.forEach((n, i) => {
    if (i > 0) out.push(_jsx(Arrow, {}, `a${i}`))
    out.push(n)
  })
  return out
}

function ChainLane({ lane }) {
  const steps = (lane.steps || []).map((s, i) =>
    _jsx(Step, { state: s.state, label: s.at ? `${s.label} ${s.at}` : s.label }, `s${i}`),
  )
  return _jsx(Lane, { head: lane.member, headTone: C.accent, children: withArrows(steps) })
}

function PodLane({ pod }) {
  const nodes = (pod.stages || []).map((st, i) => {
    const state = stageState(st, pod.state)
    return _jsx(
      Step,
      { state, label: `${st.name} ${st.done}/${st.total}`, done: st.done, total: st.total },
      `st${i}`,
    )
  })
  nodes.push(_jsx(DeliveryPill, { state: pod.state, at: pod.delivered_at }, 'pill'))
  const failNote = pod.fail_reason
    ? _jsx('span', {
        className: 'td-mono',
        style: { color: C.danger, fontSize: F.micro, marginLeft: S.x3, fontFamily: MONO },
        children: pod.fail_reason,
      }, 'fail')
    : null
  const children = withArrows(nodes)
  if (failNote) children.push(failNote)
  return _jsx(Lane, { head: pod.pod, headTone: pod.state === 'fail' ? C.danger : C.text, children })
}

function countPods(pods) {
  const c = { done: 0, work: 0, fail: 0 }
  for (const p of pods || []) c[p.state] = (c[p.state] || 0) + 1
  return c
}

function RunHead({ run, date, onDate, onToday, loading }) {
  const c = countPods(run && run.pods)
  return _jsxs(Card, {
    pad: sp(S.x2, S.x3),
    // Monospace belongs on the run's identifier, not on the whole header: 回放,
    // 已交 and 进行中 are prose, and prose in a machine typeface is what the app-ui
    // standard rules out. The date and id below carry it themselves.
    style: { display: 'flex', alignItems: 'center', gap: S.x3, flexWrap: 'wrap', fontSize: F.meta },
    children: [
      run && run.live
        ? _jsx(Pill, { tone: 'ok', children: '● LIVE' })
        : _jsx(Pill, { tone: 'quiet', children: '回放' }),
      _jsxs('span', {
        className: 'td-mono',
        style: { color: C.text, fontFamily: MONO },
        children: [_jsx('span', { style: { color: C.muted }, children: 'run ' }), (run && run.date) || date],
      }),
      _jsxs('span', {
        style: { display: 'flex', gap: S.x2 },
        children: [
          _jsx('span', { style: { color: C.ok }, children: `${c.done} ${t('state_done')}` }),
          _jsx('span', { style: { color: C.accent }, children: `${c.work} 进行中` }),
          _jsx('span', { style: { color: c.fail ? C.danger : C.muted }, children: `${c.fail} ${t('state_fail')}` }),
        ],
      }),
      loading ? _jsx('span', { style: { color: C.muted }, children: '刷新中…' }) : null,
      _jsxs('span', {
        style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: S.x2 },
        children: [
          _jsx('input', {
            type: 'date',
            value: date,
            onChange: (e) => onDate(e.target.value),
            style: {
              background: C.bg,
              color: C.text,
              border: hair(C.border),
              borderRadius: R.md,
              padding: sp(S.x1, S.x2),
              fontSize: F.micro,
              fontFamily: 'inherit',
            },
          }),
          _jsx(Ghost, { onClick: onToday, children: '今天' }),
        ],
      }),
    ],
  })
}

function Ticker({ events }) {
  const rows = events || []
  if (!rows.length) return _jsx(Notice, { tone: 'info', children: '今天还没有事件。' })
  return _jsx(Card, {
    pad: sp(S.x1, 0),
    style: { maxHeight: L.scrollCap, overflowY: 'auto' },
    children: rows.map((e, i) =>
      _jsxs('div', {
        style: {
          display: 'grid',
          gridTemplateColumns: `${ROW_GUTTER}px minmax(0, ${L.stat}px) minmax(0, 1fr)`,
          gap: S.x2,
          padding: sp(S.x1, S.x4),
          fontSize: F.meta,
          // declared machine label (a date, a run id) -- not prose
          // The event's clock carries the monospace; the message beside it is prose.
          borderBottom: i === rows.length - 1 ? 'none' : hair(C.border),
        },
        children: [
          _jsx('span', { className: 'td-mono', style: { color: C.muted, fontFamily: MONO }, children: e.at }),
          _jsx('span', {
            style: { color: C.accent, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
            children: e.who,
          }),
          _jsx('span', { style: { color: e.hot ? C.text : C.muted }, children: e.msg }),
        ],
      }, `${e.at}-${i}`),
    ),
  })
}

function LaneGroup({ children }) {
  return _jsx('div', {
    style: { background: C.card, border: hair(C.border), borderRadius: R.lg, overflow: 'hidden' },
    children,
  })
}

export function todayStr() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function RunPage({ date, onDate }) {
  const [live, setLive] = useState(true)
  const loader = useCallback(
    (signal) => load(`/run?date=${encodeURIComponent(date)}`, SHAPE.run, signal),
    [date],
  )
  const { data, error, loading, source, reload, detail } = useLoader(loader, [date], live ? 10000 : 30000)

  useEffect(() => {
    if (data) setLive(!!data.live)
  }, [data])

  if (error && !data) return _jsx(LoadError, { message: error, detail, what: t('what_run'), onRetry: reload })
  if (!data) return _jsx(Loading, { what: t('what_run') })

  // (§rev9.1 finding 9) A day nothing has started on used to be a page of empty
  // rails, which reads as broken rather than as "not yet". It says what to do.
  const idle = !(data.chain || []).length && !(data.pods || []).length
  if (idle) {
    return _jsxs('div', {
      style: { display: 'flex', flexDirection: 'column', gap: S.x3, alignItems: 'flex-start', padding: sp(S.x6, 0) },
      children: [
        _jsx(StaleBar, { message: error, detail, onRetry: reload }),
        _jsx('div', { style: { fontSize: F.h2, fontWeight: 700, letterSpacing: '-0.01em' }, children: t('empty_run_title') }),
        _jsx('div', { style: { color: C.muted, fontSize: F.body, lineHeight: 1.6, maxWidth: 520 }, children: t('empty_run') }),
      ],
    })
  }

  return _jsxs(_Fragment, {
    children: [
      _jsx(StaleBar, { message: error, detail, onRetry: reload }),
      _jsx(RunHead, { run: data, date, onDate, onToday: () => onDate(todayStr()), loading }),
      _jsx(Sect, { label: '指挥链' }),
      _jsx(LaneGroup, {
        children: (data.chain || []).map((lane) => _jsx(ChainLane, { lane }, lane.member)),
      }),
      _jsx(Sect, { label: 'Pods', hint: '分析 → 多空辩论 → 提案 → 风险评审 → 组报告' }),
      _jsx(LaneGroup, { children: (data.pods || []).map((pod) => _jsx(PodLane, { pod }, pod.pod)) }),
      _jsx(Sect, { label: '事件流（最近）' }),
      _jsx(Ticker, { events: data.events }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 11. Config page (M0: read-only)
// ─────────────────────────────────────────────────────────────────────────────
