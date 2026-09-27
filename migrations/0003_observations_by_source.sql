-- The read model needs the newest observation per source for a server. Grouping over a server's
-- whole retention window cost 464 ms on a live database (32k rows per server); with this index the
-- same answer is five index seeks.
CREATE INDEX IF NOT EXISTS idx_observations_server_source_time
  ON observations(server_id, source_kind, observed_at DESC);
