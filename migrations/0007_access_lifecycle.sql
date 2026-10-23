CREATE TABLE access_lifecycle_jobs (
  id TEXT PRIMARY KEY,
  member_id TEXT NOT NULL REFERENCES members(id),
  kind TEXT NOT NULL CHECK (kind IN ('revoke_all')),
  due_at TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','running','completed','failed','cancelled')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_one_pending_lifecycle_job
  ON access_lifecycle_jobs(member_id, kind) WHERE state IN ('pending','running');
CREATE INDEX idx_lifecycle_jobs_due ON access_lifecycle_jobs(state, due_at);
