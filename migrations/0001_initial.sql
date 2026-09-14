CREATE TABLE servers (
  id TEXT PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  display_order INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE protocols (
  id TEXT PRIMARY KEY,
  server_id TEXT NOT NULL REFERENCES servers(id),
  kind TEXT NOT NULL,
  label_key TEXT NOT NULL,
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  coverage_state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (server_id, kind)
);

CREATE TABLE probes (
  id TEXT PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  token_hash BLOB NOT NULL,
  token_prefix TEXT NOT NULL,
  schema_major INTEGER NOT NULL,
  agent_version TEXT NOT NULL,
  enrolled_at TEXT NOT NULL,
  last_seen_at TEXT,
  revoked_at TEXT
);

CREATE TABLE collection_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  result TEXT,
  trace_id TEXT NOT NULL,
  duration_ms INTEGER,
  error_code TEXT
);

CREATE TABLE probe_reports (
  report_id TEXT PRIMARY KEY,
  probe_id TEXT NOT NULL REFERENCES probes(id),
  schema_version INTEGER NOT NULL,
  agent_version TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  network_type TEXT NOT NULL,
  ip_family TEXT NOT NULL,
  route_verified INTEGER NOT NULL CHECK (route_verified IN (0, 1)),
  payload_hash BLOB NOT NULL,
  result TEXT NOT NULL,
  not_run_reason TEXT
);

CREATE TABLE observations (
  id TEXT PRIMARY KEY,
  server_id TEXT NOT NULL REFERENCES servers(id),
  protocol_id TEXT REFERENCES protocols(id),
  source_kind TEXT NOT NULL,
  network_scope TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  result TEXT NOT NULL,
  fresh_until TEXT NOT NULL,
  confidence TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  error_code TEXT,
  collection_run_id TEXT REFERENCES collection_runs(id),
  probe_report_id TEXT REFERENCES probe_reports(report_id)
);
CREATE INDEX idx_observations_server_time ON observations(server_id, observed_at DESC);
CREATE INDEX idx_observations_source_time ON observations(source_kind, observed_at DESC);
CREATE INDEX idx_observations_protocol_time ON observations(protocol_id, observed_at DESC);

CREATE TABLE metric_hourly (
  bucket_at TEXT NOT NULL,
  server_id TEXT NOT NULL REFERENCES servers(id),
  protocol_id TEXT REFERENCES protocols(id),
  metric TEXT NOT NULL,
  min REAL,
  max REAL,
  avg REAL,
  samples INTEGER NOT NULL,
  unknown_seconds INTEGER NOT NULL,
  PRIMARY KEY (bucket_at, server_id, protocol_id, metric)
);

CREATE TABLE state_snapshots (
  scope_key TEXT PRIMARY KEY,
  server_id TEXT REFERENCES servers(id),
  protocol_id TEXT REFERENCES protocols(id),
  network_scope TEXT NOT NULL,
  state TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  confidence TEXT NOT NULL,
  observed_at TEXT,
  evaluated_at TEXT NOT NULL,
  fresh_until TEXT,
  evidence_json TEXT NOT NULL,
  version INTEGER NOT NULL
);

CREATE TABLE state_transitions (
  id TEXT PRIMARY KEY,
  scope_key TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  confirmed_at TEXT NOT NULL,
  closed_at TEXT,
  dedupe_key TEXT NOT NULL UNIQUE,
  evidence_json TEXT NOT NULL
);

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  server_id TEXT REFERENCES servers(id),
  transition_id TEXT REFERENCES state_transitions(id),
  title_key TEXT NOT NULL,
  params_json TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  visible_to TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_events_time ON events(occurred_at DESC);

CREATE TABLE admin_notes (
  id TEXT PRIMARY KEY,
  server_id TEXT REFERENCES servers(id),
  text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 500),
  status TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  expires_at TEXT,
  created_by_role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE notification_queue (
  id TEXT PRIMARY KEY,
  transition_id TEXT NOT NULL REFERENCES state_transitions(id),
  destination_kind TEXT NOT NULL,
  template_key TEXT NOT NULL,
  params_json TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  locked_until TEXT,
  sent_at TEXT,
  last_error_code TEXT,
  dedupe_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE web_sessions (
  id_hash BLOB PRIMARY KEY,
  role TEXT NOT NULL,
  telegram_user_hash BLOB NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_membership_check_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE probe_enrollments (
  code_hash BLOB PRIMARY KEY,
  kind TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_by_hash BLOB NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE product_events (
  event_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  session_id TEXT NOT NULL,
  surface TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  properties_json TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX idx_product_events_expiry ON product_events(expires_at);

CREATE TABLE audit_entries (
  id TEXT PRIMARY KEY,
  actor_hash BLOB NOT NULL,
  actor_role TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_public_id TEXT NOT NULL,
  result TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  details_json TEXT NOT NULL
);
CREATE INDEX idx_audit_time ON audit_entries(occurred_at DESC);

