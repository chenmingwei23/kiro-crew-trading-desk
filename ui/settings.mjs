/** The Settings page: language, where the data lives, and Advanced (§6). */

import { useState } from 'react'
import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from 'react/jsx-runtime'
import { C, F, L, R, S, W, hair, sp } from './theme.mjs'
import { LANGS, getLang, setLang, t } from './i18n.mjs'

/** An icon well plus a title and one line of description — the card head (§6). */
function Well({ children }) {
  return _jsx('div', {
    style: {
      width: 44,
      height: 44,
      borderRadius: R.lg,
      background: C.bg2,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
      color: C.text,
    },
    children,
  })
}

function Glyph({ d }) {
  return _jsx('svg', {
    width: 20,
    height: 20,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
    children: _jsx('path', { d }),
  })
}

const ICON = {
  lang: 'M4 5h16M9 3v2M11 5c0 6-3 10-7 12M8 10c0 4 3 7 7 8M14 20l4-10 4 10M15.5 17h5',
  data: 'M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7',
  about: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 8h.01M11 12h1v5h1',
  advanced: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 11-4 0v-.1A1.7 1.7 0 007.1 19l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.7 1.7 0 003 15H3a2 2 0 110-4h.1A1.7 1.7 0 005 9.1L4.9 9a2 2 0 112.8-2.8l.1.1A1.7 1.7 0 0010 5.1V5a2 2 0 114 0v.1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1A1.7 1.7 0 0021 11h.1a2 2 0 110 4H21',
}

function Section({ icon, title, desc, children }) {
  return _jsxs('div', {
    style: {
      border: hair(C.border),
      borderRadius: R.xl,
      padding: S.x5,
      display: 'flex',
      flexDirection: 'column',
      gap: S.x4,
    },
    children: [
      _jsxs('div', {
        style: { display: 'flex', gap: S.x3, alignItems: 'flex-start' },
        children: [
          _jsx(Well, { children: _jsx(Glyph, { d: icon }) }),
          _jsxs('div', {
            style: { minWidth: 0 },
            children: [
              _jsx('div', { style: { fontSize: F.title, fontWeight: W.bold, letterSpacing: '-0.005em' }, children: title }),
              _jsx('div', { style: { fontSize: F.quiet, color: C.muted, marginTop: S.half, lineHeight: LHQ }, children: desc }),
            ],
          }),
        ],
      }),
      children || null,
    ],
  })
}

const LHQ = 1.5

/** A language choice, with a check badge on the one in force (§6). */
function LangCard({ code, label, on, onPick }) {
  return _jsxs('button', {
    type: 'button',
    className: 'td-pill',
    onClick: () => onPick(code),
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: S.x3,
      minWidth: 200,
      height: L.pill + S.x2,
      padding: sp(0, S.x4),
      borderRadius: R.lg,
      border: hair(on ? C.text : C.border),
      background: C.bg,
      color: C.text,
      fontSize: F.body,
      fontWeight: W.medium,
      cursor: 'pointer',
      textAlign: 'left',
    },
    children: [
      _jsx('span', { children: label }),
      on
        ? _jsx('span', {
            className: 'td-badge-dark',
            style: {
              width: 22,
              height: 22,
              borderRadius: R.pill,
              background: C.text,
              color: C.accentFg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: F.micro,
              flexShrink: 0,
            },
            children: '✓',
          })
        : null,
    ],
  })
}

/**
 * The Settings page.
 *
 * Operational controls sit behind a closed disclosure with one plain risk
 * sentence, and never on the main bar (§2). This app owns no start/stop of its
 * own — the desk's data service is the gateway — so Advanced points at the one
 * destructive thing a reader CAN do here, restarting a colleague's conversation,
 * and says what it costs.
 */
export default function SettingsPage({ version, appRoot, onBack }) {
  const lang = getLang()
  const [open, setOpen] = useState(false)

  return _jsxs('div', {
    style: { maxWidth: 720, margin: '0 auto', padding: sp(S.x6, 0, S.x12), display: 'flex', flexDirection: 'column', gap: S.x4 },
    children: [
      _jsx(Section, {
        icon: ICON.lang,
        title: t('set_lang'),
        desc: t('set_lang_desc'),
        children: _jsx('div', {
          style: { display: 'flex', gap: S.x3, flexWrap: 'wrap' },
          children: LANGS.map((l) =>
            _jsx(LangCard, { code: l.code, label: l.label, on: l.code === lang, onPick: setLang }, l.code),
          ),
        }),
      }),
      _jsx(Section, {
        icon: ICON.data,
        title: t('set_data'),
        desc: t('set_data_desc', { root: appRoot || '—' }),
      }),
      _jsx(Section, {
        icon: ICON.about,
        title: t('set_about'),
        desc: t('set_about_desc', { version: version || '?' }),
      }),
      _jsx(Section, {
        icon: ICON.advanced,
        title: t('set_advanced'),
        desc: t('set_advanced_desc'),
        children: _jsxs('div', {
          style: { display: 'flex', flexDirection: 'column', gap: S.x3, alignItems: 'flex-start' },
          children: [
            _jsx('button', {
              type: 'button',
              className: 'td-pill',
              onClick: () => setOpen((v) => !v),
              style: {
                height: L.pillSm,
                padding: sp(0, S.x4),
                borderRadius: R.pill,
                border: hair(C.border),
                background: C.bg,
                color: C.text,
                fontSize: F.quiet,
                fontWeight: W.medium,
                cursor: 'pointer',
              },
              children: open ? `▾ ${t('set_advanced')}` : `▸ ${t('set_advanced')}`,
            }),
            open
              ? _jsx('div', {
                  style: { fontSize: F.quiet, color: C.muted, lineHeight: 1.6, maxWidth: 560 },
                  children: t('set_reset_desc'),
                })
              : null,
          ],
        }),
      }),
      onBack
        ? _jsx('button', {
            type: 'button',
            className: 'td-pill',
            onClick: onBack,
            style: {
              alignSelf: 'flex-start',
              height: L.pill,
              padding: sp(0, S.x4),
              borderRadius: R.pill,
              border: hair(C.border),
              background: C.bg,
              color: C.text,
              fontSize: F.quiet,
              fontWeight: W.medium,
              cursor: 'pointer',
            },
            children: `‹ ${t('back')}`,
          })
        : null,
    ],
  })
}
