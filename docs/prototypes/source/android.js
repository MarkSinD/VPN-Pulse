/* VPN Pulse Probe — Android flow mock. States are showcase fixtures; nothing is sent anywhere. */
(function () {
  'use strict';
  const I18N = window.__I18N, FX = window.__FIXTURES, q = new URLSearchParams(location.search);
  const S = { state: q.get('state') || 'unbound', lang: (q.get('lang') || 'ru'), theme: q.get('theme') || 'auto', text200: q.get('text') === '200', code: '', bindError: false };
  if (!I18N[S.lang]) S.lang = 'ru';
  if (q.get('showcase') === 'hidden') document.body.setAttribute('data-showcase', 'hidden');
  const events = window.__vpnPulseEvents = [];
  const track = (name, props) => { events.push({ name, at: Date.now(), props: props || {} }); const c = document.getElementById('sc-events'); if (c) c.textContent = String(events.length); };
  const t = (k, p) => { let s = I18N[S.lang][k]; if (s === undefined) s = I18N.ru[k] !== undefined ? I18N.ru[k] : k; if (p) Object.keys(p).forEach(x => { s = s.split('{' + x + '}').join(String(p[x])); }); return s; };
  const L = o => (o && typeof o === 'object') ? (o[S.lang] || o.ru) : o;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ico = (n, cls) => '<svg class="i ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + n + '"/></svg>';
  const $ = s => document.querySelector(s);
  const content = $('#content'), bar = $('#appbar');
  const STEPS = ['bind', 'exclude', 'cellular', 'done'];
  const ONB = { unbound: 'bind', bind_error: 'bind', exclude: 'exclude', cellular_checking: 'cellular', cellular_ok: 'cellular', cellular_fail: 'cellular', cellular_nosim: 'cellular', done: 'done' };
  const servers = FX.servers.map(s => ({ id: s.id, flag: s.flag, name: s.name }));

  function applyTheme() { const h = document.documentElement; if (S.theme === 'auto') h.removeAttribute('data-theme'); else h.setAttribute('data-theme', S.theme); h.style.fontSize = S.text200 ? '200%' : ''; h.lang = S.lang; }
  function toast(m) { const el = $('#toast'); el.textContent = m; el.classList.add('show'); clearTimeout(toast.h); toast.h = setTimeout(() => el.classList.remove('show'), 2000); }
  function stepper(cur) { const idx = STEPS.indexOf(cur); return '<div class="stepper" aria-label="' + esc(STEPS.map(s => t('android.step.' + s)).join(' → ')) + '">' + STEPS.map((s, i) => '<div data-on="' + (i === idx) + '" data-done="' + (i < idx) + '"><i></i><span>' + esc(t('android.step.' + s)) + '</span></div>').join('') + '</div>'; }
  function renderBar(onb) {
    bar.innerHTML = '<button type="button" class="icon-btn ' + (onb && onb !== 'bind' ? '' : 'hidden') + '" id="back" aria-label="' + esc(t('action.back')) + '">' + ico('back') + '</button><div class="ttl">' + esc(t('android.title')) + '<small>' + esc(t('android.subtitle')) + '</small></div><button type="button" class="lang-btn" id="lang" aria-label="' + esc(t('app.lang.switch', { language: S.lang === 'ru' ? 'English' : 'русский' })) + '">' + esc(t('app.lang.other')) + '</button>';
    $('#lang').addEventListener('click', () => { S.lang = S.lang === 'ru' ? 'en' : 'ru'; render(); });
    const b = $('#back'); if (b) b.addEventListener('click', () => { const prev = { exclude: 'unbound', cellular: 'exclude', done: 'cellular_ok' }[onb]; if (prev) set(prev); });
  }
  function set(state) { S.state = state; render(); const sel = document.getElementById('sc-state'); if (sel) sel.value = state; }

  function onboarding(step) {
    let body = '';
    if (step === 'bind') {
      body = '<h1>' + esc(t('android.bind.title')) + '</h1><p class="muted">' + esc(t('android.bind.body')) + '</p><div class="field"><label for="code">' + esc(t('android.bind.code')) + '</label><input id="code" inputmode="text" autocomplete="one-time-code" placeholder="XXXX-XXXX" value="' + esc(S.code) + '" aria-invalid="' + (S.state === 'bind_error') + '" ' + (S.state === 'bind_error' ? 'aria-describedby="code-err"' : '') + '>' + (S.state === 'bind_error' ? '<div class="err" id="code-err" role="alert">' + esc(t('android.bind.error')) + '</div>' : '') + '</div><button type="button" class="btn btn-primary btn-block" id="bind">' + esc(t('android.bind.action')) + '</button>';
    } else if (step === 'exclude') {
      body = '<h1>' + esc(t('android.exclude')) + '</h1><p>' + esc(t('android.exclude.body')) + '</p><p class="muted small">' + esc(t('android.exclude.why')) + '</p><button type="button" class="btn btn-primary btn-block" id="excluded">' + ico('check') + esc(t('android.exclude.confirm')) + '</button>';
    } else if (step === 'cellular') {
      const st = S.state;
      const box = st === 'cellular_checking' ? '<div class="banner banner-info" aria-live="polite"><span class="spin" aria-hidden="true"></span><div>' + esc(t('android.cellular.checking')) + '</div></div>'
        : st === 'cellular_ok' ? '<div class="banner banner-ok" role="status">' + ico('check') + '<div>' + esc(t('android.cellular.ok')) + '</div></div>'
        : st === 'cellular_nosim' ? '<div class="banner banner-bad" role="alert">' + ico('signal') + '<div>' + esc(t('android.cellular.noSim')) + '<br><span class="muted">' + esc(t('android.cellular.fix')) + '</span></div><div class="act"><button type="button" class="btn btn-tonal" id="retry">' + esc(t('android.cellular.retry')) + '</button></div></div>'
        : '<div class="banner banner-bad" role="alert">' + ico('x') + '<div>' + esc(t('android.cellular.fail')) + '<br><span class="muted">' + esc(t('android.cellular.fix')) + '</span></div><div class="act"><button type="button" class="btn btn-tonal" id="retry">' + esc(t('android.cellular.retry')) + '</button><button type="button" class="btn btn-outline" id="settings">' + ico('settings') + esc(t('android.permission.action')) + '</button></div></div>';
      body = '<h1>' + esc(t('android.step.cellular')) + '</h1><p class="muted">' + esc(t('android.cellularReady')) + '</p>' + box + '<div class="kv"><div><span class="k">' + esc(t('android.network')) + '</span><span class="v">' + (st === 'cellular_nosim' ? '—' : 'LTE') + '</span></div><div><span class="k">' + esc(t('android.wifiOn')) + '</span><span class="v ok">' + ico('check') + '</span></div></div>' + (st === 'cellular_ok' ? '<button type="button" class="btn btn-primary btn-block" id="next">' + esc(t('android.step.done')) + '</button>' : '');
    } else {
      body = '<h1>' + esc(t('android.step.done')) + '</h1><p>' + esc(t('android.done.body')) + '</p><div class="banner banner-info">' + ico('pc') + '<div>' + esc(t('android.pcChecksVpn')) + '</div></div><button type="button" class="btn btn-primary btn-block" id="start">' + ico('play') + esc(t('android.start')) + '</button>';
    }
    return stepper(step) + body;
  }
  function main() {
    const st = S.state, running = st === 'running' || st === 'queued';
    const results = servers.map((s, i) => { const r = st === 'stale' ? 'unknown' : (st === 'queued' && i === 1) ? 'fail' : 'ok'; const cls = { ok: 'ok', fail: 'bad', unknown: 'unk' }[r]; return '<div><span class="k">' + s.flag + ' ' + esc(L(s.name)) + '</span><span class="v ' + cls + '">' + { ok: ico('check'), fail: ico('x'), unknown: '—' }[r] + esc(t('android.result.' + r)) + (st === 'stale' ? '' : ' · 14:3' + (i + 1)) + '</span></div>'; }).join('');
    const banner = st === 'queued' ? '<div class="banner banner-warn" role="status">' + ico('offline') + '<div>' + esc(t('android.offline')) + '<br><span class="muted">' + esc(t('android.queued', { n: 3 })) + '</span></div></div>'
      : st === 'stale' ? '<div class="banner banner-warn" role="status">' + ico('clock') + '<div>' + esc(t('android.stale')) + '</div></div>'
      : st === 'permission' ? '<div class="banner banner-bad" role="alert">' + ico('lock') + '<div>' + esc(t('android.permission')) + '</div><div class="act"><button type="button" class="btn btn-tonal" id="settings">' + ico('settings') + esc(t('android.permission.action')) + '</button></div></div>' : '';
    return banner +
      '<div class="card status-card"><div class="big">' + (running ? ico('pulse') : ico('stop')) + '<span>' + esc(t(running ? 'android.main.running' : 'android.main.stopped')) + '</span></div><p class="muted small">' + esc(t(running ? 'android.main.everyMinute' : 'android.main.background')) + '</p><div class="acts"><button type="button" class="btn btn-primary" id="start" ' + (running || st === 'permission' ? 'disabled' : '') + '>' + ico('play') + esc(t('android.start')) + '</button><button type="button" class="btn btn-outline" id="stop" ' + (running ? '' : 'disabled') + '>' + ico('stop') + esc(t('android.stop')) + '</button></div></div>' +
      '<div class="card"><div class="kv"><div><span class="k">' + esc(t('android.network')) + '</span><span class="v">' + ico('signal') + (st === 'permission' ? '—' : 'LTE') + '</span></div><div><span class="k">' + esc(t('android.route')) + '<small>' + esc(t('android.cellularReady')) + '</small></span><span class="v ' + (st === 'permission' ? 'unk' : 'ok') + '">' + (st === 'permission' ? '—' : ico('check') + esc(t('android.route.ok'))) + '</span></div><div><span class="k">' + esc(t('android.lastCheck')) + '</span><span class="v">' + (st === 'stale' ? '3 ' + esc(t('duration.hour', { n: 3 }).replace(/^3\s*/, '')) : st === 'stopped' ? '14:33' : '14:33') + '</span></div><div><span class="k">' + esc(t('android.queue')) + '</span><span class="v">' + (st === 'queued' ? 3 : 0) + '</span></div></div></div>' +
      '<div class="card"><h2 style="font-size:1rem">' + esc(t('android.results')) + '</h2><div class="kv">' + results + '</div><p class="footnote">' + esc(t('android.pcChecksVpn')) + '</p></div>' +
      '<div class="card"><div class="kv"><div><span class="k">' + esc(t('android.sent')) + '</span><span class="v">' + (st === 'queued' ? esc(t('android.queued', { n: 3 })) : '14:33') + '</span></div><div><span class="k">' + esc(t('android.bound')) + '</span><span class="v ok">' + ico('check') + '</span></div></div><button type="button" class="btn btn-outline btn-danger btn-block" id="unbind">' + esc(t('android.unbind')) + '</button></div>';
  }
  function render() {
    applyTheme();
    const onb = ONB[S.state];
    renderBar(onb);
    content.innerHTML = onb ? onboarding(onb) : main();
    const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
    const code = $('#code'); if (code) code.addEventListener('input', () => { S.code = code.value; });
    on('bind', () => { track('android_onboarding_step', { step: 'bind', result: S.code.trim().length >= 8 ? 'ok' : 'error' }); set(S.code.trim().length >= 8 ? 'exclude' : 'bind_error'); if (S.state === 'bind_error') { const c = $('#code'); if (c) c.focus(); } });
    on('excluded', () => { track('android_onboarding_step', { step: 'exclude', result: 'confirmed' }); set('cellular_checking'); setTimeout(() => { if (S.state === 'cellular_checking') { track('android_route_check', { result: 'ok', ip_family: 'v4' }); set('cellular_ok'); } }, 1200); });
    on('retry', () => { set('cellular_checking'); setTimeout(() => { if (S.state === 'cellular_checking') { track('android_route_check', { result: 'ok', ip_family: 'v4' }); set('cellular_ok'); } }, 1200); });
    on('next', () => set('done'));
    on('start', () => { track('android_probe_started', { network_type: 'cellular', vpn_excluded_confirmed: true }); set('running'); });
    on('stop', () => { track('android_probe_stopped', { reason: 'user', duration_bucket: 'short' }); set('stopped'); });
    on('settings', () => toast(t('admin.demoAction')));
    on('unbind', () => { toast(t('admin.demoAction')); });
    try { document.dispatchEvent(new CustomEvent('vpnpulse:render', { detail: { lang: S.lang, state: S.state } })); } catch (e) { /* */ }
  }
  window.VPNPulseShowcase = { apply(o) { if (o.state) S.state = o.state; if (o.lang) S.lang = o.lang; if (o.theme) S.theme = o.theme; if (o.text200 !== undefined) S.text200 = o.text200; if (o.showcase) document.body.setAttribute('data-showcase', o.showcase); render(); }, state: () => ({ state: S.state, lang: S.lang }), events };
  const sel = document.getElementById('sc-state');
  if (sel) { ['unbound', 'bind_error', 'exclude', 'cellular_checking', 'cellular_ok', 'cellular_fail', 'cellular_nosim', 'done', 'running', 'stopped', 'queued', 'stale', 'permission'].forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); }); sel.value = S.state; sel.addEventListener('change', () => set(sel.value)); }
  document.querySelectorAll('[data-sc-theme]').forEach(b => b.addEventListener('click', () => { S.theme = b.getAttribute('data-sc-theme'); document.querySelectorAll('[data-sc-theme]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); render(); }));
  const tx = document.getElementById('sc-text'); if (tx) tx.addEventListener('click', () => { S.text200 = !S.text200; tx.setAttribute('aria-pressed', String(S.text200)); render(); });
  const hide = document.getElementById('sc-hide'); if (hide) hide.addEventListener('click', () => document.body.setAttribute('data-showcase', 'hidden'));
  render();
})();
