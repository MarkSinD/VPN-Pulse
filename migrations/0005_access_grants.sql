CREATE TABLE access_requests (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(id),
  state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'denied', 'cancelled')),
  message TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT,
  decided_by_hash BLOB
);
CREATE UNIQUE INDEX idx_one_pending_access_request
  ON access_requests(member_id) WHERE state = 'pending';

CREATE TABLE access_grants (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(id),
  server_id TEXT NOT NULL REFERENCES servers(id),
  state TEXT NOT NULL CHECK (state IN ('active', 'suspended', 'revoked', 'expired')),
  reason TEXT NOT NULL,
  valid_until TEXT,
  granted_by_hash BLOB NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE UNIQUE INDEX idx_one_live_grant
  ON access_grants(member_id, server_id) WHERE state IN ('active', 'suspended');
CREATE INDEX idx_access_grants_member ON access_grants(member_id, state);
CREATE INDEX idx_access_grants_server ON access_grants(server_id, state);
