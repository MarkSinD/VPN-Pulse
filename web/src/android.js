/* VPN Pulse Probe — Android flow mock. States are showcase fixtures; nothing is sent anywhere.
   The screen is built the way a VPN client is: the ring in the middle says what is happening and
   starts or stops the checks; the line under it is the route; the sheet at the bottom is what was
   measured. Palette, type and lamps come from the Mini App's tokens. */
(function () {
  'use strict';
  const I18N = window.__I18N, FX = window.__FIXTURES, q = new URLSearchParams(location.search);
  const S = { state: q.get('state') || 'unbound', lang: (q.get('lang') || 'ru'), theme: q.get('theme') || 'auto', text200: q.get('text') === '200', code: '', tab: q.get('tab') || 'check', details: false };
  if (!I18N[S.lang]) S.lang = 'ru';
  if (q.get('showcase') === 'hidden') document.body.setAttribute('data-showcase', 'hidden');
  const events = window.__vpnPulseEvents = [];
  const track = (name, props) => { events.push({ name, at: Date.now(), props: props || {} }); const c = document.getElementById('sc-events'); if (c) c.textContent = String(events.length); };
  const t = (k, p) => { let s = I18N[S.lang][k]; if (s === undefined) s = I18N.ru[k] !== undefined ? I18N.ru[k] : k; if (p) Object.keys(p).forEach(x => { s = s.split('{' + x + '}').join(String(p[x])); }); return s; };
  const L = o => (o && typeof o === 'object') ? (o[S.lang] || o.ru) : o;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ico = (n, cls) => '<svg class="i ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + n + '"/></svg>';
  const $ = s => document.querySelector(s);
  const content = $('#content'), bar = $('#appbar'), tabs = $('#tabbar');
  const STEPS = ['bind', 'exclude', 'cellular', 'done'];
  const ONB = { unbound: 'bind', bind_error: 'bind', exclude: 'exclude', cellular_checking: 'cellular', cellular_ok: 'cellular', cellular_fail: 'cellular', cellular_nosim: 'cellular', done: 'done' };
  const servers = FX.servers.map(s => ({ id: s.id, flag: s.flag, name: s.name }));
  // one place decides how a state looks: ring colour, whether it breathes, the words inside
  const RING = {
    running: { state: 'operational', live: true, title: 'android.main.running', sub: 'android.main.everyMinute', hint: 'android.ring.stop' },
    queued: { state: 'degraded', live: true, title: 'android.main.running', sub: 'android.main.everyMinute', hint: 'android.ring.stop' },
    stopped: { state: 'unknown', live: false, title: 'android.main.stopped', sub: 'android.main.background', hint: 'android.ring.start' },
    stale: { state: 'degraded', live: false, title: 'android.stale', sub: 'android.main.background', hint: 'android.ring.start' },
    permission: { state: 'unavailable', live: false, title: 'android.permission', sub: null, hint: null },
    cellular_checking: { state: 'unknown', busy: true, title: 'android.cellular.checking', sub: null, hint: null },
    cellular_ok: { state: 'operational', live: false, title: 'android.route.ok', sub: 'android.cellular.ok', hint: null },
    cellular_fail: { state: 'unavailable', live: false, title: 'android.route.bad', sub: 'android.cellular.fail', hint: null },
    cellular_nosim: { state: 'unknown', live: false, title: 'android.cellular.noSim', sub: 'android.cellular.fix', hint: null }
  };

  function applyTheme() { const h = document.documentElement; if (S.theme === 'auto') h.removeAttribute('data-theme'); else h.setAttribute('data-theme', S.theme); h.style.fontSize = S.text200 ? '200%' : ''; h.lang = S.lang; }
  function toast(m) { const el = $('#toast'); el.textContent = m; el.classList.add('show'); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove('show'), 2000); }
  function set(state) { S.state = state; render(); const sel = document.getElementById('sc-state'); if (sel) sel.value = state; }
  function stepper(cur) { const idx = STEPS.indexOf(cur); return '<div class="stepper" aria-label="' + esc(STEPS.map(s => t('android.step.' + s)).join(' → ')) + '">' + STEPS.map((s, i) => '<div data-on="' + (i === idx) + '" data-done="' + (i < idx) + '"><i></i><span>' + esc(t('android.step.' + s)) + '</span></div>').join('') + '</div>'; }

  function renderBar(onb) {
    bar.innerHTML = '<button type="button" class="icon-btn ' + (onb && onb !== 'bind' ? '' : 'hidden') + '" id="back" aria-label="' + esc(t('action.back')) + '">' + ico('back') + '</button>'
      + '<div class="ttl">' + esc(t('android.title')) + '<small>' + esc(t('android.subtitle')) + '</small></div>'
      + '<button type="button" class="lang-btn" id="lang" aria-label="' + esc(t('app.lang.switch', { language: S.lang === 'ru' ? 'English' : 'русский' })) + '">' + esc(t('app.lang.other')) + '</button>';
    $('#lang').addEventListener('click', () => { S.lang = S.lang === 'ru' ? 'en' : 'ru'; render(); });
    const b = $('#back'); if (b) b.addEventListener('click', () => { const prev = { exclude: 'unbound', cellular: 'exclude', done: 'cellular_ok' }[onb]; if (prev) set(prev); });
  }

  // the ring: state, and on the main screen the control itself
  function ring(key, clickable) {
    const r = RING[key]; if (!r) return '';
    const inner = '<span class="st">' + esc(t(r.title)) + '</span>' + (r.sub ? '<span class="sub">' + esc(t(r.sub)) + '</span>' : '');
    const attrs = 'class="ring" data-state="' + r.state + '"' + (r.live ? ' data-live="true"' : '') + (r.busy ? ' data-busy="true"' : '');
    if (!clickable) return '<div ' + attrs + ' role="img" aria-label="' + esc(t(r.title)) + '">' + inner + '</div>';
    return '<button type="button" ' + attrs + ' id="ring" aria-label="' + esc(t(r.title) + (r.hint ? '. ' + t(r.hint) : '')) + '">' + inner + '</button>';
  }

  function onboarding(step) {
    if (step === 'cellular') {
      const st = S.state;
      const act = st === 'cellular_ok'
        ? '<button type="button" class="btn btn-primary btn-block" id="next">' + esc(t('android.step.done')) + '</button>'
        : st === 'cellular_checking' ? ''
          : '<button type="button" class="btn btn-primary btn-block" id="retry">' + ico('refresh') + esc(t('android.cellular.retry')) + '</button>'
          + (st === 'cellular_fail' ? '<button type="button" class="btn btn-outline btn-block" id="settings">' + ico('settings') + esc(t('android.permission.action')) + '</button>' : '');
      return stepper(step)
        + '<div class="hero">' + ring(st, false) + '<p class="hint">' + esc(t(st === 'cellular_ok' ? 'android.wifiOn' : 'android.cellularReady')) + '</p></div>'
        + '<div class="dock">' + act + '</div>';
    }
    let body = '';
    if (step === 'bind') {
      body = '<div class="step-body"><h1>' + esc(t('android.bind.title')) + '</h1><p class="muted">' + esc(t('android.bind.body')) + '</p>'
        + '<div class="field"><label for="code">' + esc(t('android.bind.code')) + '</label><input id="code" inputmode="text" autocomplete="one-time-code" placeholder="XXXX-XXXX" value="' + esc(S.code) + '" aria-invalid="' + (S.state === 'bind_error') + '"' + (S.state === 'bind_error' ? ' aria-describedby="code-err"' : '') + '>'
        + (S.state === 'bind_error' ? '<div class="err" id="code-err" role="alert">' + esc(t('android.bind.error')) + '</div>' : '') + '</div></div>'
        + '<div class="dock"><button type="button" class="btn btn-primary btn-block" id="bind">' + esc(t('android.bind.action')) + '</button></div>';
    } else if (step === 'exclude') {
      body = '<div class="step-body"><h1>' + esc(t('android.exclude')) + '</h1><p>' + esc(t('android.exclude.body')) + '</p><p class="muted small">' + esc(t('android.exclude.why')) + '</p></div>'
        + '<div class="dock"><button type="button" class="btn btn-primary btn-block" id="excluded">' + ico('check') + esc(t('android.exclude.confirm')) + '</button></div>';
    } else {
      body = '<div class="hero">' + ring('cellular_ok', false) + '</div>'
        + '<div class="step-body"><h1>' + esc(t('android.step.done')) + '</h1><p class="muted">' + esc(t('android.done.body')) + '</p>'
        + '<div class="banner banner-info">' + ico('pc') + '<div>' + esc(t('android.pcChecksVpn')) + '</div></div></div>'
        + '<div class="dock"><button type="button" class="btn btn-primary btn-block" id="start">' + ico('play') + esc(t('android.start')) + '</button></div>';
    }
    return stepper(step) + body;
  }

  // ---------- main: ring, route line, sheet ----------
  function routeChip(st) {
    const bad = st === 'permission';
    const cls = bad ? 'bad' : 'ok';
    const text = t('android.route') + ': ' + t(bad ? 'android.route.bad' : 'android.route.ok');
    return '<button type="button" class="chip ' + cls + '" id="details" aria-expanded="' + S.details + '"><span class="lamp" aria-hidden="true"></span><span class="txt">' + esc(text) + '</span>' + ico('chevron-down', 'chev') + '</button>';
  }
  function notice(st) {
    if (st === 'queued') return '<div class="banner banner-warn" role="status">' + ico('offline') + '<div>' + esc(t('android.offline')) + '<br><span class="muted">' + esc(t('android.queued', { n: 3 })) + '</span></div></div>';
    if (st === 'permission') return '<div class="banner banner-bad" role="alert">' + ico('lock') + '<div>' + esc(t('android.permission')) + '</div><div class="act"><button type="button" class="btn btn-tonal" id="settings">' + ico('settings') + esc(t('android.permission.action')) + '</button></div></div>';
    return '';
  }
  function resultRows(st) {
    return servers.map((s, i) => {
      const r = st === 'stale' || st === 'permission' ? 'unknown' : (st === 'queued' && i === 1) ? 'fail' : 'ok';
      const cls = { ok: 'ok', fail: 'bad', unknown: 'unk' }[r];
      const when = (st === 'stale' || st === 'permission') ? '' : ' · 14:3' + (i + 1);
      return '<div><span class="k">' + s.flag + ' ' + esc(L(s.name)) + '</span><span class="v ' + cls + '"><span class="lamp" aria-hidden="true"></span>' + esc(t('android.result.' + r) + when) + '</span></div>';
    }).join('');
  }
  function detailRows(st) {
    const row = (k, v, cls) => '<div><span class="k">' + esc(k) + '</span><span class="v ' + (cls || '') + '">' + v + '</span></div>';
    return '<div class="rows">'
      + row(t('android.network'), ico('signal') + (st === 'permission' ? '—' : 'LTE'))
      + row(t('android.wifiOn'), ico('check'), 'ok')
      + row(t('android.lastCheck'), esc(st === 'stale' ? t('duration.hour', { n: 3 }) : '14:33'))
      + row(t('android.queue'), String(st === 'queued' ? 3 : 0), st === 'queued' ? 'bad' : '')
      + '</div>';
  }
  function checkTab() {
    const st = S.state;
    return notice(st)
      + '<div class="hero">' + ring(st, st !== 'permission') + routeChip(st) + '</div>'
      + (S.details ? '<div class="card">' + detailRows(st) + '</div>' : '')
      + '<div class="sheet"><div class="grab" aria-hidden="true"></div>'
      + '<h2>' + esc(t('android.results')) + '<time>' + esc(st === 'stale' ? t('android.stale') : t('android.lastCheck') + ' 14:33') + '</time></h2>'
      + '<div class="rows">' + resultRows(st) + '</div>'
      + '<p class="footnote">' + esc(t('android.pcChecksVpn')) + '</p></div>';
  }
  function settingsTab() {
    const st = S.state;
    return '<div class="card">' + detailRows(st) + '</div>'
      + '<div class="card"><div class="rows">'
      + '<div><span class="k">' + esc(t('android.sent')) + '</span><span class="v">' + esc(st === 'queued' ? t('android.queued', { n: 3 }) : '14:33') + '</span></div>'
      + '<div><span class="k">' + esc(t('android.bound')) + '</span><span class="v ok"><span class="lamp" aria-hidden="true"></span>' + ico('check') + '</span></div>'
      + '</div></div>'
      + '<div class="card"><p class="muted small">' + esc(t('android.exclude.why')) + '</p>'
      + '<button type="button" class="btn btn-outline btn-danger btn-block" id="unbind">' + esc(t('android.unbind')) + '</button></div>';
  }
  function renderTabs(show) {
    tabs.classList.toggle('hidden', !show);
    if (!show) { tabs.innerHTML = ''; return; }
    const item = (id, icon, label) => '<button type="button" data-tab="' + id + '"' + (S.tab === id ? ' aria-current="page"' : '') + '>' + ico(icon) + '<span>' + esc(label) + '</span></button>';
    tabs.innerHTML = item('check', 'pulse', t('android.tab.check')) + item('settings', 'settings', t('android.tab.settings'));
    tabs.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => { S.tab = b.getAttribute('data-tab'); render(); }));
  }

  function render() {
    applyTheme();
    const onb = ONB[S.state];
    renderBar(onb);
    renderTabs(!onb);
    content.className = 'content' + (onb && onb !== 'bind' && onb !== 'exclude' ? ' stage' : '');
    content.innerHTML = onb ? onboarding(onb) : (S.tab === 'settings' ? settingsTab() : checkTab());
    const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
    const code = $('#code'); if (code) code.addEventListener('input', () => { S.code = code.value; });
    on('bind', () => { track('android_onboarding_step', { step: 'bind', result: S.code.trim().length >= 8 ? 'ok' : 'error' }); set(S.code.trim().length >= 8 ? 'exclude' : 'bind_error'); if (S.state === 'bind_error') { const c = $('#code'); if (c) c.focus(); } });
    on('excluded', () => { track('android_onboarding_step', { step: 'exclude', result: 'confirmed' }); set('cellular_checking'); setTimeout(() => { if (S.state === 'cellular_checking') { track('android_route_check', { result: 'ok', ip_family: 'v4' }); set('cellular_ok'); } }, 1200); });
    on('retry', () => { set('cellular_checking'); setTimeout(() => { if (S.state === 'cellular_checking') { track('android_route_check', { result: 'ok', ip_family: 'v4' }); set('cellular_ok'); } }, 1200); });
    on('next', () => set('done'));
    on('start', () => { track('android_probe_started', { network_type: 'cellular', vpn_excluded_confirmed: true }); set('running'); });
    on('ring', () => {
      const running = S.state === 'running' || S.state === 'queued';
      if (running) { track('android_probe_stopped', { reason: 'user', duration_bucket: 'short' }); set('stopped'); }
      else { track('android_probe_started', { network_type: 'cellular', vpn_excluded_confirmed: true }); set('running'); }
    });
    on('details', () => { S.details = !S.details; render(); });
    on('settings', () => toast(t('admin.demoAction')));
    on('unbind', () => toast(t('admin.demoAction')));
    try { document.dispatchEvent(new CustomEvent('vpnpulse:render', { detail: { lang: S.lang, state: S.state, tab: S.tab } })); } catch (e) { /* old webview */ }
  }

  window.VPNPulseShowcase = { apply(o) { if (o.state) S.state = o.state; if (o.lang) S.lang = o.lang; if (o.theme) S.theme = o.theme; if (o.text200 !== undefined) S.text200 = o.text200; if (o.showcase) document.body.setAttribute('data-showcase', o.showcase); render(); }, state: () => ({ state: S.state, lang: S.lang, tab: S.tab }), events };
  const sel = document.getElementById('sc-state');
  if (sel) { ['unbound', 'bind_error', 'exclude', 'cellular_checking', 'cellular_ok', 'cellular_fail', 'cellular_nosim', 'done', 'running', 'stopped', 'queued', 'stale', 'permission'].forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); }); sel.value = S.state; sel.addEventListener('change', () => set(sel.value)); }
  document.querySelectorAll('[data-sc-theme]').forEach(b => b.addEventListener('click', () => { S.theme = b.getAttribute('data-sc-theme'); document.querySelectorAll('[data-sc-theme]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); render(); }));
  const tx = document.getElementById('sc-text'); if (tx) tx.addEventListener('click', () => { S.text200 = !S.text200; tx.setAttribute('aria-pressed', String(S.text200)); render(); });
  const hide = document.getElementById('sc-hide'); if (hide) hide.addEventListener('click', () => document.body.setAttribute('data-showcase', 'hidden'));
  render();
})();
