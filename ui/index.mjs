/** The app root: page routing, header, and the durable view. */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { ChatPage } from './chat.mjs'
import { ConfigPage } from './config.mjs'
import { SLOTS_KEY, VIEW_KEY, getAppRoot, load, readJsonFile, readStore, useLoader, writeStore, SHAPE } from './data.mjs'
import { DeskPage } from './desk.mjs'
import { LogsPage } from './logs.mjs'
import { RunPage, todayStr } from './run.mjs'
import SettingsPage from './settings.mjs'
import { getLang, setLang, t, useLang } from './i18n.mjs'
import { C, DeskMark, F, L, LoadError, Pill, R, S, StaleBar, W, hair, injectKeyframes, sp } from './theme.mjs'

/**
 * The five pages the backend actually serves. Labels come from the string table,
 * so a page's name is one word in the reader's language rather than a code name.
 * Nothing that does not exist yet is listed: a tab that leads nowhere is worse
 * than a missing tab.
 */
const PAGES = [
  { id: 'chat', key: 'page_chat' },
  { id: 'desk', key: 'page_desk' },
  { id: 'run', key: 'page_run' },
  { id: 'logs', key: 'page_logs' },
  { id: 'config', key: 'page_config' },
]

/** A 40px capsule row — the tab language of §2, not a folder tab. */
function TabBar({ page, onPage }) {
  return _jsx('div', {
    style: { display: 'flex', gap: S.half },
    children: PAGES.map((p) => {
      const on = p.id === page
      return _jsx('button', {
        type: 'button',
        className: on ? 'td-tab td-tab-on' : 'td-tab',
        // A stable handle for tests and for the harness, so a screenshot script
        // never has to select a tab by its visible text -- which stops working the
        // moment the same tab has a second label.
        'data-page': p.id,
        onClick: () => onPage(p.id),
        style: {
          height: L.pill,
          padding: sp(0, S.x4),
          background: on ? C.text : 'transparent',
          color: on ? C.accentFg : C.muted,
          border: hair('transparent'),
          borderRadius: R.pill,
          fontSize: F.body,
          fontWeight: W.medium,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        },
        children: t(p.key),
      }, p.id)
    }),
  })
}

function SourceBadge({ source }) {
  // There is no sample-data state any more: the runtime never renders a fixture, so a
  // badge for it would be a promise the app cannot keep (§rev7 P0).
  if (source === 'live') return _jsx(Pill, { tone: 'ok', children: t('live') })
  return null
}

/** A round icon button — the only other control shape on the bar. */
function RoundBtn({ label, onClick, children }) {
  return _jsx('button', {
    type: 'button',
    className: 'td-pill',
    'aria-label': label,
    title: label,
    onClick,
    style: {
      width: L.pill,
      height: L.pill,
      borderRadius: R.pill,
      border: hair(C.border),
      background: C.bg,
      color: C.text,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      flexShrink: 0,
    },
    children,
  })
}

/**
 * The sticky top bar (§4): 72px, translucent white, one hairline under it.
 *
 * The wordmark is the ONE place the brand colour appears. Language lives on the
 * bar because it is a preference a reader changes mid-task; everything
 * operational is behind the ellipsis, on the Settings page.
 */
function Header({ page, onPage, source, version, onRefresh, onSettings }) {
  const lang = getLang()
  return _jsxs('div', {
    style: {
      height: L.bar,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: S.x4,
      padding: sp(0, S.x6),
      borderBottom: hair(C.line2),
      background: 'rgba(255,255,255,0.96)',
      backdropFilter: 'saturate(180%) blur(8px)',
      position: 'sticky',
      top: 0,
      zIndex: 30,
      flexShrink: 0,
    },
    children: [
      _jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: S.x6, minWidth: 0 },
        children: [
          _jsxs('div', {
            style: { display: 'flex', alignItems: 'center', gap: S.x2, flexShrink: 0 },
            children: [
              _jsx(DeskMark, { size: 24 }),
              _jsx('span', {
                style: { fontSize: F.title, fontWeight: W.bold, color: C.brand, letterSpacing: '-0.01em' },
                children: t('app_name'),
              }),
              _jsx(SourceBadge, { source }),
            ],
          }),
          _jsx(TabBar, { page, onPage }),
        ],
      }),
      _jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: S.x2, flexShrink: 0 },
        children: [
          _jsx('button', {
            type: 'button',
            className: 'td-pill',
            onClick: () => setLang(lang === 'zh-CN' ? 'en' : 'zh-CN'),
            style: {
              height: L.pillSm,
              padding: sp(0, S.x3),
              borderRadius: R.pill,
              border: hair(C.border),
              background: C.bg,
              color: C.text,
              fontSize: F.quiet,
              fontWeight: W.medium,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            },
            children: t('lang_switch'),
          }),
          _jsx(RoundBtn, {
            label: t('refresh'),
            onClick: onRefresh,
            children: _jsx('svg', {
              width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
              strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': 'true',
              children: _jsx('path', { d: 'M21 12a9 9 0 11-3.2-6.9M21 4v5h-5' }),
            }),
          }),
          _jsx(RoundBtn, {
            label: t('settings'),
            onClick: onSettings,
            children: _jsxs('svg', {
              width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': 'true',
              children: [
                _jsx('circle', { cx: 12, cy: 5, r: 1.5 }),
                _jsx('circle', { cx: 12, cy: 12, r: 1.5 }),
                _jsx('circle', { cx: 12, cy: 19, r: 1.5 }),
              ],
            }),
          }),
          _jsx('span', { style: { fontSize: F.micro, color: C.muted }, children: `v${version || '?'}` }),
        ],
      }),
    ],
  })
}

function useVersion() {
  const [version, setVersion] = useState('')
  useEffect(() => {
    let alive = true
    getAppRoot()
      .then((root) => (root ? readJsonFile(`${root}/app.json`) : null))
      .then((m) => {
        if (alive && m && m.version) setVersion(m.version)
      })
    return () => {
      alive = false
    }
  }, [])
  return version
}

function PageBody(p) {
  const { page, org, date, setDate, selectedId, setSelectedId, openPath, setOpenPath, goChat, goPage } = p
  const members = (org && org.members) || []

  if (page === 'chat') {
    return _jsx(ChatPage, {
      org,
      orgAt: p.orgAt,
      selectedId,
      onProfile: () => goPage('desk'),
      // A participant's name opens that crew's profile — the Desk page's own
      // semantics, reused rather than reinvented.
      onOpenMember: (id) => {
        setSelectedId(id)
        goPage('desk')
      },
      // The rail switches conversation in place, which is what Slack's DM list
      // does — no page change, the thread panel closes with the member.
      onSelectMember: setSelectedId,
      onOpenFile: (path) => {
        setOpenPath(path)
        goPage('logs')
      },
      rememberedSlots: p.rememberedSlots,
      onReset: p.onReset,
    })
  }
  if (page === 'desk') {
    return _jsx(DeskPage, {
      members,
      selectedId,
      onSelect: setSelectedId,
      onChat: goChat,
      onOpenFile: (p) => {
        setOpenPath(p)
        goPage('logs')
      },
    })
  }
  if (page === 'run') return _jsx(RunPage, { date, onDate: setDate })
  if (page === 'config') return _jsx(ConfigPage, {})
  return _jsx(LogsPage, { date, onDate: setDate, openPath, onOpenPath: setOpenPath })
}

export default function TradingDeskApp() {
  const view = useMemo(() => readStore(VIEW_KEY), [])
  const [page, setPage] = useState(() => (PAGES.some((p) => p.id === view.page) ? view.page : 'chat'))
  const [date, setDate] = useState(todayStr)
  const [selectedId, setSelectedId] = useState(() => view.memberId || 'fund')
  const [openPath, setOpenPath] = useState('')
  const [rememberedSlots, setRememberedSlots] = useState(() => readStore(SLOTS_KEY))
  const [settings, setSettings] = useState(false)
  const [appRoot, setAppRoot] = useState('')
  const version = useVersion()
  // Read once at the root; every child just calls `t()` at render time (§6).
  useLang()

  useEffect(injectKeyframes, [])

  useEffect(() => {
    let alive = true
    getAppRoot().then((root) => {
      if (alive && root) setAppRoot(root)
    })
    return () => {
      alive = false
    }
  }, [])

  // Where you were, so leaving the page and coming back returns you to the same
  // member's chat instead of resetting to the fund manager.
  useEffect(() => {
    writeStore(VIEW_KEY, { page, memberId: selectedId })
  }, [page, selectedId])

  const orgLoader = useCallback(
    (signal) => load('/org', SHAPE.org, signal),
    [],
  )
  const org = useLoader(orgLoader, [], 30000)

  const goChat = useCallback((id) => {
    setSelectedId(id)
    setPage('chat')
  }, [])

  const goPage = useCallback((id) => setPage(id), [])

  // Remember the key a reset minted, and re-read /org at once so the server's own
  // copy of it lands in this session rather than up to a poll interval later.
  const reloadOrg = org.reload
  const onReset = useCallback((memberId, slotKey) => {
    setRememberedSlots((prev) => {
      const next = { ...prev, [memberId]: { key: slotKey, at: Date.now() } }
      writeStore(SLOTS_KEY, next)
      return next
    })
    reloadOrg()
  }, [reloadOrg])

  const body = org.error && !org.data
    ? _jsx(LoadError, { message: org.error, detail: org.detail, what: t('what_members'), onRetry: org.reload })
    : _jsx(PageBody, {
        page,
        org: org.data,
        orgAt: org.at,
        date,
        setDate,
        selectedId,
        setSelectedId,
        openPath,
        setOpenPath,
        goChat,
        goPage,
        rememberedSlots,
        onReset,
      })

  // The Chat page owns its own three-column scrolling, so the shell must NOT add
  // page padding or a second scroller around it; the other pages get both.
  const bare = page === 'chat'

  return _jsxs('div', {
    className: 'td-root',
    // `overflow: hidden` is load-bearing, not tidiness: anything that outgrows the
    // root used to spill past the app's own white surface onto the dashboard's dark
    // page, which is what a reader saw as "the light card ends halfway down".
    style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'hidden' },
    children: [
      _jsx(Header, {
        page,
        onPage: (id) => {
          setSettings(false)
          setPage(id)
        },
        source: org.source,
        version,
        onRefresh: org.reload,
        onSettings: () => setSettings((v) => !v),
      }),
      settings
        ? _jsx('div', {
            className: 'td-scroll',
            style: { flex: 1, minHeight: 0, padding: sp(0, S.x6) },
            children: _jsx(SettingsPage, { version, appRoot, onBack: () => setSettings(false) }),
          })
        : bare
          ? _jsx('div', { style: { flex: 1, minHeight: 0, display: 'flex' }, children: body })
          : _jsx('div', {
              className: 'td-scroll',
              style: { flex: 1, minHeight: 0, padding: sp(S.x5, S.x6, S.x12) },
              children: _jsxs(_Fragment, {
                children: [
                  _jsx(StaleBar, { message: org.data ? org.error : '', detail: org.detail, onRetry: org.reload }),
                  body,
                ],
              }),
            }),
    ],
  })
}
