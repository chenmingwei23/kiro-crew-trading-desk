/** The Desk page — the member directory (§14.1: this mode does not change). */

import { useMemo, useState } from 'react'
import { memberTitle, phrase, t } from './i18n.mjs'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { Avatar, C, Card, Dot, F, Ghost, L, Notice, R, S, Sect, findMember, hair, labelStyle, memberKind, memberLetter, orgRows, rule, sp } from './theme.mjs'

function KvRow({ k, v }) {
  return _jsxs(_Fragment, {
    children: [
      _jsx('span', { style: { color: C.muted }, children: k }),
      _jsx('span', { style: { color: C.text }, children: v }),
    ],
  })
}

function HeroSide({ outputs, onOpen }) {
  const items = outputs || []
  return _jsxs('div', {
    style: { borderLeft: hair(C.border), paddingLeft: S.x4, fontSize: F.meta },
    children: [
      _jsx('div', {
        style: { ...labelStyle(t('recent_output')), marginBottom: S.x1 },
        children: t('recent_output'),
      }),
      items.length
        ? _jsx('div', {
            style: { display: 'flex', flexDirection: 'column', gap: S.x1 },
            children: items.map((o, i) =>
              _jsx('button', {
                onClick: () => onOpen && onOpen(o.path),
                title: o.path,
                style: {
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  textAlign: 'left',
                  color: C.accent,
                  fontSize: F.meta,
                  fontFamily: 'inherit',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                },
                children: `📄 ${phrase(o.label)}`,
              }, `${o.path}-${i}`),
            ),
          })
        : _jsx('span', { style: { color: C.muted }, children: '—' }),
    ],
  })
}

function HeroMain({ member, reportCount, reportsTo, onChat }) {
  return _jsxs('div', {
    style: { minWidth: 0 },
    children: [
      _jsx('div', { style: { fontSize: F.head, letterSpacing: '0.02em', color: C.text }, children: member.name }),
      _jsx('div', { style: { color: C.accent, marginTop: S.half, fontSize: F.quiet }, children: member.title || '' }),
      _jsx('div', {
        style: { color: C.muted, fontSize: F.meta, marginTop: S.half },
        children: member.group || reportsTo || 'Trading Desk',
      }),
      _jsxs('div', {
        style: {
          display: 'grid',
          gridTemplateColumns: `${L.label}px 1fr`,
          gap: sp(S.x1, S.x3),
          marginTop: S.x3,
          fontSize: F.meta,
        },
        children: [
          _jsx('span', { style: { color: C.muted }, children: t('status_label') }),
          _jsxs('span', {
            style: { display: 'flex', alignItems: 'center', gap: S.x1, color: C.text },
            children: [_jsx(Dot, { state: member.state }), _jsx('span', { children: phrase(member.state_msg) || '—' })],
          }),
          _jsx(KvRow, { k: t('direct_reports'), v: reportCount ? String(reportCount) : '—' }),
          member.tickers && member.tickers.length
            ? _jsx(KvRow, { k: '覆盖标的', v: member.tickers.join(' ') })
            : null,
        ],
      }),
      _jsx('div', {
        style: {
          marginTop: S.x3,
          color: C.muted,
          fontSize: F.quiet,
          lineHeight: 1.6,
          borderLeft: rule(C.border),
          paddingLeft: S.x3,
          maxWidth: L.quote,
        },
        children: member.duty || '',
      }),
      _jsx('div', {
        style: { marginTop: S.x4 },
        children: _jsx(Ghost, { onClick: onChat, active: true, children: t('chat_direct') }),
      }),
    ],
  })
}

function Hero({ member, reportCount, reportsTo, onChat, onOpenFile }) {
  const kind = memberKind(member)
  return _jsx(Card, {
    pad: S.x5,
    style: {
      display: 'grid',
      gridTemplateColumns: `minmax(0, ${L.avatarLg + S.x1}px) minmax(0, 1fr) minmax(0, ${L.chrome}px)`,
      gap: S.x5,
      alignItems: 'start',
    },
    children: _jsxs(_Fragment, {
      children: [
        _jsx('div', {
          style: { display: 'flex', justifyContent: 'center' },
          children: _jsx(Avatar, { letter: memberLetter(member), kind, size: L.avatarLg, radius: R.xl, soft: true }),
        }),
        _jsx(HeroMain, { member, reportCount, reportsTo, onChat }),
        _jsx(HeroSide, { outputs: member.recent_outputs, onOpen: onOpenFile }),
      ],
    }),
  })
}

function Twisty({ hasChildren, collapsed, count, onToggle }) {
  // The column is reserved even on a childless row, so every avatar in the rail
  // stays on one vertical line instead of shifting by a pod's presence.
  if (!hasChildren) {
    return _jsx('div', { style: { width: `${S.x4}px`, flexShrink: 0 } })
  }
  return _jsx('button', {
    onClick: (e) => {
      e.stopPropagation()
      onToggle()
    },
    'aria-expanded': !collapsed,
    title: collapsed ? t('fold_open', { n: count }) : t('fold_close'),
    style: {
      width: `${S.x4}px`,
      flexShrink: 0,
      background: 'transparent',
      border: 'none',
      padding: 0,
      color: C.muted,
      fontSize: F.micro,
      cursor: 'pointer',
      fontFamily: 'inherit',
      lineHeight: 1,
    },
    children: collapsed ? '▸' : '▾',
  })
}

function OrgRow({ member, depth, hasChildren, collapsed, childCount, selected, onSelect, onChat, onToggle }) {
  const kind = memberKind(member)
  // An IC row is COMPACT: ten of them sit under one line-manager, and the two
  // things a two-line row would show are both already on screen. Its `group`
  // repeats the parent row's verbatim, and its `name` repeats the pod
  // ("technicals · example-megacap"), so the row carries the role title alone and
  // puts its progress on the SAME line. That halves the height of an unfolded
  // pod, which is what makes unfolding one usable.
  const isIc = kind === 'ic'
  // `memberTitle`, not `member.title`: the roster stores English and the Chinese
  // reading is mapped in i18n, so a raw read here prints English rows to a
  // Chinese reader and ignores the language switch.
  const lead = isIc ? memberTitle(member) || member.name : member.name
  // The roster's group label carries no language-specific word -- the suffix is
  // appended here from the language map, so an English reader never gets a
  // Chinese noun glued to a Latin pod name. The strip handles a roster written
  // before that rule, which ended the label with the word itself.
  const sub = isIc
    ? ''
    : member.group
      ? `${String(member.group).replace(/\s*(组|pod)$/i, '')} ${t('pod_suffix')}`
      : member.title || ''
  // Just the count. `state_msg` is the backend's one-line Chinese, and ten
  // identical copies of it down one pod said less than the digits do.
  const progress = isIc ? (String(member.state_msg || '').match(/\d+\s*\/\s*\d+/) || [''])[0] : ''
  return _jsxs('div', {
    onClick: () => onSelect(member.id),
    role: 'button',
    tabIndex: 0,
    onKeyDown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onSelect(member.id)
      }
    },
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: S.x3,
      padding: isIc ? sp(S.x1, S.x4) : sp(S.x2, S.x4),
      paddingLeft: `${16 + (depth - 1) * 26}px`,
      cursor: 'pointer',
      borderLeft: rule(selected ? C.accent : 'transparent'),
      background: selected ? C.accentSubtle : 'transparent',
    },
    children: [
      _jsx(Twisty, { hasChildren, collapsed, count: childCount, onToggle }),
      _jsx(Avatar, { letter: memberLetter(member), kind, size: isIc ? L.avatarSm : undefined }),
      _jsxs('div', {
        style: { minWidth: 0 },
        children: [
          _jsx('div', {
            style: {
              fontSize: isIc ? F.micro : F.quiet,
              color: isIc ? C.muted : C.text,
              whiteSpace: 'nowrap',
            },
            children: lead,
          }),
          sub
            ? _jsx('div', {
                style: {
                  color: C.muted,
                  fontSize: F.micro,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                },
                children: sub,
              })
            : null,
        ],
      }),
      // The IC's own progress, as digits, on the row rather than under it.
      isIc
        ? _jsx('div', {
            style: {
              marginLeft: 'auto',
              color: C.muted,
              fontSize: F.micro,
              whiteSpace: 'nowrap',
              flexShrink: 0,
              fontVariantNumeric: 'tabular-nums',
            },
            children: progress,
          })
        : null,
      _jsxs('div', {
        style: {
          // The IC row's progress already claimed the free space, so a second
          // `auto` here would fight it and leave the pair floating mid-row.
          marginLeft: isIc ? S.x3 : 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: S.x2,
          flexShrink: 0,
        },
        children: [
          _jsx(Dot, { state: member.state }),
          _jsx('button', {
            onClick: (e) => {
              e.stopPropagation()
              onChat(member.id)
            },
            title: t('chat_with', { who: member.name }),
            style: {
              background: 'transparent',
              border: hair(C.border),
              color: C.muted,
              borderRadius: R.md,
              // A compact row must not be re-heightened by its own button.
              padding: isIc ? sp(0, S.x1) : sp(S.x1, S.x2),
              fontSize: F.micro,
              cursor: 'pointer',
              fontFamily: 'inherit',
            },
            children: '💬',
          }),
        ],
      }),
    ],
  })
}

function CeoRow() {
  return _jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: S.x3, padding: sp(S.x2, S.x4) },
    children: [
      _jsx(Avatar, { letter: 'R', kind: 'ceo' }),
      _jsxs('div', {
        children: [
          _jsx('div', { style: { fontSize: F.quiet, color: C.text }, children: t('ceo_you') }),
          _jsx('div', { style: { color: C.muted, fontSize: F.micro }, children: t('ceo_note') }),
        ],
      }),
    ],
  })
}

export function DeskPage({ members, selectedId, onSelect, onChat, onOpenFile }) {
  // Which rows CAN fold: anything with children, except the two the reader
  // always needs open (fund is the root, desk is the only way to reach a pod).
  const foldable = useMemo(
    () =>
      new Set(
        (members || [])
          .filter((m) => (members || []).some((c) => c.parent === m.id) && m.id !== 'fund' && m.id !== 'desk')
          .map((m) => m.id),
      ),
    [members],
  )
  // The state tracks what the reader OPENED, not what is closed, so folded is a
  // derivation rather than a snapshot. Holding `collapsed` in state instead read
  // the roster at first render -- when it is still empty, giving an empty set
  // and every pod drawn open -- and a pod added to sectors.yaml later would have
  // needed a second correction pass to fold. Neither case exists here: unopened
  // means folded, whenever the row shows up.
  const [expanded, setExpanded] = useState(() => new Set())
  const collapsed = useMemo(
    () => new Set([...foldable].filter((id) => !expanded.has(id))),
    [foldable, expanded],
  )

  const toggle = (id) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const rows = useMemo(() => orgRows(members, collapsed), [members, collapsed])
  const childCounts = useMemo(() => {
    const counts = new Map()
    for (const m of members || []) {
      if (!m.parent) continue
      counts.set(m.parent, (counts.get(m.parent) || 0) + 1)
    }
    return counts
  }, [members])
  const member = findMember(members, selectedId) || (members || [])[0]
  const reportCount = useMemo(
    () => (members || []).filter((m) => m.parent === (member && member.id)).length,
    [members, member],
  )
  const manager = findMember(members, member && member.parent)
  if (!member) return _jsx(Notice, { tone: 'info', children: t('no_members') })

  return _jsxs(_Fragment, {
    children: [
      _jsx(Hero, {
        member,
        reportCount,
        reportsTo: manager ? t('reports_to', { who: manager.name }) : '',
        onChat: () => onChat(member.id),
        onOpenFile,
      }),
      _jsx(Sect, { label: t('org_chart'), hint: t('dot_legend') }),
      _jsx(Card, {
        pad: sp(S.x1, 0),
        children: _jsxs(_Fragment, {
          children: [
            _jsx(CeoRow, {}),
            _jsx('div', {
              children: rows.map((r) =>
                _jsx(OrgRow, {
                  member: r.member,
                  depth: r.depth,
                  hasChildren: r.hasChildren,
                  collapsed: r.collapsed,
                  childCount: childCounts.get(r.member.id) || 0,
                  selected: r.member.id === member.id,
                  onSelect,
                  onChat,
                  onToggle: () => toggle(r.member.id),
                }, r.member.id),
              ),
            }),
          ],
        }),
      }),
    ],
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// 10. Run page
// ─────────────────────────────────────────────────────────────────────────────
