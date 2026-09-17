/** English / 中文 for the app's own chrome (kirocrew-app-ui §6). */

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
    /* private mode — fall through to the language guess */
  }
  // A public app opens in English. A saved preference is honoured above; with
  // none, a browser that asks for Chinese gets Chinese and everyone else English.
  try {
    const nav = typeof navigator !== 'undefined' ? navigator : null
    const lang = (nav && (nav.language || (nav.languages && nav.languages[0]))) || ''
    if (String(lang).toLowerCase().startsWith('zh')) return 'zh-CN'
  } catch (err) {
    /* no navigator — fall through to English */
  }
  return 'en'
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
  const table = TABLE[current] || TABLE['en']
  const fallback = TABLE['en']
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
//: `state_msg`, `output_sources` labels, duty prose, group labels, stage names and
//: run-view words. English is canonical now, so this table is keyed on the ENGLISH
//: the backend writes and maps to Chinese. A phrase absent here is returned as
//: written by `phrase()`, which is what keeps crew-authored text untranslated.
//:
//: Counted / dated forms use `{n}`-style placeholders; `phrase()` fills them from
//: the value it kept while decomposing, so the number or date survives the lookup.
const PHRASE_ZH = {
  // member state messages (state_msg)
  'on station': '在位待命',
  'not started': '尚未开工',
  'not started today': '今天还没开工',
  'stuck, needs a look': '卡住了，等人看一眼',
  "working on today's tasks": '正在处理今天的活',
  "today's work is delivered": '今天的活已交',
  "the work in hand isn't wrapped up yet": '手上的活还没收尾',
  'a new session is ready, waiting for your first message': '新会话已备好，等你说第一句',
  'no tickers for this pod today': '本组今天没有覆盖标的',
  'pod report delivered today': '今天组报告已交',
  "today's output delivered": '今天的产出已交',
  'no output today': '今天没有产出',
  'no pod report back yet': '组报告还没回来',
  'waiting on the rest': '在等其他人',
  'no reason given': '没有给出原因',

  // counted / dated forms — the value is kept, the phrase looked up
  '{a}/{b} delivered': '{a}/{b} 已交',
  '{a}/{b} in progress': '{a}/{b} 进行中',
  '0/{b} not started': '0/{b} 尚未开工',
  "today's {noun} delivered": '今天的{noun}已交',
  'no {noun} delivered today': '今天没有{noun}交出',
  '{n} outputs in, rolling up': '{n} 份产出到位，正在汇总',
  '{n} outputs stalled at {hhmm}, no pod report yet': '{n} 份产出卡在 {hhmm}，组报告还没出',
  'the last one stalled at {hhmm}': '最后一份卡在 {hhmm}',
  '{a} of {b} pods delivered, {tail}': '{b} 个组里 {a} 个已交，{tail}',
  '{n} pods running, {tail}': '{n} 个组在跑，{tail}',
  '{date} is a historical record': '{date} 是历史记录',
  "organizing today's research": '正在整理今天的研究',
  "today's brief delivered": '今天的汇报已交',
  'in progress': '进行中',

  // output-source labels (output_sources[].label)
  brief: '汇报',
  "Yesterday's brief": '昨日汇报',
  'macro brief': '宏观简报',
  'Latest macro brief': '最近宏观简报',
  'desk view': '桌面观点',
  'Latest desk view': '最近桌面观点',
  'risk review': '风控复核',
  'Latest risk review': '最近风控复核',
  'pod report': '组报告',
  'Latest pod report': '最近组报告',
  'CEO brief': 'CEO 汇报',
  'run events': '运行事件',
  output: '产出',

  // duty prose (duty, duty_template)
  "Runs the desk's day-to-day operations, breaking the day's intent into research and allocation actions, and owns the final conclusion.":
    '负责桌子的日常运营，把当天的意图拆成研究和配置动作，并对最终结论负责。',
  "Each day, calls the macro and market-environment view first, framing the risk appetite and main themes for each pod's stock picking.":
    '每天先给出宏观和市场环境判断，为各组选股框定风险偏好和主要主题。',
  "Coordinates research across {pod_count} pods, rolling each pod's conclusions into one executable desk view.":
    '协调 {pod_count} 个行业组的研究，把各组结论汇成一份可执行的桌面观点。',
  "Rolls each pod's conclusions into one executable desk view, resolving conflicts and priorities across pods.":
    '把各组结论汇成一份可执行的桌面观点，处理组间的冲突和优先级。',
  "Independently reviews every proposal's exposure, sizing and stops — the last gate before an order goes out.":
    '独立复核每份提案的敞口、仓位和止损——下单前的最后一道关。',
  'Turns reviewed views into concrete plans: ticker, direction, size, timing.':
    '把复核过的观点变成具体计划：标的、方向、仓位、时机。',
  "Keeps the desk's rhythm, watching the day's progress and blockers so what is due gets delivered on time.":
    '把握桌子的节奏，盯着当天的进展和阻塞，让该交的东西按时交出。',
  'Runs the {pod} pod ({tickers}): converges the pod\'s conclusions into one pod report.':
    '带 {pod} 组（{tickers}）：把组内结论收敛成一份组报告。',

  // group label (group)
  // The `group` field is NOT here. Both producers leave the word for "pod" out of
  // it, and `groupLabel()` appends the reader's own -- see its comment for why a
  // pattern would be the wrong tool for a label that is otherwise free text.

  // stage names (stages[].name)
  Analysis: '分析',
  Debate: '多空',
  Proposal: '提案',
  Risk: '风控',

  // run-view event words and step labels
  dispatched: '已下派',
  delivered: '已交',
  stuck: '卡住',
  progress: '进展',
  started: '开工',
  'brief received': '收到汇报',
  'pod report not written': '组报告还没写',
  'pod report delivered': '组报告已交',
  'macro brief delivered': '宏观简报已交',
  'risk review delivered': '风控复核已交',
  'desk view delivered': '桌面观点已交',
  'brief delivered ({path})': '汇报已交（{path}）',
  'dispatched, {n} tickers assigned': '已下派，分了 {n} 个标的',
  '{stage} {a}/{b}': '{stage} {a}/{b}',
  '{stage} {a}/{b} back': '{stage} {a}/{b} 回来',
  'no pod report that day': '那天没有组报告',
  'CEO brief written': 'CEO 汇报已写',
  "this round's dispatch is wrapped up": '这一轮派工收尾了',
  'this step is done': '这一步完成了',

  // thread fallbacks
  'new thread': '新线程',
  'dispatch · {worker}': '派工 · {worker}',
  'just opened, nothing said yet': '刚开，还没说话',
  'this session is gone': '这个会话已经不在了',
}

/**
 * The templates in `PHRASE_ZH`, compiled once into matchers.
 *
 * The backend glues a value into the middle of its own sentence -- a count, a
 * time, a pod name, a path -- so an exact lookup misses and the reader is left
 * with English inside a Chinese screen. A template entry (`the last one stalled
 * at {hhmm}`) becomes an anchored pattern whose captures fill the same
 * placeholders on the Chinese side.
 *
 * Two guards keep this from reaching text a crew member wrote, which must never
 * be translated:
 *
 * - The pattern is anchored at both ends, so it describes the WHOLE message.
 * - A template needs at least `MIN_LITERAL` characters of its own words. Without
 *   that floor, a short entry compiles to a pattern that matches almost anything
 *   and would rewrite the tail of a sentence someone dictated -- which is why the
 *   `group` field is handled by `groupLabel()` and not by an entry here at all.
 *   The one short entry that remains is matched by shape instead: `{stage} {a}/{b}`
 *   arrives as `Analysis 6/8` and is handled by the counted rules above.
 *
 * More literal text wins, so `0/{b} not started` is tried before the general
 * `{a}/{b} not started`.
 */
const MIN_LITERAL = 10
const TEMPLATES = Object.keys(PHRASE_ZH)
  .filter((key) => key.includes('{'))
  .map((key) => {
    const names = [...key.matchAll(/\{(\w+)\}/g)].map((m) => m[1])
    const literal = key.replace(/\{\w+\}/g, '')
    const body = key
      .split(/\{\w+\}/)
      .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('(.+?)')
    return { key, re: new RegExp('^' + body + '$'), names, weight: literal.length }
  })
  .filter((entry) => entry.weight >= MIN_LITERAL)
  .sort((a, b) => b.weight - a.weight)

/**
 * A backend-authored display phrase, in the reader's language.
 *
 * A phrase the table does not know is returned AS WRITTEN. That is the important
 * half: `state_msg` carries an EVENT message when one exists, which a crew member
 * wrote, and the rule above says a switch does not translate those. Four shapes
 * are tried before giving up, because the backend glues a value onto its own
 * phrase: a leading `N/M` count (an IC's progress), a trailing `N/M` count (a
 * stage label such as `Analysis 6/8`), a trailing ISO date (an output label), and
 * a template with the value in the middle. The value is kept and only the phrase
 * around it is looked up.
 *
 * `depth` is internal. A template slot is translated by calling back in, and the
 * cap stops a pathological table entry -- one whose slot could swallow the whole
 * message -- from recursing forever.
 */
export function phrase(text, depth = 0) {
  const s = String(text || '').trim()
  if (!s || current === 'en') return s
  if (PHRASE_ZH[s] !== undefined) return PHRASE_ZH[s]
  if (depth >= 3) return s
  // Leading `N/M` count: `8/8 delivered`, `3/9 in progress`, `0/9 not started`.
  const counted = s.match(/^(\d+)\s*\/\s*(\d+)\s+(.*)$/)
  if (counted) {
    const rest = counted[3]
    // `0/N not started` has its own form; everything else is `{a}/{b} <phrase>`.
    if (counted[1] === '0' && PHRASE_ZH['0/{b} ' + rest] !== undefined) {
      return fill(PHRASE_ZH['0/{b} ' + rest], { a: counted[1], b: counted[2] })
    }
    const keyed = PHRASE_ZH['{a}/{b} ' + rest]
    if (keyed !== undefined) return fill(keyed, { a: counted[1], b: counted[2] })
  }
  // Trailing `N/M` count, with an optional tail word: `Analysis 6/8`, `Debate 2/2 back`.
  const trailing = s.match(/^(.*?)\s+(\d+)\s*\/\s*(\d+)(\s+\S+)?$/)
  if (trailing) {
    const head = PHRASE_ZH[trailing[1]]
    const tail = (trailing[4] || '').trim()
    const shape = tail ? `{stage} {a}/{b} ${tail}` : '{stage} {a}/{b}'
    if (head !== undefined && PHRASE_ZH[shape] !== undefined) {
      return fill(PHRASE_ZH[shape], { stage: head, a: trailing[2], b: trailing[3] })
    }
  }
  // Trailing ISO date: `macro brief 2026-09-14`.
  const dated = s.match(/^(.*?)\s+(\d{4}-\d{2}-\d{2})$/)
  if (dated && PHRASE_ZH[dated[1]] !== undefined) return `${PHRASE_ZH[dated[1]]} ${dated[2]}`
  // A value in the middle: `3 outputs in, rolling up`, `dispatch · macro`.
  for (const entry of TEMPLATES) {
    const hit = s.match(entry.re)
    if (!hit) continue
    const vars = {}
    entry.names.forEach((name, i) => {
      // A slot can hold one of our OWN phrases -- `{tail}` in `2 pods running,
      // {tail}` and `{noun}` in `today's {noun} delivered` are both table
      // entries -- so a captured value is run through again. A slot holding a
      // ticker, a path or a sentence someone wrote comes back unchanged, which
      // is the same pass-through rule one level down.
      vars[name] = phrase(hit[i + 1], depth + 1)
    })
    return fill(PHRASE_ZH[entry.key], vars)
  }
  return s
}

/**
 * The `group` field of a member row, in the reader's language.
 *
 * Its own field rather than a `phrase()` case, because as a pattern this would be
 * "anything at all" and would rewrite whatever a crew member happened to say.
 * Naming the FIELD keeps the transform where the shape is actually guaranteed.
 *
 * Both producers -- `_group_label` in `backend/org.py` and `crews/gen_members.py`
 * -- build `<book> · <pod>` and deliberately leave out any word for "pod", since
 * that word is the one part of the label that has to change with the reader. A
 * roster written before that rule ended the label with the noun itself, so an
 * English or legacy Chinese suffix is stripped first (matched by escape, so no
 * literal CJK sits in source) and a row never reads `x pod pod`.
 */
export function groupLabel(group) {
  const s = String(group || '').trim()
  if (!s) return ''
  const stripped = s.replace(/\s*(\u7ec4|pod)$/i, '').trim()
  if (!stripped) return s
  return `${stripped} ${t('pod_suffix')}`
}

/** Interpolate `{name}` placeholders, leaving an unknown one in place. */
function fill(template, vars) {
  return String(template).replace(/\{(\w+)\}/g, (m, name) => (vars[name] === undefined ? m : String(vars[name])))
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

    // migrated hardcoded strings (English is canonical; these are the Chinese reading)
    chat_empty_title: '该成员尚未开工',
    chat_empty_body: ({ name }) => `${name} 还没有会话，等它接到第一次任务后这里就能对话。`,
    thread_route_note: '这个 gateway 的 backend 还没有 POST /thread，开线程要等它上线',
    perm_await: ({ msg }) => `这一步在等批准：${msg}。批准要到主聊天窗口，这里没有审批按钮。`,
    queued_line: ({ msg }) => `排队中：${msg}`,
    sending: '发送中…',
    transcript_empty: '还没有消息，说第一句话就开始了。',
    reading_session: '正在读会话…',
    followup_prefix: ({ title }) => `接着「${title}」继续：`,
    followup_label: '下一件工作，说给它听：',
    dismiss: '收起',
    entry_dispatch: '派工',
    entry_report: '汇报',
    entry_steer: '插话',
    entry_done: '完成',
    send_failed_http: ({ status }) => `发送失败（HTTP ${status}）`,
    profile_tooltip: ({ who }) => `看 ${who} 的 profile`,
    unanchored_title: '没能挂到具体某句话的线程',
    work_in_progress: ({ n }) => `进行中的工作 ${n}`,
    sent_to: ({ who }) => `已送到 ${who}`,
    sent: '已送出',
    thread_finished: '这件工作已完成。',
    add_followup: '追加后续工作',
    view_profile: '查看 profile',
    reset_idle: '重置对话',
    reset_armed: '确认重置？',
    reset_busy: '重置中…',
    reset_missing_note: '后端未就绪',
    reset_missing_tip: '后端还没有提供重置接口',
    reset_tip: '换一个全新会话，旧会话保留',
    day_today: '今天',
    day_yesterday: '昨天',
    attach_tip: '附件要走主聊天窗口的 @file，这里没有',
    composer_more_tip: '/command、@file、模型选择和审批按钮属于主聊天窗口，这里没有',
    read_conv_http: ({ status }) => `读不到会话（HTTP ${status}）`,
    read_conv_err: ({ detail }) => `读不到会话（${detail}）`,
    thread_failed_http: ({ status }) => `开线程失败（HTTP ${status}）`,
    thread_missing_id: '开线程失败：返回里没有 thread id',
    reset_failed_http: ({ status }) => `重置失败（HTTP ${status}）`,
    reset_missing_slot: '重置失败：返回里没有 slot_key',
    render_crash: ({ slotKey }) => `这段对话画不出来了（已记录到控制台）。会话本身没事，可以在主聊天窗口里找 ${slotKey}`,
    crash_title: '这个页面崩了',
    crash_note: '下面是真实堆栈，已经写到 data/client-errors.jsonl。',
    run_replay: '回放',
    run_in_progress: ({ n }) => `${n} 进行中`,
    run_refreshing: '刷新中…',
    run_no_events: '今天还没有事件。',
    run_chain: '指挥链',
    run_pods: 'Pods',
    run_events: '事件流（最近）',
    run_pod_flow: '分析 → 多空 → 提案 → 风控 → 组报告',
    config_empty: '（空）',
    config_none: '没有配置数据。',
    config_header: '账户与行业组配置',
    config_readonly: '只读',
    config_display_only: '本期只做展示，改配置仍走 books.yaml / sectors.yaml。',
    config_save_disabled: '保存（未开放）',
    config_save_tip: '本期不开放保存',
    config_hint_books: '账户与可用额度',
    config_hint_sectors: '行业组与覆盖标的',
    config_hint_constraints: '账户约束',
    logs_no_artifacts: '这一天没有产物。',
    desk_tickers: '覆盖标的',

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

    // migrated hardcoded strings (English is canonical)
    chat_empty_title: 'This colleague has not started yet',
    chat_empty_body: ({ name }) => `${name} has no conversation yet; once it gets its first task you can talk here.`,
    thread_route_note: 'This gateway’s backend has no POST /thread yet — opening a thread waits on it.',
    perm_await: ({ msg }) => `This step is waiting on approval: ${msg}. Approve it in the main chat window; there are no approval buttons here.`,
    queued_line: ({ msg }) => `Queued: ${msg}`,
    sending: 'Sending…',
    transcript_empty: 'No messages yet — say the first word and it begins.',
    reading_session: 'Reading the conversation…',
    followup_prefix: ({ title }) => `Continuing from “${title}”: `,
    followup_label: 'Tell it the next piece of work:',
    dismiss: 'Dismiss',
    entry_dispatch: 'Dispatch',
    entry_report: 'Report',
    entry_steer: 'Steer',
    entry_done: 'Done',
    send_failed_http: ({ status }) => `Send failed (HTTP ${status})`,
    profile_tooltip: ({ who }) => `View ${who}’s profile`,
    unanchored_title: 'Threads that could not be pinned to a specific message',
    work_in_progress: ({ n }) => `${n} in progress`,
    sent_to: ({ who }) => `Sent to ${who}`,
    sent: 'Sent',
    thread_finished: 'This work is finished.',
    add_followup: 'Add follow-up work',
    view_profile: 'View profile',
    reset_idle: 'Restart conversation',
    reset_armed: 'Confirm restart?',
    reset_busy: 'Restarting…',
    reset_missing_note: 'Backend not ready',
    reset_missing_tip: 'The backend has no restart endpoint yet',
    reset_tip: 'Start a fresh session; the old one is kept',
    day_today: 'Today',
    day_yesterday: 'Yesterday',
    attach_tip: 'Attachments go through the main chat window’s @file — not here',
    composer_more_tip: '/command, @file, model choice and approval buttons belong to the main chat window, not here',
    read_conv_http: ({ status }) => `Could not read the conversation (HTTP ${status})`,
    read_conv_err: ({ detail }) => `Could not read the conversation (${detail})`,
    thread_failed_http: ({ status }) => `Could not open the thread (HTTP ${status})`,
    thread_missing_id: 'Could not open the thread: the response carried no thread id',
    reset_failed_http: ({ status }) => `Restart failed (HTTP ${status})`,
    reset_missing_slot: 'Restart failed: the response carried no slot_key',
    render_crash: ({ slotKey }) => `This conversation could not be drawn (logged to the console). The session itself is fine — find ${slotKey} in the main chat window.`,
    crash_title: 'This page crashed',
    crash_note: 'The real stack is below, and written to data/client-errors.jsonl.',
    run_replay: 'Replay',
    run_in_progress: ({ n }) => `${n} in progress`,
    run_refreshing: 'Refreshing…',
    run_no_events: 'No events today yet.',
    run_chain: 'Reports to you',
    run_pods: 'Pods',
    run_events: 'Run events (recent)',
    run_pod_flow: 'Analysis → Debate → Proposal → Risk → pod report',
    config_empty: '(empty)',
    config_none: 'No config data.',
    config_header: 'Accounts and sector-team configuration',
    config_readonly: 'Read-only',
    config_display_only: 'This release is display-only; config changes still go through books.yaml / sectors.yaml.',
    config_save_disabled: 'Save (not enabled)',
    config_save_tip: 'Saving is not enabled in this release',
    config_hint_books: 'Accounts and available capital',
    config_hint_sectors: 'Sector teams and their tickers',
    config_hint_constraints: 'Account constraints',
    logs_no_artifacts: 'Nothing was produced on this day.',
    desk_tickers: 'Tickers',

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

/**
 * The key set of one table, for the parity check in `tests/test_i18n.py`.
 *
 * Needed because `t()` deliberately falls back to English when a Chinese key is
 * missing -- the right behaviour on screen, and the reason a gap cannot be found
 * by calling `t()`: it returns real English, not the key name. So the tables get
 * compared to each other directly.
 */
export function tableKeys(code) {
  return Object.keys(TABLE[code] || {})
}

/** The languages the tables actually carry, for the same check. */
export function tableLangs() {
  return Object.keys(TABLE)
}
