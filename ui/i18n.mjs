/** 中文 / English for the app's own chrome (kirocrew-app-ui §6). */

import { useSyncExternalStore } from 'react'

export const LANGS = [
  { code: 'zh-CN', label: '中文' },
  { code: 'en', label: 'English' },
]

const KEY = 'trading-desk.lang'

function detect() {
  try {
    const saved = window.localStorage.getItem(KEY)
    if (saved && LANGS.some((l) => l.code === saved)) return saved
  } catch (err) {
    /* private mode — fall through to the default */
  }
  return 'zh-CN'
}

let current = detect()
const subs = new Set()

export function getLang() {
  return current
}

export function setLang(code) {
  if (!LANGS.some((l) => l.code === code) || code === current) return
  current = code
  try {
    window.localStorage.setItem(KEY, code)
  } catch (err) {
    /* the switch still applies for this visit, it just is not remembered */
  }
  subs.forEach((fn) => fn())
}

function subscribe(fn) {
  subs.add(fn)
  return () => subs.delete(fn)
}

/** The root calls this once; children just call `t()` at render time. */
export function useLang() {
  return useSyncExternalStore(subscribe, getLang, getLang)
}

/**
 * A chrome string.
 *
 * A missing key renders as the key rather than throwing or rendering `undefined`:
 * a gap in the table should be visible to whoever is looking at the screen and
 * harmless to the person using it.
 */
export function t(key, vars) {
  const table = TABLE[current] || TABLE['zh-CN']
  const fallback = TABLE['zh-CN']
  const entry = table[key] !== undefined ? table[key] : fallback[key]
  if (entry === undefined) return key
  if (typeof entry === 'function') return entry(vars || {})
  if (!vars) return entry
  return String(entry).replace(/\{(\w+)\}/g, (m, name) => (vars[name] === undefined ? m : String(vars[name])))
}

/**
 * A member's human job title, for the "this is an AI" label on the author line.
 *
 * The author line used to print the raw agent id (`tada-fund-manager`) in
 * monospace, which is an internal noun in a machine typeface — two of the
 * standard's rules at once. The id is still available as the label's tooltip for
 * anyone who needs it. English titles come from the roster; Chinese has no title
 * field on the backend, so it is mapped here.
 */
const TITLE_ZH = {
  fund: '基金经理',
  macro: '宏观策略',
  desk: '研究总管',
  risk: '组合风控',
  trader: '交易员',
  scrum: '节奏管理',
}

//: The ten IC roles, keyed by the ROLE SUFFIX of an `ic-<pod>-<role>` id. Keyed
//: by suffix rather than by whole id because nine pods draw the same ten roles —
//: one table, not ninety entries. Longest-first so `risk-aggressive` is not read
//: as some pod's `aggressive`.
const IC_TITLE_ZH = {
  'risk-conservative': '风险评审 · 保守',
  'risk-aggressive': '风险评审 · 激进',
  'risk-neutral': '风险评审 · 中性',
  fundamentals: '基本面分析师',
  technicals: '技术面分析师',
  sentiment: '情绪分析师',
  news: '新闻分析师',
  trader: '组内 Trader',
  bull: '多头研究员',
  bear: '空头研究员',
}

/** The role suffix of an `ic-<pod>-<role>` id, or '' when it is not an IC.
 *  Module-private: `memberTitle` is the only caller, and theme.mjs keeps its own
 *  copy of the role table for the monogram rather than importing across. */
function icRole(id) {
  const text = String(id || '')
  if (!text.startsWith('ic-')) return ''
  for (const role of Object.keys(IC_TITLE_ZH)) {
    if (text.endsWith(`-${role}`)) return role
  }
  return ''
}

export function memberTitle(member) {
  if (!member) return ''
  if (current === 'zh-CN') {
    if (TITLE_ZH[member.id]) return TITLE_ZH[member.id]
    const role = icRole(member.id)
    if (role) return IC_TITLE_ZH[role]
    if (String(member.id || '').startsWith('lm')) return `${member.pod || ''} 组长`.trim()
  }
  return String(member.title || '')
}

/**
 * The two tables, in the same key order.
 *
 * Only the app's OWN words are here. Everything a crew member wrote — a brief, a
 * regime call, a thread title — is shown as written, because a switch cannot
 * translate it and pretending otherwise would put words in their mouth.
 */

//: Display phrases the BACKEND authors and hands over as finished text —
//: `state_msg` and an `output_sources` label. They are the app's own words, but
//: they do not arrive through `t()`, so the switch cannot reach them without a
//: table keyed on the Chinese the backend wrote.
const PHRASE_EN = {
  // org.py `_state_from`
  '卡住了，等人看一眼': 'stuck — needs a look',
  正在处理今天的活: 'working on today',
  今天的活已交: "today's work is in",
  手上的活还没收尾: 'still wrapping up',
  在位待命: 'on station',
  '新会话已备好，等你说第一句': 'session ready — say the first word',
  尚未开工: 'not started',
  // org.py `_ic_state`
  本组今天没有标的: 'no tickers in this pod today',
  已交: 'delivered',
  进行中: 'in progress',
  // roster `output_sources` labels
  昨日简报: "yesterday's brief",
  昨日汇报: "yesterday's report",
  今日宏观简报: "today's macro brief",
  最近组报告: 'latest pod report',
  最近风控报告: 'latest risk report',
  成交记录: 'fills',
}

/**
 * A backend-authored display phrase, in the reader's language.
 *
 * A phrase the table does not know is returned AS WRITTEN. That is the important
 * half: `state_msg` carries an EVENT message when one exists, which a crew member
 * wrote, and the rule above says a switch does not translate those. Two shapes
 * are decomposed first, because the backend glues a value onto its own phrase:
 * a leading `N/M` count (an IC's progress) and a trailing ISO date (an output
 * label). The value is kept and only the phrase around it is looked up.
 */
export function phrase(text) {
  const s = String(text || '').trim()
  if (!s || current === 'zh-CN') return s
  if (PHRASE_EN[s]) return PHRASE_EN[s]
  const counted = s.match(/^(\d+\s*\/\s*\d+)\s+(.*)$/)
  if (counted && PHRASE_EN[counted[2]]) return `${counted[1]} ${PHRASE_EN[counted[2]]}`
  const dated = s.match(/^(.*?)\s+(\d{4}-\d{2}-\d{2})$/)
  if (dated && PHRASE_EN[dated[1]]) return `${PHRASE_EN[dated[1]]} ${dated[2]}`
  return s
}

const TABLE = {
  'zh-CN': {
    // chrome
    app_name: 'Trading Desk',
    live: '实时',
    refresh: '刷新',
    page_chat: '对话',
    page_desk: '桌子',
    page_run: '今日',
    page_config: '设置项',
    page_logs: '产出',
    more: '更多',
    settings: '设置',
    back: '返回',
    lang_switch: '中文 / EN',

    // rail
    rail_search: '找人或找话题',
    rail_chain: '指挥链',
    rail_pods: ({ n }) => `${n} 个行业组`,
    rail_empty: '还没有成员数据。',

    // chat
    ai_of: ({ title }) => `AI ${title}`,
    you: '你',
    protocol_author: '协议消息',
    composer_to: ({ name }) => `跟 ${name} 说点什么…`,
    composer_plain: '说点什么…',
    composer_hint: 'Enter 发送 · Shift+Enter 换行',
    composer_queue: '他在忙时你打的话会排队',
    composer_queued: '已排到下一句，他说完就看',
    send: '发送',
    queue: '排队',
    walk_fold: ({ n }) => `过程 · ${n} 步`,
    walk_open: '展开这一段的过程',
    walk_close: '收起这一段的过程',
    fold_brief: '任务简报',
    fold_brief_hint: '展开这条 thread 的任务简报',
    fold_protocol: '协议消息',
    fold_protocol_hint: '展开这条给 agent 的协议消息',
    writing: '正在写…',
    load_older: '加载更早的消息',
    no_session: '尚未开工',
    no_session_hint: '这位同事还没有被派活。跟他说第一句，就会给他开一个会话。',

    // row actions
    act_quote: '引用',
    act_copy: '复制',
    act_thread: '开线程',
    act_thread_open: '打开这条消息的线程',
    act_thread_new: '在这条消息上开一条线程',
    act_thread_missing: '这个 backend 还没有开线程这个能力，正在等它上线',
    act_thread_nested: '线程里不能再开线程',

    // reply bar / thread panel
    reply_n: ({ n }) => `${n} 条回复`,
    reply_latest: ({ time }) => `最新 ${time}`,
    reply_open: '打开线程 ›',
    reply_view: '查看线程',
    thread_anchor: ({ time }) => `挂在你 ${time} 那句话下面`,
    thread_close: '关闭',
    thread_kind_clone: '分身',
    thread_kind_dispatch: '派工',
    thread_in_panel: '在这条线里说话…',
    thread_only_here: '只有这条线里的人看得到',
    threads_loose: ({ n }) => `进行中的工作 ${n}`,

    // status legend
    legend_online: '在线',
    legend_working: '正在工作',
    legend_idle: '空闲',
    legend_fold: '过程 = 中间独白和工具调用，点开看全部',

    // errors
    read_failed: ({ what }) => `暂时打不开${what}`,
    read_failed_hint: '请稍后重试',
    loading: ({ what }) => `载入${what}…`,
    what_members: '这张桌子的成员',
    what_config: '设置项',
    what_run: '今日进度',
    what_output: '产出',
    what_file: '这份文件',
    what_thread: '这条线程',
    state_done: '已完成',
    state_work: '进行中',
    state_fail: '受阻',
    org_chart: '组织架构',
    dot_legend: '绿点在线 · 橙点正在工作 · 灰点空闲',
    reports_to: ({ who }) => `向 ${who} 汇报`,
    direct_reports: '直属下级',
    recent_output: '最近产出',
    status_label: '状态',
    no_members: '还没有成员数据。',
    ceo_you: '你',
    ceo_note: 'CEO · 只对 fund-manager 下指令',
    chat_direct: '💬 直接对话',
    pod_suffix: '组',
    fold_open: ({ n }) => `展开组内 ${n} 人`,
    fold_close: '收起组内成员',
    chat_with: ({ who }) => `与 ${who} 对话`,
    reply_here: '回复此线程',
    receipt_note: '开这条线程时的交代',
    thread_empty: '这条线程还没有记录。',
    this_thread: '这条线程',
    panel_resize: '拖动调整线程面板宽度',
    rail_hide: '收起成员栏',
    rail_show: '展开成员栏',
    empty_run_title: '今天还没有开工',
    empty_run: '今天还没有开工。到「对话」跟基金经理说一句，桌子就会跑起来。',
    empty_output: '这一天没有产出。换一个日期，或者先让桌子跑一轮。',
    jump_to: ({ day }) => `看 ${day}`,
    pick_output: '左边点一项，内容出现在这里。',
    retry: '重试',
    retry_hint: '再读一次',
    stale: '刚才没读到新的，这是上一次的内容',
    route_missing: ({ what }) => `这个版本还没有${what}这个功能`,

    // settings page
    set_title: '设置',
    set_lang: '界面语言',
    set_lang_desc: '只改界面文字。同事们写的内容按他们写的语言显示，不会被翻译。',
    set_about: '关于',
    set_about_desc: ({ version }) =>
      `Trading Desk v${version}。15 位 AI 同事替你把一天的研究跑完：宏观判环境，9 个行业组各自研究自己的标的，风控算敞口。下单一律要你按一次。`,
    set_advanced: '高级',
    set_advanced_desc: '这些操作会影响正在跑的工作，平时不需要用。',
    set_reset_desc: '重开某位同事的会话会让他忘掉之前聊过的内容，旧会话保留在侧栏。到「桌子」页点那个人可以单独重开。',
    set_data: '数据来源',
    set_data_desc: ({ root }) => `这张桌子的文件都在 ${root}`,
  },

  en: {
    app_name: 'Trading Desk',
    live: 'Live',
    refresh: 'Refresh',
    page_chat: 'Chat',
    page_desk: 'Desk',
    page_run: 'Today',
    page_config: 'Settings',
    page_logs: 'Output',
    more: 'More',
    settings: 'Settings',
    back: 'Back',
    lang_switch: 'EN / 中文',

    rail_search: 'Find a person or a topic',
    rail_chain: 'Reports to you',
    rail_pods: ({ n }) => `${n} sector teams`,
    rail_empty: 'No members yet.',

    ai_of: ({ title }) => `AI ${title}`,
    you: 'You',
    protocol_author: 'Protocol message',
    composer_to: ({ name }) => `Message ${name}…`,
    composer_plain: 'Message…',
    composer_hint: 'Enter to send · Shift+Enter for a new line',
    composer_queue: 'If they are busy, what you type waits its turn',
    composer_queued: 'Queued — they will read it when they finish',
    send: 'Send',
    queue: 'Queue',
    walk_fold: ({ n }) => `${n} step${n === 1 ? '' : 's'} along the way`,
    walk_open: 'Show the steps',
    walk_close: 'Hide the steps',
    fold_brief: 'The brief',
    fold_brief_hint: 'Show the brief this thread started from',
    fold_protocol: 'Protocol message',
    fold_protocol_hint: 'Show this message written for an agent',
    writing: 'Writing…',
    load_older: 'Load earlier messages',
    no_session: 'Not started yet',
    no_session_hint: 'No work has been given to this colleague yet. Say something and a conversation opens.',

    act_quote: 'Quote',
    act_copy: 'Copy',
    act_thread: 'Thread',
    act_thread_open: 'Open this message’s thread',
    act_thread_new: 'Start a thread on this message',
    act_thread_missing: 'This backend cannot open threads yet — waiting on it',
    act_thread_nested: 'A thread cannot contain another thread',

    reply_n: ({ n }) => `${n} ${n === 1 ? 'reply' : 'replies'}`,
    reply_latest: ({ time }) => `last ${time}`,
    reply_open: 'Open thread ›',
    reply_view: 'View thread',
    thread_anchor: ({ time }) => `Hangs under what you said at ${time}`,
    thread_close: 'Close',
    thread_kind_clone: 'Own line',
    thread_kind_dispatch: 'Delegated',
    thread_in_panel: 'Reply in this thread…',
    thread_only_here: 'Only people in this thread see it',
    threads_loose: ({ n }) => `${n} in progress`,

    legend_online: 'Online',
    legend_working: 'Working',
    legend_idle: 'Idle',
    legend_fold: 'Steps = the narration and tool calls in between; open to read them',

    read_failed: ({ what }) => `Cannot open ${what} right now`,
    read_failed_hint: 'Try again in a moment',
    loading: ({ what }) => `Loading ${what}…`,
    what_members: 'this desk’s members',
    what_config: 'settings',
    what_run: 'today’s progress',
    what_output: 'output',
    what_file: 'this file',
    what_thread: 'this thread',
    state_done: 'Done',
    state_work: 'Working',
    state_fail: 'Stuck',
    org_chart: 'Org chart',
    dot_legend: 'Green online · Orange working · Grey idle',
    reports_to: ({ who }) => `Reports to ${who}`,
    direct_reports: 'Direct reports',
    recent_output: 'Recent output',
    status_label: 'Status',
    no_members: 'No members yet.',
    ceo_you: 'You',
    ceo_note: 'CEO · you brief the fund manager only',
    chat_direct: '💬 Open chat',
    pod_suffix: 'pod',
    fold_open: ({ n }) => `Show the ${n} people in this pod`,
    fold_close: 'Hide this pod',
    chat_with: ({ who }) => `Chat with ${who}`,
    reply_here: 'Reply in this thread',
    receipt_note: 'What was said when this thread was opened',
    thread_empty: 'Nothing recorded on this thread yet.',
    this_thread: 'this thread',
    panel_resize: 'Drag to resize the thread panel',
    rail_hide: 'Hide the member list',
    rail_show: 'Show the member list',
    empty_run_title: 'Nothing has started today',
    empty_run: 'Nothing has started today. Say something to the fund manager on the Chat page and the desk goes to work.',
    empty_output: 'Nothing was produced on this day. Pick another date, or let the desk run first.',
    jump_to: ({ day }) => `Go to ${day}`,
    pick_output: 'Pick something on the left and it opens here.',
    retry: 'Retry',
    retry_hint: 'Read it again',
    stale: 'Nothing new came back — this is what it last said',
    route_missing: ({ what }) => `This version does not have ${what} yet`,

    set_title: 'Settings',
    set_lang: 'Interface language',
    set_lang_desc:
      'Changes the interface only. What your colleagues wrote stays in the language they wrote it in — a switch cannot translate it.',
    set_about: 'About',
    set_about_desc: ({ version }) =>
      `Trading Desk v${version}. Fifteen AI colleagues run a day of research for you: macro reads the regime, nine sector teams cover their own names, risk sizes the exposure. Every order still needs your press.`,
    set_advanced: 'Advanced',
    set_advanced_desc: 'These affect work that is running. You should not need them day to day.',
    set_reset_desc:
      'Restarting a colleague’s conversation makes them forget what you discussed; the old one stays in your sidebar. Open the Desk page and pick a person to restart just them.',
    set_data: 'Where the data lives',
    set_data_desc: ({ root }) => `This desk’s files are under ${root}`,
  },
}
