/* Local WireGuard/X25519 key generation for self-service profiles.
 * Secret bytes stay in this closure and are never written to storage or sent to the API.
 */
(function (root) {
  'use strict';
  const P = (1n << 255n) - 19n;
  const A24 = 121665n;
  const mod = x => ((x % P) + P) % P;
  const pow = (base, exponent) => {
    let out = 1n, value = mod(base), exp = exponent;
    while (exp > 0n) {
      if (exp & 1n) out = mod(out * value);
      value = mod(value * value);
      exp >>= 1n;
    }
    return out;
  };
  const decode = bytes => {
    let value = 0n;
    for (let i = bytes.length - 1; i >= 0; i -= 1) value = (value << 8n) | BigInt(bytes[i]);
    return value;
  };
  const encode = value => {
    const out = new Uint8Array(32);
    let current = mod(value);
    for (let i = 0; i < 32; i += 1) { out[i] = Number(current & 255n); current >>= 8n; }
    return out;
  };
  const cswap = (swap, a, b) => swap ? [b, a] : [a, b];
  function derivePublicKey(input) {
    const scalar = new Uint8Array(input);
    if (scalar.length !== 32) throw new Error('X25519 private key must be 32 bytes');
    scalar[0] &= 248; scalar[31] &= 127; scalar[31] |= 64;
    const k = decode(scalar), x1 = 9n;
    let x2 = 1n, z2 = 0n, x3 = x1, z3 = 1n, swap = 0;
    for (let pos = 254; pos >= 0; pos -= 1) {
      const bit = Number((k >> BigInt(pos)) & 1n);
      swap ^= bit;
      [x2, x3] = cswap(swap, x2, x3); [z2, z3] = cswap(swap, z2, z3);
      swap = bit;
      const a = mod(x2 + z2), aa = mod(a * a), b = mod(x2 - z2), bb = mod(b * b);
      const e = mod(aa - bb), c = mod(x3 + z3), d = mod(x3 - z3);
      const da = mod(d * a), cb = mod(c * b);
      x3 = mod((da + cb) ** 2n); z3 = mod(x1 * ((da - cb) ** 2n));
      x2 = mod(aa * bb); z2 = mod(e * (aa + A24 * e));
    }
    [x2, x3] = cswap(swap, x2, x3); [z2, z3] = cswap(swap, z2, z3);
    scalar.fill(0);
    return encode(x2 * pow(z2, P - 2n));
  }
  const b64 = bytes => btoa(String.fromCharCode(...bytes));
  const clean = (name, value) => {
    if (typeof value !== 'string' || !value || /[\r\n]/.test(value)) throw new Error(`Invalid ${name}`);
    return value;
  };
  function generate() {
    const secret = crypto.getRandomValues(new Uint8Array(32));
    secret[0] &= 248; secret[31] &= 127; secret[31] |= 64;
    const publicBytes = derivePublicKey(secret);
    let destroyed = false;
    return {
      publicKey: b64(publicBytes),
      buildConfig(parameters) {
        if (destroyed) throw new Error('Key material destroyed');
        const lines = ['[Interface]', `PrivateKey = ${b64(secret)}`, `Address = ${clean('address', parameters.address)}`];
        if (Array.isArray(parameters.dns) && parameters.dns.length) {
          lines.push(`DNS = ${parameters.dns.map(value => clean('DNS server', value)).join(', ')}`);
        }
        if (parameters.MTU !== undefined) lines.push(`MTU = ${clean('MTU', String(parameters.MTU))}`);
        for (const key of ['Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4']) {
          if (parameters[key] !== undefined && parameters[key] !== '') lines.push(`${key} = ${clean(key, String(parameters[key]))}`);
        }
        if (parameters.HeaderProtectionKey !== undefined) lines.push(`HeaderProtectionKey = ${clean('header protection key', parameters.HeaderProtectionKey)}`);
        for (const key of ['I1', 'I2', 'I3', 'I4', 'I5', 'ContentPaddingAddition', 'RekeyAfterTime', 'RekeyTimeout', 'RejectAfterTime',
          'KeepaliveTimeout', 'MaxHandshakeAttempts', 'RandomTrailers', 'DisableCookies']) {
          if (parameters[key] !== undefined && parameters[key] !== '') lines.push(`${key} = ${clean(key, String(parameters[key]))}`);
        }
        lines.push('', '[Peer]', `PublicKey = ${clean('server public key', parameters.serverPublicKey)}`,
          `PresharedKey = ${clean('preshared key', parameters.presharedKey)}`,
          `Endpoint = ${clean('endpoint', parameters.endpoint)}`,
          `AllowedIPs = ${clean('allowed IPs', parameters.allowedIPs || '0.0.0.0/0, ::/0')}`,
          `PersistentKeepalive = ${clean('persistent keepalive', String(parameters.persistentKeepalive || 25))}`, '');
        return lines.join('\n');
      },
      destroy() { secret.fill(0); publicBytes.fill(0); destroyed = true; },
    };
  }
  root.VpnPulseAccessKeys = { generate, derivePublicKey };
})(typeof window !== 'undefined' ? window : globalThis);
