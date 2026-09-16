/** The Config page — the desk's own settings, read from the backend. */

import { useCallback } from 'react'
import { t } from './i18n.mjs'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { load, useLoader, SHAPE } from './data.mjs'
import { C, Card, F, Ghost, L, LoadError, Loading, MONO, Notice, Pill, R, S, Sect, StaleBar, hair, sp } from './theme.mjs'

function isScalar(v) {
  return v === null || ['string', 'number', 'boolean'].indexOf(typeof v) >= 0
}

function scalarText(v) {
  if (v === null || v === undefined) return '—'
  return String(v)
}

function ScalarField({ label, value }) {
  return _jsxs('label', {
    style: { display: 'flex', alignItems: 'center', gap: S.x2, fontSize: F.meta, minWidth: 0 },
    children: [
      _jsx('span', { style: { color: C.muted, minWidth: L.stat, flexShrink: 0 }, children: label }),
      _jsx('input', {
        readOnly: true,
        // A config value is the desk's own vocabulary -- a limit, a ticker, a book
        // name -- so monospace is correct here and declared as such (§rev9 probe).
        className: 'td-mono',
        value: scalarText(value),
        style: {
          flex: 1,
          minWidth: 0,
          maxWidth: L.field,
          background: C.bg,
          color: C.text,
          border: hair(C.border),
          borderRadius: R.md,
          padding: sp(S.x1, S.x2),
          fontSize: F.meta,
          fontFamily: MONO,
        },
      }),
    ],
  })
}

function ScalarList({ label, values }) {
  if (!values.length) return _jsx(ScalarField, { label, value: null })
  return _jsx(ScalarField, { label, value: values.map(scalarText).join('  ') })
}

/** Renders an arbitrary parsed-YAML value as a read-only form. Recursion is one
 *  level per call so no single expression nests deeply. */
function DataNode({ label, value, depth }) {
  if (isScalar(value) || value === undefined) return _jsx(ScalarField, { label, value })

  if (Array.isArray(value)) {
    if (value.every(isScalar)) return _jsx(ScalarList, { label, values: value })
    return _jsx(Group, {
      label: `${label} (${value.length})`,
      depth,
      children: value.map((v, i) => _jsx(DataNode, { label: `#${i + 1}`, value: v, depth: depth + 1 }, `i${i}`)),
    })
  }

  const keys = Object.keys(value)
  return _jsx(Group, {
    label,
    depth,
    children: keys.length
      ? keys.map((k) => _jsx(DataNode, { label: k, value: value[k], depth: depth + 1 }, k))
      : [_jsx('span', { style: { color: C.muted, fontSize: F.meta }, children: '（空）' }, 'empty')],
  })
}

function Group({ label, depth, children }) {
  return _jsxs('div', {
    style: {
      borderLeft: hair(C.border),
      paddingLeft: S.x3,
      marginLeft: depth > 0 ? S.x1 : 0,
      display: 'flex',
      flexDirection: 'column',
      gap: S.x1,
    },
    children: [
      _jsx('div', {
        // A config group's name is the key from the file (`account_constraints`), not
        // a phrase we chose -- monospace says exactly that, and declaring it keeps the
        // probe honest about the ones that ARE prose.
        className: 'td-mono',
        style: { color: C.accent, fontSize: F.meta, fontWeight: 600, fontFamily: MONO },
        children: label,
      }),
      _jsx('div', { style: { display: 'flex', flexDirection: 'column', gap: S.x1 }, children }),
    ],
  })
}

/** The section header already names the block, so a plain object is rendered as
 *  its own keys rather than nested under a group repeating that name. */
function sectionBody(title, value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return _jsx(DataNode, { label: title, value, depth: 0 })
  }
  const keys = Object.keys(value)
  if (!keys.length) return _jsx('span', { style: { color: C.muted, fontSize: F.meta }, children: '（空）' })
  return _jsx('div', {
    style: { display: 'flex', flexDirection: 'column', gap: S.x1 },
    children: keys.map((k) => _jsx(DataNode, { label: k, value: value[k], depth: 0 }, k)),
  })
}

function ConfigSection({ title, hint, value }) {
  return _jsxs('div', {
    style: { marginBottom: S.x3 },
    children: [
      _jsx(Sect, { label: title }),
      _jsxs(Card, {
        children: [
          hint ? _jsx('div', { style: { color: C.muted, fontSize: F.meta, marginBottom: S.x2 }, children: hint }) : null,
          sectionBody(title, value),
        ],
      }),
    ],
  })
}

export function ConfigPage() {
  const loader = useCallback(
    (signal) => load('/deskconfig', SHAPE.deskconfig, signal),
    [],
  )
  const { data, error, loading, reload, detail } = useLoader(loader, [], 30000)

  if (loading && !data) return _jsx(Loading, { what: t('what_config') })
  if (error && !data) return _jsx(LoadError, { message: error, detail, what: t('what_config'), onRetry: reload })
  if (!data) return _jsx(Notice, { tone: 'info', children: '没有配置数据。' })

  return _jsxs(_Fragment, {
    children: [
      _jsx(StaleBar, { message: error, detail }),
      _jsxs(Card, {
        style: { display: 'flex', alignItems: 'center', gap: S.x3, flexWrap: 'wrap', marginBottom: S.x1 },
        children: [
          _jsx('span', { style: { fontSize: F.meta, color: C.text }, children: '账户与行业组配置' }),
          _jsx(Pill, { tone: 'warn', children: '只读' }),
          _jsx('span', {
            style: { fontSize: F.meta, color: C.muted },
            children: '本期只做展示，改配置仍走 books.yaml / sectors.yaml。',
          }),
          _jsx('span', {
            style: { marginLeft: 'auto' },
            children: _jsx(Ghost, { disabled: true, title: '本期不开放保存', children: '保存（未开放）' }),
          }),
        ],
      }),
      _jsx(ConfigSection, { title: 'books', hint: '账户与可用额度', value: data.books }),
      _jsx(ConfigSection, { title: 'sectors', hint: '行业组与覆盖标的', value: data.sectors }),
      _jsx(ConfigSection, { title: 'constraints', hint: '账户约束', value: data.constraints }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 12. Logs page
// ─────────────────────────────────────────────────────────────────────────────
