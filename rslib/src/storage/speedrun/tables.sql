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
  level integer NOT NULL,
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
  usn integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transfer_review_concept ON transfer_review (concept_id);
CREATE INDEX IF NOT EXISTS idx_transfer_review_guid ON transfer_review (guid);

CREATE TABLE IF NOT EXISTS concept_state (
  concept_id integer NOT NULL PRIMARY KEY,
  theta real NOT NULL DEFAULT 0,
  n_obs integer NOT NULL DEFAULT 0,
  r_cache real NOT NULL DEFAULT 0,
  last_practiced integer NOT NULL DEFAULT 0,
  usn integer NOT NULL DEFAULT 0,
  mtime_secs integer NOT NULL DEFAULT 0
);
