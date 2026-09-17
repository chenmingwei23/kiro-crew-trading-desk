/** The Logs page — what the desk wrote to disk. */

import { useCallback, useEffect, useState } from 'react'
import { phrase, t } from './i18n.mjs'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { HostBoundary, load, readDeskFile, uiKit, useLoader, SHAPE } from './data.mjs'
import { C, Card, F, Ghost, L, LoadError, Loading, MONO, Notice, R, S, StaleBar, labelStyle, sp } from './theme.mjs'

function DateChips({ dates, value, onChange }) {
  return _jsx('div', {
    style: { display: 'flex', gap: S.x1, flexWrap: 'wrap', marginBottom: S.x2 },
    children: (dates || []).map((d) =>
      _jsx(Ghost, { active: d === value, onClick: () => onChange(d), children: d }, d),
    ),
  })
}

function FileTree({ tree, activePath, onPick }) {
  const groups = tree || []
  if (!groups.length) return _jsx(Notice, { tone: 'info', children: t('logs_no_artifacts') })
  return _jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: S.x3 },
    children: groups.map((g) =>
      _jsxs('div', {
        children: [
          _jsx('div', {
            style: { ...labelStyle(g.group), marginBottom: S.x1 },
            children: phrase(g.group),
          }),
          _jsx('div', {
            style: { display: 'flex', flexDirection: 'column', gap: S.half },
            children: (g.files || []).map((f) =>
              _jsx('button', {
                onClick: () => onPick(f.path),
                title: f.path,
                style: {
                  textAlign: 'left',
                  background: f.path === activePath ? C.accentSubtle : 'transparent',
                  color: f.path === activePath ? C.text : C.accent,
                  border: 'none',
                  borderRadius: R.sm,
                  padding: sp(S.x1, S.x2),
                  fontSize: F.meta,
                  fontFamily: 'inherit',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                },
                children: `📄 ${f.label}`,
              }, f.path),
            ),
          }),
        ],
      }, g.group),
    ),
  })
}

function FileBody({ text }) {
  const kit = uiKit()
  const own = _jsx('pre', {
    style: {
      margin: 0,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      fontFamily: MONO,
      fontSize: F.meta,
      lineHeight: 1.65,
      color: C.text,
    },
    children: text,
  })
  if (!kit || !kit.MarkdownRenderer) return own
  // The host's renderer is attempted, but a throw inside it must cost this one
  // file's formatting rather than the page -- see HostBoundary.
  return _jsx(HostBoundary, {
    resetKey: text,
    fallback: own,
    children: _jsx(kit.MarkdownRenderer, { content: text }),
  })
}

function FileView({ path }) {
  const [text, setText] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    setText(null)
    setFailed(false)
    if (!path) return undefined
    readDeskFile(path).then((t) => {
      if (!alive) return
      if (t === null) setFailed(true)
      else setText(t)
    })
    return () => {
      alive = false
    }
  }, [path])

  if (!path) return _jsx(Notice, { tone: 'info', children: t('pick_output') })
  if (failed) return _jsx(Notice, { tone: 'error', children: t('read_failed', { what: t('what_file') }) })
  if (text === null) return _jsx(Loading, { what: t('what_file') })

  return _jsxs(Card, {
    style: { maxHeight: `min(66vh, ${L.modal}px)`, overflowY: 'auto' },
    children: [
      // The path is the tooltip, not the headline (§rev9.1 finding 11): a reader
      // came for what the desk wrote, and `teams/macro/reports/2026-09-15.md` is
      // our filing system, not their information. The left column already names it.
      _jsx('div', {
        style: { color: C.muted, fontSize: F.quiet, marginBottom: S.x2 },
        title: path,
        children: readableTitle(path),
      }),
      _jsx(FileBody, { text }),
    ],
  })
}

/** A path as a person would say it: the day, and what the thing is. */
function readableTitle(path) {
  const parts = String(path || '').split('/').filter(Boolean)
  const file = parts[parts.length - 1] || ''
  const day = (file.match(/(\d{4}-\d{2}-\d{2})/) || [])[1] || ''
  const group = parts.length >= 2 ? parts[parts.length - 3] || parts[0] : ''
  return [day, group].filter(Boolean).join(' · ') || file
}

export function LogsPage({ date, onDate, openPath, onOpenPath }) {
  const loader = useCallback(
    (signal) => load(`/artifacts?date=${encodeURIComponent(date)}`, SHAPE.artifacts, signal),
    [date],
  )
  const { data, error, reload, detail } = useLoader(loader, [date], 30000)

  if (error && !data) return _jsx(LoadError, { message: error, detail, what: t('what_output'), onRetry: reload })
  if (!data) return _jsx(Loading, { what: t('what_output') })
  // (§rev9.1 finding 9) A day with nothing on it said nothing at all. It says what
  // to do instead, and (finding 12) the page opens on the most recent day that
  // actually HAS output rather than on today, which is usually empty before the
  // desk has run.
  const empty = !Array.isArray(data.tree) || data.tree.length === 0
  const latest = Array.isArray(data.dates) ? data.dates.find((d) => d && d !== date) : ''

  return _jsxs(_Fragment, {
    children: [
      _jsx(StaleBar, { message: error, detail }),
      _jsx('div', {
        style: { display: 'grid', gridTemplateColumns: `minmax(0, ${L.sidePane}px) minmax(0, 1fr)`, gap: S.x4, alignItems: 'start' },
        children: _jsxs(_Fragment, {
          children: [
            _jsxs('div', {
              children: [
                _jsx(DateChips, { dates: data.dates, value: date, onChange: onDate }),
                empty
                  ? _jsxs(Card, {
                      style: { display: 'flex', flexDirection: 'column', gap: S.x3, alignItems: 'flex-start' },
                      children: [
                        _jsx('div', { style: { color: C.muted, fontSize: F.quiet, lineHeight: 1.6 }, children: t('empty_output') }),
                        latest
                          ? _jsx(Ghost, { onClick: () => onDate(latest), children: t('jump_to', { day: latest }) })
                          : null,
                      ],
                    })
                  : _jsx(Card, { children: _jsx(FileTree, { tree: data.tree, activePath: openPath, onPick: onOpenPath }) }),
              ],
            }),
            _jsx(FileView, { path: openPath }),
          ],
        }),
      }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 13. Shell
// ─────────────────────────────────────────────────────────────────────────────
