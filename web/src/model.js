/* VPN Pulse — view model: one shape for the renderer, two producers.
     fromFixtures(FX, scenarioId, ctx)  — compact demo scenarios (prototype opened as a file, showcase)
     fromApi(bundle, ctx)               — contract payloads (live API, dev server)
   app.js consumes only the shape below and never looks at raw fixtures or raw API payloads,
   so both paths must render the same DOM — scripts/ui_check.py --parity enforces that. */
window.VPNPulseModel = (function () {
  'use strict';
  const KINDS = ['pc', 'mobile', 'abroad'];
  const KIND_PROBE = { pc: 'pc', mobile: 'android', abroad: 'abroad' };
  const STATE_RESULT = { operational: 'ok', unavailable: 'fail', degraded: 'partial', unknown: 'unknown' };
  const NOTE_MAX = 240;
  const FRESH_MIN = 3; // freshness window in minutes (monitoring policy: 180 s)

  // ---------- shared helpers (formatting lives here so both producers agree) ----------
  const pick = (v, lang) => (v && typeof v === 'object') ? (v[lang] || v.ru || '') : (v === undefined || v === null ? '' : String(v));
  function fmtPct(x, lang) {
    if (x === null || x === undefined || isNaN(x)) return '—';
    const p = Math.round(x * 1000) / 10;
    const s = Number.isInteger(p) ? String(p) : p.toFixed(1);
    return (lang === 'ru' ? s.replace('.', ',') : s) + '%';
  }
  const parsePct = s => { if (s === null || s === undefined || s === '—') return null; const n = parseFloat(String(s).replace('%', '').replace(',', '.')); return isNaN(n) ? null : n / 100; };
  const pad = n => (n < 10 ? '0' : '') + n;
  const fmtTime = d => d ? pad(d.getHours()) + ':' + pad(d.getMinutes()) : '';
  const minutesSince = (iso, now) => iso ? Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000)) : null;
  function countryName(cc, lang, fallback) {
    try { const n = new Intl.DisplayNames([lang === 'ru' ? 'ru' : 'en'], { type: 'region' }).of(cc.toUpperCase()); if (n && n !== cc.toUpperCase()) return n; } catch (e) { /* old webview */ }
    return fallback || cc.toUpperCase();
  }
  // fictional demand curve shared with the dev server (vpnpulse.dev.scenarios._seeded)
  function seeded(seed, base, amp, points, hoursPerPoint) {
    const a = [];
    for (let i = 0; i < points; i++) { const h = i * hoursPerPoint, day = Math.max(0, Math.sin((h - 6) / 24 * Math.PI * 2)); a.push(Math.max(0, Math.round((base + amp * day + ((i * 7 + seed) % 5) * 0.3 - 0.6) * 10) / 10)); }
    return a;
  }
  const roundCount = v => v === null ? null : Math.floor(v + 0.5);
  // day/time of a fixture event → Date (UTC calendar, like the dev server)
  function fixtureAt(now, day, hhmm) {
    const [h, m] = String(hhmm || '00:00').split(':').map(Number);
    if (typeof day === 'number') { const d = new Date(now); d.setUTCDate(d.getUTCDate() - day); return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), h, m)); }
    const p = String(day).split('-').map(Number); return new Date(Date.UTC(p[0], p[1] - 1, p[2], h, m));
  }
  // what confirms the current state: the PC test, member connections, both or nothing
  function confirmedBy(state, sources, humans) {
    const pc = sources.pc;
    const pcConfirms = pc && pc.age !== null && pc.age !== undefined && pc.age <= FRESH_MIN && (state === 'unavailable' ? pc.r === 'fail' : pc.r === 'ok');
    const humansConfirm = humans && state !== 'unavailable' && state !== 'unknown';
    return pcConfirms && humansConfirm ? 'both' : pcConfirms ? 'pc' : humansConfirm ? 'humans' : 'none';
  }
  function conflictOf(state, sources, humans) {
    if (state === 'unavailable' || !sources.pc || sources.pc.r !== 'fail') return null;
    if (humans) return { a: 'server.conflict.pcFail', b: 'server.conflict.humansOk' };
    if (sources.abroad && sources.abroad.r === 'ok') return { a: 'server.conflict.pcFail', b: 'server.conflict.abroadOk' };
    return null;
  }
  const missingKinds = presence => { const m = KINDS.filter(k => presence[k] === 'none'); return m.length ? m : null; };
  function finishServer(s, lang) {
    s.country = countryName(s.cc, lang, s.countryFallback);
    s.uptime24 = fmtPct(s.uptime24n, lang); s.uptime7 = fmtPct(s.uptime7n, lang);
    return s;
  }

  // ---------- producer 1: compact fixtures ----------
  function merged(FX, id) {
    const raw = FX.scenarios[id] || FX.scenarios.operational;
    if (!raw.inherit) return Object.assign({}, raw);
    const base = merged(FX, raw.inherit), sc = Object.assign({}, base, raw);
    sc.servers = Object.assign({}, base.servers || {});
    Object.keys(raw.servers || {}).forEach(sid => { sc.servers[sid] = Object.assign({}, sc.servers[sid] || {}, raw.servers[sid]); });
    if (!('events' in raw)) sc.events = base.events;
    return sc;
  }
  function fromFixtures(FX, id, ctx) {
    const lang = ctx.lang, now = ctx.now;
    const sc = merged(FX, id);
    const vm = {
      id, source: 'fixtures', overall: sc.overall || 'unknown', freshnessMin: sc.freshnessMin === undefined ? null : sc.freshnessMin,
      recommended: sc.recommended || null, empty: !!sc.empty, loading: !!sc.loading, api: sc.api || null, code: sc.code || null,
      demo: !!sc.demo, lastKnownTime: sc.lastKnownTime || null, since: FX.meta.since ? new Date(FX.meta.since + 'T00:00:00Z') : null,
      noteMax: NOTE_MAX, note: null, list: [], eventsList: [], adminData: null, presence: {}
    };
    if (sc.note) vm.note = { text: pick(sc.note.text, lang), at: fixtureAt(now, 0, sc.note.time), expires: sc.note.expires ? fixtureAt(now, 0, sc.note.expires) : null };
    // events
    let ev = sc.events; if (typeof ev === 'string') ev = FX.eventSets[ev]; ev = (ev || []).slice();
    if (sc.eventsAppend) ev = ev.concat(FX.eventSets[sc.eventsAppend]);
    vm.eventsList = ev.map(e => ({ kind: e.kind, sev: e.sev, server: e.server || null, at: fixtureAt(now, e.day, e.time), text: e.text === undefined ? null : pick(e.text, lang), source: e.source || null, state: e.state || null }));
    vm.eventsList.sort((a, b) => b.at - a.at); // newest first, ties keep their order (stable sort) — same as the API
    // admin
    if (sc.admin !== null) {
      const a = sc.admin || {}, A = FX.defaults.admin;
      const attention = (a.attentionPrepend || []).concat(a.attention !== undefined ? a.attention : A.attention);
      vm.adminData = {
        attention: attention.map(x => ({ sev: x.sev, server: x.server || null, text: pick(x.text, lang), code: x.code || 'ATTENTION' })),
        probes: (() => { const raw = Object.assign({}, A.probes, a.probes || {}), out = {}; Object.keys(raw).forEach(k => { out[k] = Object.assign({ id: 'probe-' + k }, raw[k]); }); return out; })(),
        services: Object.assign({}, A.services, a.services || {}),
        doctor: { result: (a.doctor || A.doctor).result, items: (a.doctor || A.doctor).items.map(it => ({ name: it.name, state: it.state, next: pick(it.next, lang), cmd: it.cmd || null })) },
        enrollCode: A.enrollCode, nextCommand: a.nextCommand || null
      };
    }
    // presence of check sources
    const over = sc.sources || {};
    KINDS.forEach(k => {
      if (over[k]) { vm.presence[k] = over[k]; return; }
      const p = vm.adminData ? vm.adminData.probes[KIND_PROBE[k]] : null;
      vm.presence[k] = !p || p.enrolled === false ? 'none' : (p.state === 'unknown' ? 'silent' : 'active');
    });
    vm.coverageMissing = missingKinds(vm.presence);
    // servers
    if (!sc.empty && !sc.loading && sc.api !== 'auth') {
      FX.servers.forEach(base_s => {
        const o = (sc.servers || {})[base_s.id]; if (!o) return;
        const s = Object.assign({}, base_s, o);
        s.name = pick(s.name, lang); s.countryFallback = pick(base_s.country, lang);
        s.abroadFrom = base_s.abroadFrom || null;
        s.load = Object.assign({}, FX.defaults.load[s.id], o.load || {});
        s.sources = {};
        KINDS.forEach(k => { s.sources[k] = Object.assign({}, FX.defaults.sourcesOk[k], (o.sources || {})[k] || {}); });
        // a source whose probe does not exist carries no evidence (the API sends none for it)
        KINDS.forEach(k => { if (vm.presence[k] === 'none') s.sources[k] = { r: 'unknown', age: null, detailKey: 'source.detail.notEnrolled' }; s.sources[k].via = k === 'abroad' ? s.abroadFrom : null; });
        const base = s.load.awg ? 1 + s.load.awg / 4 : 0.3, amp = 3 + s.load.awg;
        s.series = seeded(s.seed, base, amp, 48, 0.5);
        if (s.state === 'unavailable') { s.series[46] = 0; s.series[47] = 0; }
        s.segs = []; for (let i = 0; i < 48; i++) s.segs.push('operational');
        (o.marks || []).forEach(m => { for (let i = m[0]; i <= m[1]; i++) s.segs[i] = m[2]; });
        if (o.gapFrom !== undefined) { for (let i = o.gapFrom; i < 48; i++) { s.segs[i] = 'unknown'; s.series[i] = null; } }
        s.series = s.series.map(roundCount);
        s.series7 = seeded(s.seed, base, amp, 168, 1); s.segs7 = [];
        for (let i = 0; i < 168; i++) s.segs7.push(i < 120 ? 'operational' : s.segs[i - 120]);
        s.series7 = s.series7.map((v, i) => s.segs7[i] === 'unknown' ? null : roundCount(v));
        s.software = (s.software || []).map(w => ({ name: w.name, noteKey: w.noteKey || null, note: w.note || null }));
        s.uptime24n = parsePct(s.uptime24); s.uptime7n = parsePct(s.uptime7);
        s.diag = !!s.diag;
        const humans = s.confirmedBy === 'humans' || s.confirmedBy === 'both';
        s.confirmedBy = confirmedBy(s.state, s.sources, humans);
        s.conflict = conflictOf(s.state, s.sources, humans);
        vm.list.push(finishServer(s, lang));
      });
    }
    return vm;
  }

  // ---------- producer 2: contract payloads ----------
  function evidenceMap(items, now) {
    const out = {};
    (items || []).forEach(x => { if (KINDS.indexOf(x.source) === -1) return; out[x.source] = { r: STATE_RESULT[x.state] || 'unknown', age: minutesSince(x.freshness && x.freshness.observed_at, now), detailKey: x.reason_code ? 'source.detail.' + x.reason_code : 'source.detail.notEnrolled', via: x.via_server_id || null }; });
    return out;
  }
  function apiServer(card, detail, metrics, adminDetail, ctx) {
    const lang = ctx.lang, now = ctx.now, d = detail || {};
    const s = { id: card.id, name: card.name, cc: (card.country_code || '').toLowerCase(), countryFallback: card.country_code, state: card.state };
    s.uptime24n = card.uptime_24h === undefined ? null : card.uptime_24h; s.uptime7n = d.uptime_7d === undefined ? null : d.uptime_7d;
    s.staleMin = card.freshness && card.freshness.is_stale && card.freshness.observed_at ? minutesSince(card.freshness.observed_at, now) : undefined;
    const evidence = (d.checks && d.checks.length ? d.checks : card.sources) || [];
    s.sources = evidenceMap(evidence, now);
    KINDS.forEach(k => { if (!s.sources[k]) s.sources[k] = { r: 'unknown', age: null, detailKey: 'source.detail.notEnrolled', via: null }; });
    s.abroadFrom = s.sources.abroad.via;
    const humans = evidence.some(x => x.source === 'human_activity' && x.state === 'operational' && !(x.freshness && x.freshness.is_stale));
    s.confirmedBy = confirmedBy(s.state, s.sources, humans);
    s.conflict = conflictOf(s.state, s.sources, humans);
    const protos = d.protocols || [];
    s.protocols = protos.map(p => p.kind === 'xray_reality' ? 'xray' : 'awg');
    const awg = protos.find(p => p.kind === 'amneziawg'), xr = protos.find(p => p.kind === 'xray_reality'), res = d.resources || {}, prof = d.profiles || {};
    s.load = { awg: awg ? (awg.connections || 0) : 0, xray: xr ? xr.connections : null, xrayKnown: xr ? xr.connections !== null : true, mbit: res.traffic_mbps === undefined ? null : res.traffic_mbps, cpu: res.cpu_percent === undefined ? null : res.cpu_percent, ram: res.memory_percent === undefined ? null : res.memory_percent, swap: res.swap_percent === undefined ? null : res.swap_percent, peak: res.peak_connections_24h === undefined ? null : res.peak_connections_24h, lastConnMin: minutesSince(prof.last_connection_at, now) };
    s.software = (d.components || []).map(c => ({ name: c.name + (c.version ? ' ' + c.version : ''), noteKey: c.note_key || null, note: c.note || null }));
    s.keys = { issued: prof.issued === undefined ? null : prof.issued, ever: prof.ever_connected === undefined ? null : prof.ever_connected, active: prof.active_24h === undefined ? null : prof.active_24h };
    const checks = {}; (d.service_checks || []).forEach(c => { checks[c.check] = c.ok; });
    const engineKernel = (d.components || []).some(c => c.id === 'amneziawg' && c.note_key === 'server.software.kernel');
    s.system = { ssh: checks.ssh !== false, engine: engineKernel ? 'module' : 'container', port: checks.port !== false };
    if ('dns' in checks) { s.system.dns = true; s.system.ddns = checks.ddns !== false; }
    const m24 = metrics && metrics['24h'], m7 = metrics && metrics['7d'];
    s.series = m24 ? m24.points.map(p => p.connections) : []; s.segs = m24 ? m24.points.map(p => p.state) : [];
    s.series7 = m7 ? m7.points.map(p => p.connections) : null; s.segs7 = m7 ? m7.points.map(p => p.state) : null;
    s.diag = !!(adminDetail && adminDetail.diagnostics && adminDetail.diagnostics.code === 'BLOCKED_IN_COUNTRY');
    return finishServer(s, lang);
  }
  function fromApi(b, ctx) {
    const now = ctx.now, st = b.status;
    const vm = { id: ctx.scenario || 'live', source: 'api', overall: st.state, freshnessMin: minutesSince(st.freshness && st.freshness.observed_at, now), recommended: st.recommended_server_id || null,
      empty: st.servers.length === 0, loading: false, api: null, code: null, demo: st.mode === 'demo', lastKnownTime: null,
      since: st.observing_since ? new Date(st.observing_since) : null, noteMax: NOTE_MAX, note: null, list: [], eventsList: [], adminData: null, presence: {} };
    if (st.note) vm.note = { text: st.note.text, at: new Date(st.note.created_at), expires: st.note.expires_at ? new Date(st.note.expires_at) : null };
    KINDS.forEach(k => { vm.presence[k] = 'none'; });
    (st.sources || []).forEach(x => { if (KINDS.indexOf(x.source) !== -1) vm.presence[x.source] = x.state; });
    vm.coverageMissing = missingKinds(vm.presence);
    vm.list = st.servers.map(card => apiServer(card, b.details && b.details[card.id], b.metrics && b.metrics[card.id], b.admin && b.admin.details && b.admin.details[card.id], ctx));
    vm.eventsList = ((b.events && b.events.items) || []).map(e => {
      const kind = String(e.title_key || '').replace(/^events\./, '');
      const sev = e.kind === 'note' ? 'note' : kind === 'recovered' ? 'ok' : (e.severity === 'critical' || e.severity === 'warning') ? 'problem' : 'info';
      const p = e.params || {};
      return { kind, sev, server: e.server_id || null, at: new Date(e.occurred_at), text: p.text === undefined ? null : p.text, source: p.source || null, state: p.state || null };
    });
    if (b.admin) {
      const ov = b.admin.overview || { attention_items: [], doctor: { result: 'ok', items: [] }, next_command: null };
      const probes = {};
      (b.admin.probes || []).forEach(p => {
        if (p.status === 'revoked') return;
        const e = { id: p.id, state: p.status === 'active' ? 'ok' : 'unknown', enrolled: true, lastMin: minutesSince(p.last_seen_at, now) };
        if (p.status === 'stopped') e.session = 'stopped';
        if (p.route_verified !== null && p.route_verified !== undefined) e.route = p.route_verified;
        if (p.queued_reports !== null && p.queued_reports !== undefined) e.queue = p.queued_reports;
        if (p.agent_version) e.version = p.agent_version;
        if (e.lastMin === null) delete e.lastMin;
        probes[p.kind] = e;
      });
      ['pc', 'android', 'abroad'].forEach(k => { if (!probes[k]) probes[k] = { state: 'unknown', enrolled: false }; });
      const services = {}; const checks = (b.admin.readiness && b.admin.readiness.checks) || {};
      Object.keys(checks).forEach(n => { services[n] = checks[n].ok ? 'ok' : (checks[n].age_seconds === null || checks[n].age_seconds === undefined ? 'unknown' : 'fail'); });
      vm.adminData = {
        attention: (ov.attention_items || []).map(a => ({ sev: a.severity, server: a.server_id || null, text: a.message, code: a.code })),
        probes, services,
        doctor: { result: ov.doctor.result, items: (ov.doctor.items || []).map(it => ({ name: it.check, state: it.state, next: it.next, cmd: it.command || null })) },
        enrollCode: null, nextCommand: ov.next_command || null
      };
    }
    return vm;
  }
  // an unreachable API: last good model with the offline flag, or an empty offline shell
  function offline(lastGood, ctx) {
    const base = lastGood ? Object.assign({}, lastGood) : { id: 'offline', source: 'api', overall: 'unknown', freshnessMin: null, recommended: null, empty: false, demo: false, since: null, noteMax: NOTE_MAX, note: null, list: [], eventsList: [], adminData: null, presence: { pc: 'none', mobile: 'none', abroad: 'none' }, coverageMissing: null };
    base.api = 'offline'; base.loading = false; base.code = null; base.lastKnownTime = ctx.lastGoodAt ? fmtTime(ctx.lastGoodAt) : '—';
    return base;
  }
  const authFailed = code => ({ id: 'auth', source: 'api', overall: 'unknown', freshnessMin: null, recommended: null, empty: false, loading: false, api: 'auth', code: code || 'MEMBERSHIP_REQUIRED', demo: false, lastKnownTime: null, since: null, noteMax: NOTE_MAX, note: null, list: [], eventsList: [], adminData: null, presence: { pc: 'none', mobile: 'none', abroad: 'none' }, coverageMissing: null });
  const loading = () => ({ id: 'loading', source: 'api', overall: 'unknown', freshnessMin: null, recommended: null, empty: false, loading: true, api: null, code: null, demo: false, lastKnownTime: null, since: null, noteMax: NOTE_MAX, note: null, list: [], eventsList: [], adminData: null, presence: { pc: 'none', mobile: 'none', abroad: 'none' }, coverageMissing: null });

  return { KINDS, NOTE_MAX, fromFixtures, fromApi, offline, authFailed, loading, fmtPct, fmtTime, minutesSince, pick };
})();
