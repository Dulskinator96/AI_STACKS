-- WON/NEXUS Supabase schema
-- Paste this entire file into: Supabase Dashboard → SQL Editor → New Query → Run

CREATE TABLE IF NOT EXISTS entries (
  id        bigserial PRIMARY KEY,
  timestamp timestamptz DEFAULT now(),
  session   text,
  mode      text,
  content   text,
  score     real,
  tags      text
);

CREATE TABLE IF NOT EXISTS sessions (
  id     text PRIMARY KEY,
  opened timestamptz,
  closed timestamptz,
  log    text,
  brief  text
);

CREATE TABLE IF NOT EXISTS snapshots (
  id        bigserial PRIMARY KEY,
  timestamp timestamptz DEFAULT now(),
  data      text
);

CREATE TABLE IF NOT EXISTS content_hashes (
  hash       text PRIMARY KEY,
  first_seen timestamptz DEFAULT now(),
  source     text,
  count      integer DEFAULT 1
);

CREATE TABLE IF NOT EXISTS captures (
  hash         text PRIMARY KEY,
  ts           timestamptz DEFAULT now(),
  source       text,
  content_type text,
  content      text,
  char_count   integer,
  compressed   boolean DEFAULT false,
  indexed      boolean DEFAULT false
);

-- RLS: block all public/anon access; service_role key bypasses RLS automatically
ALTER TABLE entries        ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots      ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_hashes ENABLE ROW LEVEL SECURITY;
ALTER TABLE captures       ENABLE ROW LEVEL SECURITY;

-- Performance indexes
CREATE INDEX IF NOT EXISTS entries_timestamp_idx ON entries (timestamp DESC);
CREATE INDEX IF NOT EXISTS entries_mode_idx      ON entries (mode);
CREATE INDEX IF NOT EXISTS entries_session_idx   ON entries (session);
CREATE INDEX IF NOT EXISTS captures_ts_idx       ON captures (ts DESC);
CREATE INDEX IF NOT EXISTS sessions_opened_idx   ON sessions (opened DESC);
