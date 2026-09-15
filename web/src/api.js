/* VPN Pulse — API client for contracts/openapi.yaml (v1.3).
   One fetch wrapper: same-origin cookies, Accept-Language, problem+json errors.
   `scenario` is a dev-server affordance (?scenario=…); a real deployment ignores it. */
window.VPNPulseApi = function (opts) {
  'use strict';
  const base = (opts.base || '/api/v1').replace(/\/$/, '');
  function ApiError(status, code, message) { this.status = status; this.code = code || 'HTTP_ERROR'; this.message = message || this.code; }
  ApiError.prototype = Object.create(Error.prototype);

  function url(path, params) {
    const p = new URLSearchParams();
    Object.keys(params || {}).forEach(k => { if (params[k] !== undefined && params[k] !== null) p.set(k, String(params[k])); });
    const sc = opts.scenario && opts.scenario(); if (sc) p.set('scenario', sc);
    const qs = p.toString();
    return base + path + (qs ? (path.indexOf('?') === -1 ? '?' : '&') + qs : '');
  }
  async function call(method, path, params, body) {
    const headers = { 'Accept': 'application/json', 'Accept-Language': opts.lang() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let res;
    try {
      res = await fetch(url(path, params), { method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (e) { throw new ApiError(0, 'NETWORK', String(e && e.message || e)); }
    if (res.status === 204) return null;
    let data = null;
    const ct = res.headers.get('content-type') || '';
    if (ct.indexOf('json') !== -1) { try { data = await res.json(); } catch (e) { data = null; } }
    if (!res.ok) throw new ApiError(res.status, data && data.code, data && data.title);
    return data;
  }
  return {
    ApiError,
    // sessions
    session: initData => call('POST', '/sessions', null, { init_data: initData }),
    devSession: role => call('POST', '/dev/session', { role }),
    me: () => call('GET', '/sessions/current'),
    logout: () => call('DELETE', '/sessions/current'),
    // member reads
    status: () => call('GET', '/status'),
    server: id => call('GET', '/servers/' + encodeURIComponent(id)),
    metrics: (id, period) => call('GET', '/servers/' + encodeURIComponent(id) + '/metrics', { period }),
    events: (filter, limit, cursor) => call('GET', '/events', { filter, limit, cursor }),
    help: () => call('GET', '/help'),
    ready: () => call('GET', '/health/ready'),
    // admin
    adminServer: id => call('GET', '/admin/servers/' + encodeURIComponent(id)),
    adminProbes: () => call('GET', '/admin/probes'),
    adminOverview: () => call('GET', '/admin/overview'),
    createEnrollment: (kind, capabilities) => call('POST', '/admin/probe-enrollments', null, { kind, capabilities }),
    revokeProbe: id => call('POST', '/admin/probes/' + encodeURIComponent(id) + '/revoke'),
    putNote: (text, expiresAt) => call('PUT', '/admin/note', null, { text, expires_at: expiresAt || null }),
    deleteNote: () => call('DELETE', '/admin/note'),
    // analytics
    analytics: events => call('POST', '/analytics/events:batch', null, { events })
  };
};
