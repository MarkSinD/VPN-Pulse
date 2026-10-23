CREATE TABLE members (
  id TEXT PRIMARY KEY,
  telegram_id_ciphertext BLOB NOT NULL,
  telegram_user_hash BLOB NOT NULL UNIQUE,
  display_name TEXT,
  username TEXT,
  membership_state TEXT NOT NULL CHECK (membership_state IN ('active', 'left', 'banned', 'unknown')),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

ALTER TABLE web_sessions ADD COLUMN member_id TEXT REFERENCES members(id);
CREATE INDEX idx_web_sessions_member ON web_sessions(member_id, expires_at DESC);

CREATE TABLE membership_events (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(id),
  source TEXT NOT NULL CHECK (source IN ('session', 'chat_member', 'admin_import')),
  previous_state TEXT,
  new_state TEXT NOT NULL CHECK (new_state IN ('active', 'left', 'banned', 'unknown')),
  external_event_id TEXT UNIQUE,
  occurred_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_membership_events_member_time ON membership_events(member_id, occurred_at DESC);
