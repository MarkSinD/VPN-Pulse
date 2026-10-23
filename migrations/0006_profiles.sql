CREATE TABLE vpn_profiles (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(id),
  server_id TEXT NOT NULL REFERENCES servers(id),
  grant_id TEXT NOT NULL REFERENCES access_grants(id),
  public_key TEXT NOT NULL,
  public_key_fingerprint TEXT NOT NULL,
  address TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('reserved', 'applied', 'delivered', 'connected', 'revoking', 'revoked', 'failed', 'needs_review')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivered_at TEXT,
  first_handshake_at TEXT,
  revoked_at TEXT
);
CREATE UNIQUE INDEX idx_one_live_profile
  ON vpn_profiles(member_id, server_id)
  WHERE state IN ('reserved', 'applied', 'delivered', 'connected', 'revoking', 'needs_review');
CREATE UNIQUE INDEX idx_profile_public_key_live
  ON vpn_profiles(public_key) WHERE state NOT IN ('revoked', 'failed');

CREATE TABLE address_leases (
  server_id TEXT NOT NULL REFERENCES servers(id),
  address TEXT NOT NULL,
  profile_id TEXT REFERENCES vpn_profiles(id),
  state TEXT NOT NULL CHECK (state IN ('leased', 'quarantine')),
  leased_at TEXT NOT NULL,
  released_at TEXT,
  quarantine_until TEXT,
  PRIMARY KEY (server_id, address)
);

CREATE TABLE profile_operations (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  profile_id TEXT NOT NULL REFERENCES vpn_profiles(id),
  operation TEXT NOT NULL CHECK (operation IN ('issue', 'revoke', 'replace')),
  state TEXT NOT NULL CHECK (state IN ('reserved', 'applying', 'applied', 'delivered', 'completed', 'failed', 'needs_review')),
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_profile_operations_profile ON profile_operations(profile_id, created_at DESC);
