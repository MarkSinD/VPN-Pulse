/* VPN Pulse — Mini App logic.
   Renders one view model (window.VPNPulseModel) that comes either from the API
   (window.VPNPulseApi, live or dev server) or from the inlined demo scenarios
   (prototype opened as a file, showcase). Strings: window.__I18N (RU/EN). No secrets. */
(function () {
  'use strict';
  const I18N = window.__I18N, FX = window.__FIXTURES, Model = window.VPNPulseModel;
  const q = new URLSearchParams(location.search);
  // telegram-web-app.js (vendored, loaded from the page's own origin) defines window.Telegram.WebApp
  // everywhere; only a non-empty initData means the page really runs inside Telegram
  const tg = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData ? window.Telegram.WebApp : null;
  // data source: the API when served next to it (/app/) or inside Telegram, demo scenarios otherwise
  const MODE = q.get('data') || ((tg && tg.initData) || location.pathname.indexOf('/app/') !== -1 ? 'api' : 'fixtures');

  // ---------- state ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem('vpnpulse.' + k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('vpnpulse.' + k, v); } catch (e) { /* private mode */ } }
  };
  const S = {
    scenario: q.get('scenario') || 'operational',
    role: q.get('role') || 'member',
    theme: q.get('theme') || 'auto',
    // the installation's default language (the served page carries it in <html lang>), then the visitor's own
    // choice from the switch in the header — never the phone's or Telegram's setting
    lang: q.get('lang') || store.get('lang', document.documentElement.lang === 'en' ? 'en' : 'ru'),
    tab: 'status', server: null,
    filter: 'all', range: '24h', open: 'checks',
    hintDismissed: store.get('hint', '') === '1',
    scrollPos: 0, originRow: null, eventsPage: 1, noteExpanded: false, eventsState: 'ok',
    text200: q.get('text') === '200',
    sessionRole: null, help: null
  };
  if (!I18N[S.lang]) S.lang = 'ru';
  const screenParam = q.get('screen');
  if (screenParam) { const m = screenParam.match(/^server:(\w+)$/); if (m) { S.tab = 'status'; S.server = m[1]; } else if (['status', 'events', 'keys', 'help', 'admin'].includes(screenParam)) S.tab = screenParam; }
  // the showcase bar belongs to the prototype opened as a file; next to the API (dev server, production,
  // Telegram) it stays hidden unless asked for with ?showcase=visible
  if (q.get('showcase') === 'hidden' || (MODE === 'api' && q.get('showcase') !== 'visible')) document.body.setAttribute('data-showcase', 'hidden');
  // the dev server accepts ?scenario= — only ever sent when a scenario was asked for or the showcase is visible
  const devScenarios = q.has('scenario') || document.body.getAttribute('data-showcase') !== 'hidden';
  const api = MODE === 'api' ? window.VPNPulseApi({ base: q.get('api') || '/api/v1', lang: () => S.lang, scenario: () => (devScenarios ? S.scenario : null) }) : null;

  // ---------- analytics (allowlisted, no identity) ----------
  // Every event stays on the page (showcase counter, QA). With the API it is also shaped per
  // contracts/analytics-events.schema.json and sent in batches once a session exists — after the
  // render or the interaction that caused it, never in its way. The queue is in-memory (≤ 200);
  // a rejected batch (400) is dropped; any other failure waits — next trigger or a growing back-off
  // (2 s, 4 s, … up to 60 s) — so an unreachable or restarting API never sees a tight loop; a lost
  // session (401/403) stops the flushes until the next refresh signs in again.
  const events = window.__vpnPulseEvents = [];
  const analytics = { queue: [], timer: null, session: uuid(), inflight: false, sent: 0, failures: 0 };
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const b = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(b); else for (let i = 0; i < 16; i++) b[i] = Math.random() * 256 | 0;
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, x => ('0' + x.toString(16)).slice(-2)).join('');
    return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
  }
  function track(name, props) {
    const e = { name, at: Date.now(), props: props || {} }; events.push(e);
    if (window.console && q.get('debug')) console.debug('analytics', e);
    const c = document.getElementById('sc-events'); if (c) c.textContent = String(events.length);
    if (!api) return;
    analytics.queue.push({ event_id: uuid(), name, occurred_at: new Date(e.at).toISOString(), schema_version: 1, session_id: analytics.session, surface: 'mini_app', properties: e.props });
    if (analytics.queue.length > 200) analytics.queue.splice(0, analytics.queue.length - 200);
    scheduleFlush(1500);
  }
  function scheduleFlush(delay) {
    if (!api) return;
    if (analytics.timer) clearTimeout(analytics.timer);
    analytics.timer = setTimeout(() => { analytics.timer = null; flushAnalytics(); }, delay);
  }
  async function flushAnalytics() {
    if (!api || !S.sessionRole || analytics.inflight || !analytics.queue.length) return;
    const batch = analytics.queue.slice(0, 50);
    analytics.inflight = true;
    let ok = false;
    try { await api.analytics(batch); analytics.queue.splice(0, batch.length); analytics.sent += batch.length; ok = true; }
    catch (e) {
      if (e && e.status === 400) { analytics.queue.splice(0, batch.length); ok = true; }   // the batch itself is wrong: drop it
      else if (e && (e.status === 401 || e.status === 403)) { S.sessionRole = null; }        // the session is gone: the next refresh signs in again
    }
    finally { analytics.inflight = false; }
    if (ok) analytics.failures = 0; else analytics.failures = Math.min(analytics.failures + 1, 6);
    if (!analytics.queue.length || !S.sessionRole) return;
    // drain a long queue right away after a success; after a failure wait 2 s, 4 s, … 60 s at most
    scheduleFlush(ok ? 0 : Math.min(60000, 1000 * Math.pow(2, analytics.failures)));
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushAnalytics(); });

  // ---------- i18n ----------
  function t(key, params) {
    let s = I18N[S.lang][key];
    if (s === undefined) { s = I18N.ru[key] !== undefined ? I18N.ru[key] : key; }
    if (params) Object.keys(params).forEach(k => { s = s.split('{' + k + '}').join(String(params[k])); });
    return s;
  }
  const L = o => (o && typeof o === 'object') ? (o[S.lang] || o.ru) : o;
  function dur(min) { if (min === null || min === undefined) return '—'; if (min < 1) return t('duration.now'); if (min < 60) return t('duration.min', { n: min }); if (min < 48 * 60) return t('duration.hour', { n: Math.round(min / 60) }); return t('duration.day', { n: Math.round(min / 1440) }); }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ico = (n, cls) => '<svg class="i ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + n + '"/></svg>';
  const fmtTime = Model.fmtTime;
  // calendar label for a Date in the viewer's time zone: today / yesterday / "9 сентября"
  function dayLabel(d) {
    if (!d) return '';
    const now = new Date(), today = new Date(now.getFullYear(), now.getMonth(), now.getDate()), that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((today - that) / 86400000);
    if (diff === 0) return t('events.today'); if (diff === 1) return t('events.yesterday');
    try { return new Intl.DateTimeFormat(S.lang === 'ru' ? 'ru-RU' : 'en-GB', { day: 'numeric', month: 'long' }).format(d); } catch (e) { return d.toISOString().slice(0, 10); }
  }

  // ---------- data ----------
  const ctx = () => ({ lang: S.lang, now: Date.now(), scenario: S.scenario });
  let SC = MODE === 'api' ? Model.loading() : Model.fromFixtures(FX, S.scenario, ctx());
  let lastGood = null, lastGoodAt = null, loadSeq = 0, refreshTimer = null;
  const kinds = () => ['pc', 'mobile', 'abroad'].filter(k => SC.presence[k] !== 'none');
  const byId = id => SC.list.find(s => s.id === id);
  function sname(s) {
    if (s && typeof s === 'object') return s.name;
    const found = byId(s); if (found) return found.name;
    const fx = FX && FX.servers.find(x => x.id === s); return fx ? L(fx.name) : (s || '—');
  }
  async function ensureSession() {
    if (S.sessionRole) return;
    if (tg && tg.initData) { await api.session(tg.initData); const me = await api.me(); S.role = me.role; }
    else {
      // no Telegram around us: the dev server hands out a session; production has no such route (404),
      // which means "open this from Telegram" rather than "the service is down"
      try { await api.devSession(S.role); }
      catch (e) { if (e && e.status === 404) { const denied = new Error('open from Telegram'); denied.status = 401; denied.code = 'TELEGRAM_REQUIRED'; throw denied; } throw e; }
    }
    S.sessionRole = S.role;
  }
  async function fetchBundle() {
    const status = await api.status();
    const details = {}, metrics = {}, adminDetails = {};
    await Promise.all(status.servers.map(async c => {
      const [d, m24, m7] = await Promise.all([api.server(c.id), api.metrics(c.id, '24h'), api.metrics(c.id, '7d')]);
      details[c.id] = d; metrics[c.id] = { '24h': m24, '7d': m7 };
      if (S.role === 'admin') adminDetails[c.id] = await api.adminServer(c.id);
    }));
    const [ev, help] = await Promise.all([api.events('all', 100), api.help()]);
    let admin = null;
    if (S.role === 'admin') {
      const [overview, probes, readiness] = await Promise.all([api.adminOverview(), api.adminProbes(), api.ready()]);
      admin = { overview, probes, readiness, details: adminDetails };
    }
    return { status, details, metrics, events: ev, help, admin };
  }
  async function load() {
    if (MODE !== 'api') { SC = Model.fromFixtures(FX, S.scenario, ctx()); render(); document.body.setAttribute('data-load', 'ready'); return; }
    const seq = ++loadSeq;
    document.body.setAttribute('data-load', 'loading');
    try {
      await ensureSession();
      let bundle;
      try { bundle = await fetchBundle(); }
      catch (e) { if (e && e.status === 401) { S.sessionRole = null; await ensureSession(); bundle = await fetchBundle(); } else throw e; }
      if (seq !== loadSeq) return;
      S.help = bundle.help;
      SC = Model.fromApi(bundle, ctx()); lastGood = SC; lastGoodAt = new Date();
      if (S.server && !byId(S.server)) S.server = null;
    } catch (e) {
      if (seq !== loadSeq) return;
      if (e && (e.status === 401 || e.status === 403)) SC = Model.authFailed(e.code);
      else { SC = Model.offline(lastGood, { lastGoodAt }); if (window.console && e && e.status !== 503) console.warn('vpnpulse: status unavailable', e); }
    }
    render();
    document.body.setAttribute('data-load', 'ready');
    scheduleFlush(0);
  }
  function scheduleRefresh() {
    if (MODE !== 'api' || refreshTimer) return;
    refreshTimer = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 60000);
  }

  // ---------- DOM ----------
  const $ = sel => document.querySelector(sel);
  const root = $('#app-scroll'), header = $('#app-header'), nav = $('#app-nav');
  let noteDraft = null;

  function applyTheme() {
    const html = document.documentElement;
    if (S.theme === 'auto') html.removeAttribute('data-theme'); else html.setAttribute('data-theme', S.theme);
    html.style.fontSize = S.text200 ? '200%' : '';
    document.documentElement.lang = S.lang;
    if (tg) { try { const bg = getComputedStyle(html).getPropertyValue('--color-bg').trim(); if (tg.setHeaderColor) tg.setHeaderColor(bg); if (tg.setBackgroundColor) tg.setBackgroundColor(bg); } catch (e) { /* older clients */ } }
  }

  // ---------- header / nav ----------
  function renderHeader() {
    const inServer = S.tab === 'status' && S.server;
    const s = inServer ? byId(S.server) : null;
    const titleHtml = inServer && s
      ? '<span class="t">' + esc(sname(s)) + '</span><span class="st">' + esc(t('status.state.' + s.state)) + '</span>'
      : '<span class="t">' + esc(t('app.title')) + '</span>' + (SC.demo ? '<span class="demo-mark">' + esc(t('app.demo')) + '</span>' : '');
    header.innerHTML =
      '<button type="button" class="icon-btn ' + (inServer ? '' : 'hidden') + '" id="back-btn" aria-label="' + esc(t('action.back')) + '" data-event="back">' + ico('back') + '</button>' +
      '<div class="ttl">' + titleHtml + '</div>' +
      '<button type="button" class="lang-btn" id="lang-btn" aria-label="' + esc(t('app.lang.switch', { language: S.lang === 'ru' ? 'English' : 'русский' })) + '" data-event="language_changed">' + esc(t('app.lang.other')) + '</button>';
    $('#back-btn').addEventListener('click', () => history.back());
    $('#lang-btn').addEventListener('click', () => { const from = S.lang; S.lang = S.lang === 'ru' ? 'en' : 'ru'; store.set('lang', S.lang); track('language_changed', { from, to: S.lang }); load(); });
    if (tg) { if (inServer) { tg.BackButton.show(); } else { tg.BackButton.hide(); } }
  }
  function renderNav() {
    const tabs = [['status', 'pulse'], ['events', 'clock'], ['keys', 'key'], ['help', 'help']];
    if (S.role === 'admin') tabs.push(['admin', 'shield']);
    nav.style.setProperty('--nav-count', tabs.length);
    nav.innerHTML = tabs.map(([id, ic]) => '<button type="button" data-tab="' + id + '" ' + (S.tab === id ? 'aria-current="page"' : '') + '>' + ico(ic) + '<span>' + esc(t('app.nav.' + id)) + '</span></button>').join('');
    nav.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { const id = b.getAttribute('data-tab'); if (S.tab === id && !S.server) { root.scrollTop = 0; return; } S.tab = id; S.server = null; history.replaceState({ tab: id }, ''); render(); root.scrollTop = 0; if (id === 'events') track('events_viewed', { filter: S.filter, result_bucket: SC.eventsList.length ? 'some' : 'empty' }); if (id === 'help') track('help_viewed', { entry_point: 'nav', overall_state: SC.overall }); }));
  }

  // ---------- components ----------
  // flags: inline SVG (30x20) for simple geometric flags keyed by ISO code; anything else shows the code.
  // Emoji flags are not used: Windows renders them as letters and colours differ between platforms.
  const H = (c, w) => { w = w || c.map(() => 1); const total = w.reduce((a, b) => a + b, 0); let y = 0; return c.map((col, i) => { const h = 20 * w[i] / total, r = '<rect x="0" y="' + y.toFixed(2) + '" width="30" height="' + (h + 0.2).toFixed(2) + '" fill="' + col + '"/>'; y += h; return r; }).join(''); };
  const V = c => c.map((col, i) => '<rect x="' + (30 * i / c.length).toFixed(2) + '" y="0" width="' + (30 / c.length + 0.2).toFixed(2) + '" height="20" fill="' + col + '"/>').join('');
  const N = (bg, cross, inner) => '<rect width="30" height="20" fill="' + bg + '"/><rect x="8" y="0" width="5" height="20" fill="' + cross + '"/><rect x="0" y="7.5" width="30" height="5" fill="' + cross + '"/>' + (inner ? '<rect x="9.5" y="0" width="2" height="20" fill="' + inner + '"/><rect x="0" y="9" width="30" height="2" fill="' + inner + '"/>' : '');
  const FLAGS = {
    lv: H(['#9e3039', '#ffffff', '#9e3039'], [2, 1, 2]), nl: H(['#ae1c28', '#ffffff', '#21468b']), fi: N('#ffffff', '#003580'),
    se: N('#006aa7', '#fecc00'), no: N('#ba0c2f', '#ffffff', '#00205b'), dk: N('#c8102e', '#ffffff'), is: N('#02529c', '#ffffff', '#dc1e35'),
    de: H(['#000000', '#dd0000', '#ffce00']), ee: H(['#0072ce', '#000000', '#ffffff']), lt: H(['#fdb913', '#006a44', '#c1272d']), at: H(['#ed2939', '#ffffff', '#ed2939']),
    hu: H(['#ce2939', '#ffffff', '#477050']), bg: H(['#ffffff', '#00966e', '#d62612']), pl: H(['#ffffff', '#dc143c']), ua: H(['#0057b7', '#ffd700']),
    fr: V(['#0055a4', '#ffffff', '#ef4135']), it: V(['#009246', '#ffffff', '#ce2b37']), ie: V(['#169b62', '#ffffff', '#ff883e']), be: V(['#000000', '#fae042', '#ed2939']), ro: V(['#002b7f', '#fcd116', '#ce1126']),
    ch: '<rect width="30" height="20" fill="#d52b1e"/><rect x="13" y="4" width="4" height="12" fill="#fff"/><rect x="9" y="8" width="12" height="4" fill="#fff"/>',
    jp: '<rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="6" fill="#bc002d"/>'
  };
  const flagSvg = cc => FLAGS[cc] ? '<svg viewBox="0 0 30 20" aria-hidden="true">' + FLAGS[cc] + '</svg>' : '';
  // gauge ring: a 300-degree scale open at the bottom, engraved ticks, the flag in the centre and the
  // country code in the gap. Arc length = availability over 24 h (dashed when unknown); colour = state;
  // the mark repeats the state for colour-blind users.
  const gauge = arc => '<svg class="r" viewBox="0 0 64 64"><path class="track" d="M18 56.25A28 28 0 1 1 46 56.25"/><path class="ticks" d="M21 51.05A22 22 0 1 1 43 51.05" pathLength="300"/><path class="arc" d="M18 56.25A28 28 0 1 1 46 56.25" pathLength="300"' + arc + '/></svg>';
  function ring(s, cls) {
    const cc = (s.cc || '').toLowerCase();
    const face = flagSvg(cc) || (cc ? '<span class="cc-txt">' + esc(cc.toUpperCase()) + '</span>' : '<span class="emoji">' + (s.flag || '') + '</span>');
    const mark = s.state === 'unavailable' ? '<span class="mark">' + ico('x') + '</span>' : s.state === 'degraded' ? '<span class="mark">' + ico('alert') + '</span>' : '';
    const up = parseFloat(String(s.uptime24 || '').replace(',', '.'));
    const arc = s.state === 'unknown' || isNaN(up) ? '' : ' style="stroke-dasharray:' + Math.max(6, Math.min(300, up * 3)).toFixed(1) + ' 300"';
    return '<span class="ring r-' + s.state + ' ' + (cls || '') + '" aria-hidden="true">' + gauge(arc) + '<span class="flag">' + face + '</span>' + (cc ? '<span class="cc">' + esc(cc.toUpperCase()) + '</span>' : '') + mark + '</span>';
  }
  const sevIcon = { high: 'x', medium: 'alert', low: 'info' };
  // summary gauge for the status headline: arc = share of servers that work, colour = overall state,
  // glyph repeats the state (check / alert / x / clock = no fresh data). No flag, no country code.
  const stateGlyph = { operational: 'check', degraded: 'alert', unavailable: 'x', unknown: 'clock' };
  function summaryGauge(state, fraction) {
    const arc = state === 'unknown' || fraction === null ? '' : ' style="stroke-dasharray:' + Math.max(6, Math.min(300, fraction * 300)).toFixed(1) + ' 300"';
    return '<span class="ring xs r-' + state + '" aria-hidden="true">' + gauge(arc) + '<span class="glyph">' + ico(stateGlyph[state] || 'clock') + '</span></span>';
  }
  const srcIcon = { pc: 'pc', mobile: 'signal', abroad: 'globe' };
  function sources(s, withLabels) {
    return '<span class="srcs">' + kinds().map(k => { const r = s.sources[k].r; return '<span class="src s-' + r + '"><span class="sr-only">' + esc(t('source.' + k)) + ': ' + esc(t('source.result.' + r)) + '</span>' + ico(srcIcon[k]) + '<span class="d" aria-hidden="true"></span>' + (withLabels ? '<span class="lbl">' + esc(t('source.' + k)) + '</span>' : '') + '</span>'; }).join('') + '</span>';
  }
  function segsHtml(segs, extra) { return '<span class="segs ' + (extra || '') + '" aria-hidden="true"' + (segs.length !== 48 ? ' style="grid-template-columns:repeat(' + segs.length + ',1fr)"' : '') + '>' + segs.map(x => '<i class="' + x + '"></i>').join('') + '</span>'; }
  function chart(s, big) {
    const week = big && S.range === '7d' && s.series7;
    const series = week ? s.series7 : s.series, segs = week ? s.segs7 : s.segs;
    return '<span class="' + (big ? 'bigchart' : 'chart') + '" role="img" aria-label="' + esc(t('server.chartSummary', { range: t(S.range === '7d' ? 'server.range7d' : 'server.range24') })) + '"><canvas data-series="' + series.map(v => v === null ? '' : v).join(',') + '" data-state="' + s.state + '"></canvas>' + segsHtml(segs) + '</span>';
  }
  function drawCharts() {
    const cs = getComputedStyle(document.documentElement);
    const col = { operational: cs.getPropertyValue('--color-operational').trim(), degraded: cs.getPropertyValue('--color-degraded').trim(), unavailable: cs.getPropertyValue('--color-unavailable').trim(), unknown: cs.getPropertyValue('--color-unknown').trim() };
    root.querySelectorAll('canvas[data-series]').forEach(c => {
      const w = c.clientWidth, h = c.clientHeight; if (!w || !h) return;
      const dpr = window.devicePixelRatio || 1; c.width = w * dpr; c.height = h * dpr;
      const ctx2 = c.getContext('2d'); ctx2.scale(dpr, dpr);
      const raw = c.getAttribute('data-series').split(','), series = raw.map(v => v === '' ? null : Number(v));
      if (series.length < 2) return;
      const color = col[c.getAttribute('data-state')] || col.operational, bottom = h - 9, pad = 1;
      const max = Math.max(1, ...series.filter(v => v !== null));
      const x = i => pad + i * (w - pad * 2) / (series.length - 1), y = v => bottom - (v / max) * (bottom - 3);
      ctx2.lineWidth = 1.5; ctx2.strokeStyle = color; ctx2.fillStyle = color; ctx2.lineJoin = 'round';
      let run = [];
      const flush = () => { if (run.length < 2) { run = []; return; } ctx2.beginPath(); run.forEach((p, i) => i ? ctx2.lineTo(p[0], p[1]) : ctx2.moveTo(p[0], p[1])); ctx2.lineTo(run[run.length - 1][0], bottom); ctx2.lineTo(run[0][0], bottom); ctx2.closePath(); ctx2.globalAlpha = .10; ctx2.fill(); ctx2.globalAlpha = 1; ctx2.beginPath(); run.forEach((p, i) => i ? ctx2.lineTo(p[0], p[1]) : ctx2.moveTo(p[0], p[1])); ctx2.stroke(); run = []; };
      series.forEach((v, i) => { if (v === null) flush(); else run.push([x(i), y(v)]); }); flush();
      const last = series[series.length - 1]; if (last !== null) { ctx2.beginPath(); ctx2.arc(x(series.length - 1), y(last), 2.5, 0, Math.PI * 2); ctx2.fill(); }
    });
  }
  function toast(msg) { const el = $('#toast'); el.textContent = msg; el.classList.add('show'); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove('show'), 2200); }
  function copy(text) { try { navigator.clipboard && navigator.clipboard.writeText(text); } catch (e) { /* mock */ } toast(t('action.copied')); }
  function copyRow(cmd) { return '<div class="copy-row"><code>' + esc(cmd) + '</code><button type="button" class="btn btn-ghost" data-copy="' + esc(cmd) + '">' + ico('copy') + esc(t('action.copy')) + '</button></div>'; }
  function bindCopy() { root.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => copy(b.getAttribute('data-copy')))); }
  // API-backed actions fall back to a demo toast when there is no API (prototype opened as a file)
  function apiAction(run, fallbackKey) {
    if (!api) { toast(t(fallbackKey || 'admin.demoAction')); return Promise.resolve(false); }
    return run().then(() => true).catch(e => { toast(t('error.generic', { code: (e && e.code) || 'HTTP_ERROR' })); return false; });
  }

  // ---------- status ----------
  function overallBlock() {
    const rec = SC.recommended ? byId(SC.recommended) : null;
    // freshness as a chip: short duration visible, full sentence for screen readers; amber once stale (> 3 min)
    const fresh = SC.freshnessMin === null || SC.freshnessMin === undefined ? '' : '<span class="chip chip-fresh' + (SC.freshnessMin > 3 ? ' stale' : '') + '"><span aria-hidden="true">' + ico('clock') + '<span class="num">' + esc(dur(SC.freshnessMin)) + '</span></span><span class="sr-only">' + esc(t('status.updatedAgo', { duration: dur(SC.freshnessMin) })) + '</span></span>';
    // the recommendation lives on the server row (chip); here only the absence of one is worth a line
    const recHtml = !SC.empty && !rec && SC.list.length ? '<p class="small muted">' + esc(t('status.noRecommendation')) + '</p>' : '';
    const title = SC.empty ? t('status.settingUp') : t('status.' + SC.overall);
    const okShare = SC.list.length ? SC.list.filter(x => x.state === 'operational').length / SC.list.length : null;
    const lamp = SC.empty || !SC.overall ? '' : summaryGauge(SC.overall, okShare);
    return '<div class="overall"><div class="ov-row"><h1 class="title" id="screen-title" tabindex="-1">' + lamp + esc(title) + '</h1>' + fresh + '</div>' + recHtml + '</div>';
  }
  function noteBlock() {
    if (!SC.note) return '';
    const txt = SC.note.text, long = txt.length > 140;
    return '<section class="note-box" aria-label="' + esc(t('events.note')) + '"><div class="txt ' + (long && !S.noteExpanded ? 'clamp' : '') + '" id="note-txt">' + esc(txt) + '</div><div class="who">' + esc(t('status.noteFrom', { time: fmtTime(SC.note.at) })) + '</div>' + (long ? '<button type="button" class="btn btn-text" id="note-more" aria-expanded="' + S.noteExpanded + '" aria-controls="note-txt">' + esc(t(S.noteExpanded ? 'action.less' : 'action.more')) + '</button>' : '') + '</section>';
  }
  function serverRow(s) {
    const unk = s.state === 'unknown';
    const label = unk ? t('status.rowLabelUnknown', { server: sname(s) }) : t('status.rowLabel', { server: sname(s), state: t('status.state.' + s.state), uptime: s.uptime24 });
    const side = unk || s.uptime24 === '—'
      ? '<span class="up num muted">—</span><span class="cap">' + esc(t('status.currentUnknown')) + '</span>'
      : '<span class="up num">' + esc(s.uptime24) + '</span><span class="cap">' + esc(t('status.history24h')) + '</span>';
    return '<button type="button" class="srow" data-server="' + s.id + '" data-event="server_row_pressed" aria-label="' + esc(label) + '">' + ring(s) +
      '<span class="main"><span class="name"><span class="t">' + esc(sname(s)) + '</span>' + (SC.recommended === s.id ? '<span class="chip chip-rec">' + ico('star') + esc(t('status.recommended')) + '</span>' : '') + '</span>' +
      '<span class="stl"><b>' + esc(t('status.state.' + s.state)) + '</b><span>· ' + esc(s.country) + '</span></span>' + sources(s, true) + chart(s, false) + '</span>' +
      '<span class="side">' + side + ico('chevron', 'chev') + '</span></button>';
  }
  function statusScreen() {
    if (SC.loading) return skeleton();
    if (SC.api === 'auth') return errorScreen('auth');
    const parts = [];
    if (SC.api === 'offline') parts.push('<div class="banner banner-warn" role="status">' + ico('offline') + '<div><b>' + esc(t('status.offline')) + '</b><br>' + esc(t('status.offlineBody', { time: SC.lastKnownTime })) + '</div><div class="act"><button type="button" class="btn btn-ghost" data-retry="status" data-event="retry_pressed">' + ico('refresh') + esc(t('action.retry')) + '</button></div></div>');
    parts.push(overallBlock());
    if (SC.coverageMissing && S.role === 'admin') parts.push('<div class="banner banner-warn">' + ico('alert') + '<div>' + esc(t('status.coveragePartial', { missing: SC.coverageMissing.map(k => t('status.coverage.' + k)).join(', ') })) + '</div></div>');
    parts.push(noteBlock());
    if (SC.empty) {
      parts.push('<div class="empty">' + ico('pulse') + '<p>' + esc(t('status.settingUpBody')) + '</p></div>');
      if (S.role === 'admin' && SC.adminData) parts.push('<section class="admin-block"><span class="admin-tag">' + esc(t('app.nav.admin')) + '</span><h2 class="sub">' + esc(t('admin.serverAdd')) + '</h2><p class="small muted">' + esc(t('admin.serverAddBody')) + '</p>' + copyRow(SC.adminData.nextCommand || 'vpn-pulse server add') + '<a class="btn btn-text" href="#quick-start" data-event="quick_start_opened" style="justify-self:start">' + ico('ext') + esc(t('action.quickStart')) + '</a></section>');
      return '<div class="screen">' + parts.join('') + '</div>';
    }
    if (!S.hintDismissed) parts.push('<div class="hint" id="hint"><span>' + esc(t('status.hint')) + '</span><button type="button" class="btn btn-text" id="hint-ok">' + esc(t('status.hintDismiss')) + '</button></div>');
    const ks = kinds();
    if (ks.length) parts.push('<div class="legend" role="list" aria-label="' + esc(t('status.legend')) + '">' + ks.map(k => { const on = SC.presence[k] === 'active'; return '<span role="listitem"><span class="src ' + (on ? 's-ok' : 's-unknown') + '">' + ico(srcIcon[k]) + '<span class="d" aria-hidden="true"></span></span><span class="lg-t">' + esc(t('source.' + k)) + '</span><span class="sr-only">' + esc(t(on ? 'status.sourceOn' : 'status.sourceOff')) + '</span></span>'; }).join('') + '</div>');
    parts.push('<div class="servers" id="servers">' + SC.list.map(serverRow).join('') + '</div>');
    parts.push('<div class="axis" aria-hidden="true"><span></span><div><span>' + esc(t('status.axisStart')) + '</span><span>' + esc(t('status.axisEnd')) + '</span></div><span class="spacer"></span></div>');
    const side = window.innerWidth >= 1024 ? '<aside class="ctx">' + (SC.eventsList.length ? '<div class="panel"><h3>' + esc(t('events.title')) + '</h3>' + eventRow(SC.eventsList[0]) + '</div>' : '') + '<div class="panel"><h3>' + esc(t('status.legend')) + '</h3><div class="stack small muted">' + kinds().map(k => '<span>' + ico(srcIcon[k]) + ' ' + esc(t('source.' + k + '.full')) + '</span>').join('') + '</div></div></aside>' : '';
    return '<div class="status-layout"><div class="screen">' + parts.join('') + '</div>' + side + '</div>';
  }
  function skeleton() {
    const row = '<div class="srow" aria-hidden="true"><span class="sk" style="width:64px;height:64px;border-radius:50%"></span><span class="main"><span class="sk" style="height:20px;width:40%"></span><span class="sk" style="height:14px;width:60%"></span><span class="sk" style="height:30px;width:100%"></span></span><span class="sk" style="width:48px;height:20px"></span></div>';
    return '<div class="screen skeleton" aria-busy="true" aria-live="polite"><div class="overall"><div class="ov-row"><span class="sk" style="height:29px;width:56%"></span><span class="sk" style="height:28px;width:72px;border-radius:999px"></span></div></div><p class="sr-only">' + esc(t('app.loading')) + '</p><div class="servers">' + row + row + row + '</div></div>';
  }
  function errorScreen(kind) {
    const code = SC.code || 'MEMBERSHIP_REQUIRED';
    track('ui_error_shown', { surface: 'status', error_code: code, recoverable: kind !== 'auth' });
    return '<div class="error-screen" role="alert">' + ico('lock') + '<h1 class="title" id="screen-title" tabindex="-1">' + esc(t('error.auth')) + '</h1><p>' + esc(t('error.authBody', { code })) + '</p></div>';
  }
  function bindStatus() {
    root.querySelectorAll('.srow[data-server]').forEach(b => b.addEventListener('click', e => openServer(b.getAttribute('data-server'), e.detail === 0 ? 'keyboard' : 'pointer', b)));
    const hk = $('#hint-ok'); if (hk) hk.addEventListener('click', () => { S.hintDismissed = true; store.set('hint', '1'); $('#hint').remove(); });
    const nm = $('#note-more'); if (nm) nm.addEventListener('click', () => { S.noteExpanded = !S.noteExpanded; render(); });
    root.querySelectorAll('[data-retry]').forEach(b => b.addEventListener('click', () => {
      track('retry_pressed', { surface: b.getAttribute('data-retry'), error_code: 'STATUS_UNAVAILABLE' });
      b.classList.add('loading');
      if (api) load(); else setTimeout(() => { b.classList.remove('loading'); toast(t('error.offline')); }, 700);
    }));
    root.querySelectorAll('[data-event="quick_start_opened"]').forEach(a => a.addEventListener('click', () => track('quick_start_opened', { entry_point: 'status' })));
    bindCopy();
  }

  // ---------- server ----------
  function openServer(id, input) {
    const s = byId(id); if (!s) return;
    S.scrollPos = root.scrollTop; S.originRow = id; S.open = 'checks';
    if (!S.hintDismissed) { S.hintDismissed = true; store.set('hint', '1'); }
    track('server_row_pressed', { server_public_id: id, state: s.state, recommended: SC.recommended === id, input });
    history.pushState({ tab: 'status', server: id }, '');
    S.server = id; render(); root.scrollTop = 0;
    const h = $('#screen-title'); if (h) h.focus({ preventScroll: true });
    track('server_detail_viewed', { server_public_id: id, state: s.state, load_ms: 0 });
  }
  function acc(id, icon, title, mini, body) {
    const open = S.open === id;
    return '<section class="acc"><button type="button" class="acc-btn" id="acc-' + id + '" aria-expanded="' + open + '" aria-controls="panel-' + id + '" data-acc="' + id + '" data-event="detail_group_toggled">' + ico(icon, 'lead') + '<span>' + esc(title) + '</span><span class="mini">' + esc(mini || '') + '</span>' + ico('chevron-down', 'chev') + '</button><div class="acc-panel" id="panel-' + id + '" role="region" aria-labelledby="acc-' + id + '" ' + (open ? '' : 'hidden') + '>' + body + '</div></section>';
  }
  function srcRow(s, k) {
    const src = s.sources[k], r = src.r, cls = { ok: 'ok', fail: 'bad', partial: 'warn', unknown: 'unk' }[r];
    const via = k === 'abroad' && s.abroadFrom ? t('source.detail.viaServer', { server: sname(s.abroadFrom) }) + ' · ' : '';
    const detail = via + t(src.detailKey) + (src.age === null || src.age === undefined ? '' : ' · ' + t('source.ago', { duration: dur(src.age) }));
    return '<div><span class="k">' + ico(srcIcon[k]) + ' ' + esc(t('source.' + k)) + '<small>' + esc(t('source.' + k + '.full')) + '</small><small>' + esc(detail) + '</small></span><span class="v ' + cls + '">' + { ok: ico('check'), fail: ico('x'), partial: ico('alert'), unknown: '—' }[r] + esc(t('source.result.' + r)) + '</span></div>';
  }
  const num = v => (v === null || v === undefined ? '—' : v);
  function serverScreen(id) {
    const s = byId(id); if (!s) { if (SC.loading) return skeleton(); S.server = null; return statusScreen(); }
    const by = t(s.state === 'unavailable' ? 'server.failedBy' : 'server.confirmedBy', { by: t('server.by.' + s.confirmedBy) });
    const stale = s.staleMin ? '<div class="banner banner-info">' + ico('clock') + '<div>' + esc(t('server.stale', { duration: dur(s.staleMin) })) + '</div></div>' : '';
    const conflict = s.conflict ? '<div class="banner banner-warn">' + ico('alert') + '<div>' + esc(t('server.conflict', { a: t(s.conflict.a), b: t(s.conflict.b) })) + '</div></div>' : '';
    const diag = s.diag && S.role === 'admin' ? '<div class="diag"><b>' + esc(t('admin.diag.blocked')) + '</b><span>' + esc(t('admin.diag.action')) + '</span></div>' : '';
    const ks = kinds();
    const checks = (ks.length ? '<div class="kv">' + ks.map(k => srcRow(s, k)).join('') + '</div>' : '<p class="small muted">' + esc(t('server.checksNone')) + '</p>') + '<p class="small muted">' + esc(by) + '</p>';
    const ld = s.load, xr = s.protocols.includes('xray');
    const load = '<div class="metrics"><div class="metric"><div class="k">' + esc(t('server.connections')) + '</div><div class="v num">' + (xr && !ld.xrayKnown ? ld.awg + '+' : ld.awg + (ld.xray || 0)) + '</div><div class="s">' + esc(t('server.awg')) + ' ' + ld.awg + (xr ? ' · ' + esc(t('server.xray')) + ' ' + (ld.xrayKnown ? ld.xray : '—') : '') + '</div></div>' +
      '<div class="metric"><div class="k">' + esc(t('server.traffic')) + '</div><div class="v num">' + num(ld.mbit) + '<small>' + esc(t('server.mbit')) + '</small></div><div class="s">' + esc(t('server.peak', { n: num(ld.peak) })) + '</div></div>' +
      '<div class="metric"><div class="k">' + esc(t('server.cpu')) + '</div><div class="v num">' + num(ld.cpu) + '<small>%</small></div></div>' +
      '<div class="metric"><div class="k">' + esc(t('server.memory')) + '</div><div class="v num">' + num(ld.ram) + '<small>%</small></div><div class="s">' + esc(t('server.swap')) + ' ' + num(ld.swap) + '%</div></div></div>' +
      (xr && !ld.xrayKnown ? '<p class="small muted">' + esc(t('server.xrayUnknown')) + '</p>' : '') +
      '<div class="seg-ctl" role="group"><button type="button" data-range="24h" aria-pressed="' + (S.range === '24h') + '">' + esc(t('server.range24')) + '</button><button type="button" data-range="7d" aria-pressed="' + (S.range === '7d') + '">' + esc(t('server.range7d')) + '</button></div>' +
      chart(s, true) + '<div class="axis2"><span>' + esc(S.range === '7d' ? '−7 d'.replace('d', S.lang === 'ru' ? 'дн' : 'd') : t('status.axisStart')) + '</span><span>' + esc(t('status.axisEnd')) + '</span></div>' +
      '<div class="kv"><div><span class="k">' + esc(t('server.uptime24')) + '</span><span class="v">' + esc(s.uptime24) + '</span></div><div><span class="k">' + esc(t('server.uptime7')) + '</span><span class="v">' + esc(s.uptime7) + '</span></div><div><span class="k">' + esc(t('server.lastConn')) + '</span><span class="v">' + esc(dur(ld.lastConnMin)) + '</span></div></div>';
    const soft = s.software.length ? '<div class="kv">' + s.software.map(w => '<div><span class="k">' + esc(w.name) + '<small>' + esc(w.noteKey ? t(w.noteKey) : (w.note || '')) + '</small></span><span></span></div>').join('') + '</div>' : '<p class="small muted">—</p>';
    const keys = '<div class="metrics" style="grid-template-columns:repeat(3,1fr)"><div class="metric"><div class="k">' + esc(t('server.keysIssued')) + '</div><div class="v num">' + num(s.keys.issued) + '</div></div><div class="metric"><div class="k">' + esc(t('server.keysEver')) + '</div><div class="v num">' + num(s.keys.ever) + '</div></div><div class="metric"><div class="k">' + esc(t('server.keysActive')) + '</div><div class="v num">' + num(s.keys.active) + '</div></div></div>';
    const yes = '<span class="v ok">' + ico('check') + esc(t('server.yes')) + '</span>';
    const sys = '<div class="kv"><div><span class="k">' + esc(t('server.sshOk')) + '</span>' + yes + '</div><div><span class="k">' + esc(t(s.system.engine === 'module' ? 'server.moduleOk' : 'server.containerOk')) + '</span>' + yes + '</div><div><span class="k">' + esc(t('server.portOk')) + '</span>' + yes + '</div>' + (s.system.dns ? '<div><span class="k">' + esc(t('server.dnsOk')) + '</span>' + yes + '</div><div><span class="k">' + esc(t('server.ddnsOk')) + '</span>' + yes + '</div>' : '') + '</div>';
    const evs = SC.eventsList.filter(e => e.server === s.id);
    const evHtml = evs.length ? '<div>' + evs.slice(0, 5).map(eventRow).join('') + '</div>' : '<p class="small muted">' + esc(t('events.empty')) + '</p>';
    let adminHtml = '';
    if (S.role === 'admin' && SC.adminData) {
      const att = SC.adminData.attention.filter(a => a.server === s.id);
      adminHtml = acc('admin', 'shield', t('server.admin'), att.length ? String(att.length) : '', '<div class="admin-block">' + (att.length ? '<div class="attn">' + att.map(a => '<div><span class="lp ' + a.sev + '" aria-hidden="true">' + ico(sevIcon[a.sev]) + '</span><span>' + esc(a.text) + '<div class="sev">' + esc(t('admin.severity.' + a.sev)) + '</div></span></div>').join('') + '</div>' : '<p class="small muted">' + esc(t('admin.noAttention')) + '</p>') + '</div>');
    }
    return '<div class="screen">' +
      '<div class="detail-top">' + ring(s, 'sm') + '<div class="h"><h1 id="screen-title" tabindex="-1">' + esc(sname(s)) + (SC.recommended === s.id ? '<span class="chip chip-rec">' + ico('star') + esc(t('status.recommended')) + '</span>' : '') + '</h1><div class="st"><b>' + esc(t('status.state.' + s.state)) + '</b><span>· ' + esc(s.country) + '</span><span>· ' + esc(s.protocols.map(p => p === 'awg' ? t('server.awg') : t('server.xray')).join(' + ')) + '</span>' + (SC.freshnessMin !== null && SC.freshnessMin !== undefined ? '<span>· ' + esc(t('status.updatedAgo', { duration: dur(SC.freshnessMin) })) + '</span>' : '') + '</div></div></div>' +
      stale + conflict + diag +
      '<div class="detail-cols"><div>' + acc('checks', 'search', t('server.checks'), '', checks) + acc('load', 'chart', t('server.load'), (xr && !ld.xrayKnown ? ld.awg + '+' : String(ld.awg + (ld.xray || 0))), load) + '</div><div>' + acc('software', 'layers', t('server.software'), String(s.protocols.length), soft) + acc('keys', 'key', t('server.keys'), String(num(s.keys.active)), keys) + acc('system', 'server', t('server.system'), s.state === 'unknown' ? '—' : s.uptime7, sys) + acc('events', 'clock', t('server.events'), String(evs.length), evHtml) + adminHtml + '</div></div></div>';
  }
  function bindServer() {
    root.querySelectorAll('.acc-btn').forEach(b => b.addEventListener('click', () => toggleAcc(b)));
    root.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => { S.range = b.getAttribute('data-range'); render(); const nb = root.querySelector('[data-range="' + S.range + '"]'); if (nb) nb.focus({ preventScroll: true }); }));
  }
  function toggleAcc(btn) {
    const id = btn.getAttribute('data-acc'), wasOpen = S.open === id;
    const topBefore = btn.getBoundingClientRect().top;
    S.open = wasOpen ? null : id;
    root.querySelectorAll('.acc-btn').forEach(b => { const on = b.getAttribute('data-acc') === S.open; b.setAttribute('aria-expanded', String(on)); const p = document.getElementById('panel-' + b.getAttribute('data-acc')); if (p) p.hidden = !on; });
    drawCharts();
    btn.focus({ preventScroll: true });
    // keep the pressed header where it was: a group above may have collapsed
    const shift = btn.getBoundingClientRect().top - topBefore;
    if (shift) root.scrollTop = Math.max(0, root.scrollTop + shift);
    const r = btn.getBoundingClientRect(), sr = root.getBoundingClientRect();
    if (r.top < sr.top || r.bottom > sr.bottom) btn.scrollIntoView({ block: 'nearest' });
    track('detail_group_toggled', { group: id, expanded: !wasOpen, input: 'pointer' });
  }

  // ---------- events ----------
  function eventText(e) {
    if (e.kind === 'note') return '<b>' + esc(t('events.note')) + '</b> · ' + esc(e.text || '');
    if (e.kind === 'probeSilent') return esc(t('events.probeSilent', { source: t('source.' + e.source) }));
    const p = { server: ' ', state: e.state ? t('status.state.' + e.state) : '', source: e.source ? t('source.' + e.source) : '' };
    return esc(t('events.' + e.kind, p)).replace(' ', '<b>' + esc(sname(e.server)) + '</b>');
  }
  function eventRow(e) { const ic = { ok: 'check', problem: 'x', note: 'note', info: 'info' }[e.sev] || 'info'; return '<div class="ev"><span class="ic ' + e.sev + '" aria-hidden="true">' + ico(ic) + '</span><span class="t">' + eventText(e) + '</span><time>' + esc(fmtTime(e.at)) + '</time></div>'; }
  function eventsScreen() {
    if (SC.api === 'auth') return errorScreen('auth');
    const filters = ['all', 'problems', 'notes'];
    const ctl = '<div class="seg-ctl" role="group" aria-label="' + esc(t('events.title')) + '">' + filters.map(f => '<button type="button" data-filter="' + f + '" aria-pressed="' + (S.filter === f) + '" data-event="events_filter_changed">' + esc(t('events.filter.' + f)) + '</button>').join('') + '</div>';
    let body;
    if (S.eventsState === 'loading' || SC.loading) body = '<p class="small muted" aria-live="polite">' + esc(t('events.loading')) + '</p>';
    else if (S.eventsState === 'error' || SC.api === 'offline') body = '<div class="banner banner-bad" role="alert">' + ico('alert') + '<div>' + esc(t('events.error')) + '<br><span class="xs">STATUS_UNAVAILABLE</span></div><div class="act"><button type="button" class="btn btn-ghost" id="ev-retry" data-event="retry_pressed">' + ico('refresh') + esc(t('action.retry')) + '</button></div></div>';
    else {
      const list = SC.eventsList.filter(e => S.filter === 'all' || (S.filter === 'problems' && e.sev === 'problem') || (S.filter === 'notes' && e.sev === 'note'));
      if (!list.length) body = '<div class="empty">' + ico('clock') + '<h2 class="sub">' + esc(t('events.empty')) + '</h2><p>' + esc(t('events.emptyBody', { date: dayLabel(SC.since) })) + '</p></div>';
      else {
        const page = list.slice(0, S.eventsPage * 6); let day = null, h = '';
        page.forEach(e => { const dl = dayLabel(e.at); if (dl !== day) { day = dl; h += '<div class="evday">' + esc(dl) + '</div>'; } h += eventRow(e); });
        if (list.length > page.length) h += '<button type="button" class="btn btn-ghost btn-block" id="ev-more" style="margin-top:12px">' + esc(t('events.more')) + '</button>';
        body = '<div>' + h + '</div>';
      }
    }
    return '<div class="screen"><h1 class="title" id="screen-title" tabindex="-1">' + esc(t('events.title')) + '</h1>' + ctl + body + '</div>';
  }
  function bindEvents() {
    root.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { const from = S.filter; S.filter = b.getAttribute('data-filter'); S.eventsPage = 1; track('events_filter_changed', { from, to: S.filter }); render(); const nb = root.querySelector('[data-filter="' + S.filter + '"]'); if (nb) nb.focus({ preventScroll: true }); }));
    const more = $('#ev-more'); if (more) more.addEventListener('click', () => { S.eventsPage++; render(); });
    const rt = $('#ev-retry'); if (rt) rt.addEventListener('click', () => {
      track('retry_pressed', { surface: 'events', error_code: 'STATUS_UNAVAILABLE' });
      if (api) { load(); return; }
      S.eventsState = 'loading'; render(); setTimeout(() => { S.eventsState = SC.api === 'offline' ? 'error' : 'ok'; render(); }, 700);
    });
  }

  // ---------- keys / help ----------
  function contactAvailable() { return !S.help || S.help.contact_available !== false; }
  function keysScreen() {
    return '<div class="screen"><h1 class="title" id="screen-title" tabindex="-1">' + esc(t('keys.title')) + '</h1><div class="stack"><p><b>' + esc(t('keys.mvp')) + '</b></p><p class="muted small">' + esc(t('keys.body')) + '</p></div>' + (contactAvailable() ? '<button type="button" class="btn btn-primary" data-contact="keys" data-event="contact_admin_pressed">' + ico('send') + esc(t('help.contact')) + '</button>' : '') + '<div class="divider"></div><div class="stack"><h2 class="sub">' + esc(t('keys.reserveTitle')) + '</h2><p>' + esc(t('keys.reserve')) + '</p><p class="muted small">' + esc(t('keys.reserveBody')) + '</p></div></div>';
  }
  function helpScreen() {
    const steps = [1, 2, 3, 4].map(n => '<div class="step"><button type="button" class="step-btn" aria-expanded="' + (S.open === 'h' + n) + '" aria-controls="hs-' + n + '" data-step="' + n + '" data-event="help_step_opened"><span class="n">' + n + '</span><span>' + esc(t('help.step' + n + '.title')) + '</span>' + ico('chevron-down', 'chev') + '</button><div class="step-body" id="hs-' + n + '" ' + (S.open === 'h' + n ? '' : 'hidden') + '>' + esc(t('help.step' + n + '.body')) + '</div></div>').join('');
    const why = SC.overall === 'unavailable' ? t('help.whyIncident') : SC.overall === 'unknown' ? t('help.whyUnknown') : t('help.whyOk');
    return '<div class="screen"><h1 class="title" id="screen-title" tabindex="-1">' + esc(t('help.title')) + '</h1><div class="small"><span class="muted">' + esc(t('help.current')) + ':</span> <span class="c-' + SC.overall + '"><span class="state-dot"></span></span> <b>' + esc(t('status.' + SC.overall)) + '</b></div><div>' + steps + '</div>' + (contactAvailable() ? '<button type="button" class="btn btn-primary btn-block" data-contact="help" data-event="contact_admin_pressed">' + ico('send') + esc(t('help.contact')) + '</button>' : '') + '<details class="why"><summary>' + ico('help') + esc(t('help.why')) + '</summary><p>' + esc(why) + '</p></details></div>';
  }
  function bindHelp() {
    root.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => { const id = 'h' + b.getAttribute('data-step'); const was = S.open === id; S.open = was ? null : id; root.querySelectorAll('.step-btn').forEach(x => { const on = 'h' + x.getAttribute('data-step') === S.open; x.setAttribute('aria-expanded', String(on)); document.getElementById('hs-' + x.getAttribute('data-step')).hidden = !on; }); if (!was) track('help_step_opened', { step_id: id }); b.focus({ preventScroll: true }); }));
    root.querySelectorAll('[data-contact]').forEach(b => b.addEventListener('click', () => {
      track('contact_admin_pressed', { entry_point: b.getAttribute('data-contact'), overall_state: SC.overall });
      const url = S.help && S.help.contact_url;
      if (url) { if (tg && tg.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank', 'noopener'); }
      else toast(t('admin.demoAction'));
    }));
  }

  // ---------- admin ----------
  const probeKinds = { pc: 'pc', android: 'android', abroad: 'abroad' };
  const probeCaps = { pc: ['control_internet', 'handshake', 'https'], android: ['dns', 'tcp'], abroad: ['handshake'] };
  function adminScreen() {
    const A = SC.adminData; if (!A) return '<div class="screen admin-screen"><h1 class="title" id="screen-title" tabindex="-1">' + esc(t('admin.title')) + '</h1><p class="muted">' + esc(t('status.unknown')) + '</p></div>';
    const sevOrder = { high: 0, medium: 1, low: 2 };
    const att = A.attention.slice().sort((a, b) => sevOrder[a.sev] - sevOrder[b.sev]);
    const attHtml = att.length ? '<div class="attn">' + att.map(a => '<div><span class="lp ' + a.sev + '" aria-hidden="true">' + ico(sevIcon[a.sev]) + '</span><span>' + (a.server ? '<b>' + esc(sname(a.server)) + '</b> · ' : '') + esc(a.text) + '<div class="sev">' + esc(t('admin.severity.' + a.sev)) + '</div></span></div>').join('') + '</div>' : '<p class="small muted">' + esc(t('admin.noAttention')) + '</p>';
    const pr = A.probes;
    function probeRow(k, name) {
      const p = pr[k] || {}, enrolled = p.enrolled !== false;
      const meta = enrolled ? [p.lastMin !== undefined ? t('admin.lastReport', { duration: dur(p.lastMin) }) : '', p.route !== undefined ? t(p.route ? 'admin.routeOk' : 'admin.routeBad') : '', p.queue !== undefined ? t('admin.queue', { n: p.queue }) : '', p.version ? t('admin.version', { v: p.version }) : ''].filter(Boolean).join(' · ') : t('admin.notEnrolled');
      const action = enrolled ? '<button type="button" class="btn btn-ghost btn-revoke" data-revoke="' + esc(name) + '" data-probe="' + esc(p.id || 'probe-' + k) + '">' + esc(t('admin.revoke')) + '</button>' : '<button type="button" class="btn btn-ghost" data-enroll="' + k + '">' + esc(t('admin.enroll')) + '</button>';
      return '<div class="probe-row"><div><div class="pn"><span class="c-' + { ok: 'operational', warn: 'degraded', fail: 'unavailable', unknown: 'unknown' }[p.state || 'unknown'] + '"><span class="state-dot"></span></span>' + esc(name) + ' <span class="xs muted">' + esc(t('admin.state.' + (p.state || 'unknown'))) + '</span></div><div class="pm">' + esc(meta) + '</div></div>' + action + '</div>';
    }
    const probes = probeRow('pc', t('admin.probe.pc')) + probeRow('android', t('admin.probe.android')) + probeRow('abroad', t('admin.probe.abroad'));
    const svc = '<div class="svc">' + Object.keys(A.services).map(k => '<div><span class="c-' + { ok: 'operational', warn: 'degraded', fail: 'unavailable', unknown: 'unknown' }[A.services[k]] + '"><span class="state-dot"></span></span><span>' + esc(t('admin.service.' + k) === 'admin.service.' + k ? k : t('admin.service.' + k)) + '</span><span class="xs muted" style="margin-left:auto">' + esc(t('admin.state.' + A.services[k])) + '</span></div>').join('') + '</div>';
    const d = A.doctor, dc = { ok: 'operational', warn: 'degraded', fail: 'unavailable' }[d.result];
    const doctor = '<div class="doctor"><div class="res c-' + dc + '">' + ico(d.result === 'ok' ? 'check' : d.result === 'warn' ? 'alert' : 'x') + '<span>' + esc(t('admin.doctor.' + d.result)) + '</span></div>' + d.items.map(it => '<div class="item"><div><b>' + esc(t('admin.service.' + it.name) === 'admin.service.' + it.name ? it.name : t('admin.service.' + it.name)) + '</b> · <span class="c-' + { ok: 'operational', warn: 'degraded', fail: 'unavailable' }[it.state] + '">' + esc(t('admin.state.' + it.state)) + '</span></div><div class="muted">' + esc(t('admin.doctor.next')) + ': ' + esc(it.next) + '</div>' + (it.cmd ? copyRow(it.cmd) : '') + '</div>').join('') + (A.nextCommand && !d.items.length ? copyRow(A.nextCommand) : '') + '</div>';
    const nt = SC.note, noteVal = noteDraft !== null ? noteDraft : (nt ? nt.text : '');
    const note = '<div class="stack"><textarea class="note-input" id="note-input" maxlength="' + SC.noteMax + '" placeholder="' + esc(t('admin.note.placeholder')) + '" aria-label="' + esc(t('admin.note')) + '">' + esc(noteVal) + '</textarea><div class="small muted" style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><span id="note-count">' + esc(t('admin.note.chars', { n: noteVal.length, max: SC.noteMax })) + '</span>' + (nt && nt.expires ? '<span>' + esc(t('admin.note.expires', { time: fmtTime(nt.expires) })) + '</span>' : '') + '</div><div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="btn btn-primary" id="note-save">' + esc(t('action.save')) + '</button>' + (nt ? '<button type="button" class="btn btn-ghost btn-danger" id="note-del">' + esc(t('admin.note.delete')) + '</button>' : '') + '</div>' + (!nt && !noteVal ? '<p class="small muted">' + esc(t('admin.note.empty')) + '</p>' : '') + '</div>';
    return '<div class="screen admin-screen"><h1 class="title" id="screen-title" tabindex="-1">' + esc(t('admin.title')) + '</h1>' +
      '<section class="stack"><h2 class="sub">' + esc(t('admin.attention')) + '</h2>' + attHtml + '</section>' +
      '<section class="stack"><h2 class="sub">' + esc(t('admin.probes')) + '</h2><div>' + probes + '</div></section>' +
      '<section class="stack"><h2 class="sub">' + esc(t('admin.services')) + '</h2>' + svc + '</section>' +
      '<section class="stack"><h2 class="sub">' + esc(t('admin.doctor')) + '</h2>' + doctor + '</section>' +
      '<section class="stack"><h2 class="sub">' + esc(t('admin.note')) + '</h2>' + note + '</section></div>';
  }
  function enrollSheet(code, origin) {
    openSheet('<h2>' + esc(t('admin.enroll.title')) + '</h2><div class="code" aria-live="polite">' + esc(code) + '</div><p class="small muted">' + esc(t('admin.enroll.body')) + '</p><div class="acts"><button type="button" class="btn btn-ghost" data-copy="' + esc(code) + '">' + ico('copy') + esc(t('action.copy')) + '</button><button type="button" class="btn btn-primary" data-close>' + esc(t('action.close')) + '</button></div>', origin);
  }
  function bindAdmin() {
    bindCopy();
    root.querySelectorAll('[data-enroll]').forEach(b => b.addEventListener('click', () => {
      const k = b.getAttribute('data-enroll');
      if (!api) { enrollSheet(SC.adminData.enrollCode || '—', b); return; }
      api.createEnrollment(probeKinds[k], probeCaps[k]).then(r => enrollSheet(r.code, b)).catch(e => toast(t('error.generic', { code: (e && e.code) || 'HTTP_ERROR' })));
    }));
    root.querySelectorAll('[data-revoke]').forEach(b => b.addEventListener('click', () => openSheet('<h2>' + esc(t('admin.revoke')) + '</h2><p>' + esc(t('admin.revokeConfirm', { name: b.getAttribute('data-revoke') })) + '</p><div class="acts"><button type="button" class="btn btn-ghost" data-close>' + esc(t('action.cancel')) + '</button><button type="button" class="btn btn-primary" data-confirm>' + esc(t('action.confirm')) + '</button></div>', b,
      () => apiAction(() => api.revokeProbe(b.getAttribute('data-probe'))).then(ok => { if (ok) load(); }))));
    const ni = $('#note-input'); if (ni) ni.addEventListener('input', () => { noteDraft = ni.value; $('#note-count').textContent = t('admin.note.chars', { n: ni.value.length, max: SC.noteMax }); });
    const ns = $('#note-save'); if (ns) ns.addEventListener('click', () => { const text = ($('#note-input').value || '').trim(); if (!text) return; apiAction(() => api.putNote(text)).then(ok => { if (ok) { noteDraft = null; load(); } }); });
    const nd = $('#note-del'); if (nd) nd.addEventListener('click', () => openSheet('<h2>' + esc(t('admin.note.delete')) + '</h2><p>' + esc(t('admin.note.deleteConfirm')) + '</p><div class="acts"><button type="button" class="btn btn-ghost" data-close>' + esc(t('action.cancel')) + '</button><button type="button" class="btn btn-primary" data-confirm>' + esc(t('action.confirm')) + '</button></div>', nd,
      () => apiAction(() => api.deleteNote()).then(ok => { if (ok) { noteDraft = null; load(); } })));
  }
  function openSheet(html, origin, onConfirm) {
    const bd = document.createElement('div'); bd.className = 'sheet-backdrop'; bd.innerHTML = '<div class="sheet" role="dialog" aria-modal="true">' + html + '</div>';
    document.body.appendChild(bd);
    const close = () => { bd.remove(); document.removeEventListener('keydown', onKey); if (origin) origin.focus({ preventScroll: true }); };
    const onKey = e => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    bd.addEventListener('click', e => { if (e.target === bd) close(); });
    bd.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', close));
    bd.querySelectorAll('[data-confirm]').forEach(b => b.addEventListener('click', () => { if (onConfirm) onConfirm(); else toast(t('admin.demoAction')); close(); }));
    bd.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => copy(b.getAttribute('data-copy'))));
    const f = bd.querySelector('button'); if (f) f.focus();
  }

  // ---------- render / routing ----------
  function render() {
    applyTheme(); renderHeader(); renderNav();
    let html;
    if (S.tab === 'status') html = S.server ? serverScreen(S.server) : statusScreen();
    else if (S.tab === 'events') html = eventsScreen();
    else if (S.tab === 'keys') html = keysScreen();
    else if (S.tab === 'help') html = helpScreen();
    else html = adminScreen();
    root.innerHTML = html;
    if (S.tab === 'status') { S.server ? bindServer() : bindStatus(); }
    else if (S.tab === 'events') bindEvents(); else if (S.tab === 'help') bindHelp(); else if (S.tab === 'admin') bindAdmin(); else if (S.tab === 'keys') bindHelp();
    drawCharts();
    document.body.setAttribute('data-scenario', SC.id); document.body.setAttribute('data-source', SC.source || MODE);
    try { document.dispatchEvent(new CustomEvent('vpnpulse:render', { detail: { lang: S.lang, scenario: S.scenario, role: S.role, tab: S.tab, server: S.server, source: SC.source } })); } catch (e) { /* old webview */ }
  }
  window.addEventListener('popstate', () => {
    if (S.server) {
      S.server = null; render();
      root.scrollTop = S.scrollPos;
      const row = root.querySelector('.srow[data-server="' + S.originRow + '"]'); if (row) row.focus({ preventScroll: true });
    } else render();
  });
  if (tg) { try { tg.ready(); tg.expand(); tg.BackButton.onClick(() => history.back()); if (S.theme === 'auto' && tg.colorScheme) document.documentElement.setAttribute('data-theme', tg.colorScheme); } catch (e) { /* not in Telegram */ } }
  window.addEventListener('resize', drawCharts);
  const mq = window.matchMedia('(prefers-color-scheme: dark)'); if (mq.addEventListener) mq.addEventListener('change', drawCharts);

  // ---------- showcase controls (not part of the product) ----------
  function applyShowcase(o) {
    let reload = false;
    if (o.scenario) { S.scenario = o.scenario; S.eventsState = 'ok'; S.eventsPage = 1; noteDraft = null; reload = true; }
    if (o.role) { S.role = o.role; S.sessionRole = null; if (S.role !== 'admin' && S.tab === 'admin') S.tab = 'status'; reload = true; }
    if (o.theme) S.theme = o.theme;
    if (o.lang) { S.lang = o.lang; store.set('lang', S.lang); reload = true; }
    if (o.text200 !== undefined) S.text200 = o.text200;
    if (o.showcase) document.body.setAttribute('data-showcase', o.showcase);
    if (o.screen) { const m = o.screen.match(/^server:(\w+)$/); if (m) { S.tab = 'status'; S.server = m[1]; S.open = 'checks'; } else { S.tab = o.screen; S.server = null; } }
    const p = reload ? load() : (render(), Promise.resolve());
    syncShowcase();
    return p;
  }
  function syncShowcase() {
    const sc = document.getElementById('sc-scenario'); if (sc) sc.value = S.scenario;
    document.querySelectorAll('[data-sc-role]').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-sc-role') === S.role)));
    document.querySelectorAll('[data-sc-theme]').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-sc-theme') === S.theme)));
    const tx = document.getElementById('sc-text'); if (tx) tx.setAttribute('aria-pressed', String(S.text200));
  }
  window.VPNPulseShowcase = { apply: applyShowcase, reload: load, mode: MODE, state: () => JSON.parse(JSON.stringify({ scenario: S.scenario, role: S.role, theme: S.theme, lang: S.lang, tab: S.tab, server: S.server, open: S.open, scrollPos: S.scrollPos, source: SC.source })), events, analytics: () => ({ queued: analytics.queue.length, sent: analytics.sent }), flush: flushAnalytics };
  const scSel = document.getElementById('sc-scenario');
  if (scSel) { Object.keys(FX.scenarios).forEach(id => { if (MODE === 'api' && id === 'loading') return; const o = document.createElement('option'); o.value = id; o.textContent = id; scSel.appendChild(o); }); scSel.addEventListener('change', () => applyShowcase({ scenario: scSel.value })); }
  document.querySelectorAll('[data-sc-role]').forEach(b => b.addEventListener('click', () => applyShowcase({ role: b.getAttribute('data-sc-role') })));
  document.querySelectorAll('[data-sc-theme]').forEach(b => b.addEventListener('click', () => applyShowcase({ theme: b.getAttribute('data-sc-theme') })));
  const scText = document.getElementById('sc-text'); if (scText) scText.addEventListener('click', () => applyShowcase({ text200: !S.text200 }));
  const scHide = document.getElementById('sc-hide'); if (scHide) scHide.addEventListener('click', () => applyShowcase({ showcase: 'hidden' }));
  const scLabel = document.querySelector('.showcase .sc-label'); if (scLabel && MODE === 'api') scLabel.textContent = 'Showcase · API';

  // ---------- boot ----------
  history.replaceState({ tab: S.tab, server: S.server }, '');
  if (S.server) history.pushState({ tab: 'status', server: S.server }, '');
  render(); syncShowcase();
  if (MODE !== 'api') document.body.setAttribute('data-load', 'ready');
  track('app_opened', { role: S.role, language: S.lang, theme: S.theme, viewport_bucket: window.innerWidth < 480 ? 'phone' : window.innerWidth < 1024 ? 'tablet' : 'desktop' });
  if (MODE === 'api') { load().then(() => { if (!SC.loading && SC.api !== 'auth') track('status_ready', { overall_state: SC.overall, freshness_bucket: SC.freshnessMin === null ? 'none' : SC.freshnessMin <= 3 ? 'fresh' : 'stale', load_ms: 0, coverage: SC.coverageMissing ? 'partial' : 'full' }); }); scheduleRefresh(); }
  else if (!SC.loading && SC.api !== 'auth') track('status_ready', { overall_state: SC.overall, freshness_bucket: SC.freshnessMin === null ? 'none' : SC.freshnessMin <= 3 ? 'fresh' : 'stale', load_ms: 0, coverage: SC.coverageMissing ? 'partial' : 'full' });
})();
