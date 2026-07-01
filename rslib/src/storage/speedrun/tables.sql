CREATE TABLE IF NOT EXISTS concept (
  id integer NOT NULL PRIMARY KEY,
  outline_id text NOT NULL,
  section text NOT NULL,
  title text NOT NULL,
  exam_weight real NOT NULL,
  usn integer NOT NULL DEFAULT 0,
  mtime_secs integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS speedrun_item (
  id integer NOT NULL PRIMARY KEY,
  concept_id integer NOT NULL,
  LEVEL integer NOT NULL,
  difficulty real NOT NULL,
  source_ref text NOT NULL,
  ai_generated integer NOT NULL DEFAULT 0,
  stem text NOT NULL DEFAULT '',
  choices text NOT NULL DEFAULT '[]',
  answer integer NOT NULL DEFAULT 0,
  explanation text NOT NULL DEFAULT '',
  usn integer NOT NULL DEFAULT 0,
  mtime_secs integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transfer_review (
  id integer NOT NULL PRIMARY KEY,
  -- Globally-unique identity used for sync. Local `id` is device-local; two
  -- devices may both mint id=1, but their guids differ, so the merge dedupes
  -- on guid and replays the union to converge.
  guid text NOT NULL DEFAULT '',
  item_id integer NOT NULL,
  concept_id integer NOT NULL,
  correct integer NOT NULL,
  latency_ms integer NOT NULL DEFAULT 0,
  ts integer NOT NULL,
  -- Item difficulty (IRT b) at answer time, carried in the log so replay is
  -- self-contained and converges across devices (see speedrun/sync.rs).
  difficulty real NOT NULL DEFAULT 0.5,
  usn integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_transfer_review_concept ON transfer_review (concept_id);
-- NOTE: the index on `guid` is created in ensure_speedrun_tables() *after* the
-- defensive ALTER that adds the column, because a collection from a pre-guid
-- build reaches this batch without a `guid` column and `CREATE INDEX` on a
-- missing column aborts the whole batch (IF NOT EXISTS only suppresses
-- "index already exists").
CREATE TABLE IF NOT EXISTS concept_state (
  concept_id integer NOT NULL PRIMARY KEY,
  theta real NOT NULL DEFAULT 0,
  n_obs integer NOT NULL DEFAULT 0,
  r_cache real NOT NULL DEFAULT 0,
  last_practiced integer NOT NULL DEFAULT 0,
  usn integer NOT NULL DEFAULT 0,
  mtime_secs integer NOT NULL DEFAULT 0
);