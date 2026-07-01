// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Persistence for the Speedrun transfer engine.
//!
//! The four tables (`concept`, `speedrun_item`, `transfer_review`,
//! `concept_state`) live in the collection database alongside Anki's own
//! tables, but are created lazily with `CREATE TABLE IF NOT EXISTS` rather than
//! through Anki's versioned schema-upgrade chain. This keeps us out of the
//! download/upgrade/downgrade/export invariants that the core `ver` column
//! guards, so adding the engine cannot corrupt or fail to open an existing
//! collection. Each row carries `usn` so the tables can be wired into sync
//! later (Phase 7) without a migration.

use rusqlite::params;

use super::SqliteStorage;
use crate::error::Result;
use crate::speedrun::Concept;
use crate::speedrun::ConceptState;
use crate::speedrun::Item;
use crate::speedrun::TransferReview;

const CREATE_TABLES: &str = include_str!("tables.sql");

impl SqliteStorage {
    /// Idempotently create the Speedrun tables. Cheap to call on every service
    /// entry point.
    pub(crate) fn ensure_speedrun_tables(&self) -> Result<()> {
        self.db.execute_batch(CREATE_TABLES)?;
        // Defensive migration: a collection created by an earlier build of the
        // engine has `transfer_review` without the sync `guid` column. Add it if
        // missing (SQLite errors with "duplicate column" once it exists, which
        // we ignore), then backfill any blank guids so the sync merge has a
        // unique key for every historical row.
        if self
            .db
            .execute(
                "ALTER TABLE transfer_review ADD COLUMN guid text NOT NULL DEFAULT ''",
                [],
            )
            .is_ok()
        {
            let blanks: Vec<i64> = self
                .db
                .prepare("SELECT id FROM transfer_review WHERE guid = ''")?
                .query_and_then([], |r| Ok(r.get::<_, i64>(0)?))?
                .collect::<Result<_>>()?;
            for id in blanks {
                self.db.execute(
                    "UPDATE transfer_review SET guid = ? WHERE id = ?",
                    params![crate::notes::base91_u64(), id],
                )?;
            }
        }
        // Create the guid index only now that the column is guaranteed to exist
        // (fresh collections have it from CREATE TABLE; older ones just got it
        // from the ALTER above). Creating it inside the CREATE_TABLES batch would
        // fail on a pre-guid collection and abort the migration meant to fix it.
        self.db.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_transfer_review_guid ON transfer_review (guid)",
        )?;
        // Defensive migration for the synced `difficulty` column (added after the
        // original engine). New collections get it from CREATE TABLE; older ones
        // get it here. Backfill historical rows from the local item table so they
        // replay with their real difficulty; rows whose item is gone keep the
        // representative default (0.5).
        if self
            .db
            .execute(
                "ALTER TABLE transfer_review ADD COLUMN difficulty real NOT NULL DEFAULT 0.5",
                [],
            )
            .is_ok()
        {
            self.db.execute(
                "UPDATE transfer_review
                 SET difficulty = (
                     SELECT difficulty FROM speedrun_item
                     WHERE speedrun_item.id = transfer_review.item_id
                 )
                 WHERE item_id IN (SELECT id FROM speedrun_item)",
                [],
            )?;
        }
        Ok(())
    }

    pub(crate) fn upsert_concept(&self, c: &Concept) -> Result<()> {
        self.db
            .prepare_cached(
                "INSERT OR REPLACE INTO concept (id, outline_id, section, title, exam_weight, usn, mtime_secs)
                 VALUES (?, ?, ?, ?, ?, 0, 0)",
            )?
            .execute(params![
                c.id,
                c.outline_id,
                c.section,
                c.title,
                c.exam_weight
            ])?;
        Ok(())
    }

    #[allow(dead_code)] // kept as a storage accessor for future callers
    pub(crate) fn get_concept(&self, id: i64) -> Result<Option<Concept>> {
        self.db
            .prepare_cached(
                "SELECT id, outline_id, section, title, exam_weight FROM concept WHERE id = ?",
            )?
            .query_and_then([id], row_to_concept)?
            .next()
            .transpose()
    }

    pub(crate) fn all_concepts(&self) -> Result<Vec<Concept>> {
        self.db
            .prepare_cached(
                "SELECT id, outline_id, section, title, exam_weight FROM concept ORDER BY id",
            )?
            .query_and_then([], row_to_concept)?
            .collect()
    }

    pub(crate) fn upsert_item(&self, i: &Item) -> Result<()> {
        let choices_json = serde_json::to_string(&i.choices).unwrap_or_else(|_| "[]".into());
        self.db
            .prepare_cached(
                "INSERT OR REPLACE INTO speedrun_item
                   (id, concept_id, level, difficulty, source_ref, ai_generated,
                    stem, choices, answer, explanation, usn, mtime_secs)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            )?
            .execute(params![
                i.id,
                i.concept_id,
                i.level,
                i.difficulty,
                i.source_ref,
                i.ai_generated as i64,
                i.stem,
                choices_json,
                i.answer,
                i.explanation,
            ])?;
        Ok(())
    }

    #[allow(dead_code)] // kept as a storage accessor for future callers
    pub(crate) fn get_item(&self, id: i64) -> Result<Option<Item>> {
        self.db
            .prepare_cached(
                "SELECT id, concept_id, level, difficulty, source_ref, ai_generated,
                        stem, choices, answer, explanation
                 FROM speedrun_item WHERE id = ?",
            )?
            .query_and_then([id], row_to_item)?
            .next()
            .transpose()
    }

    /// The lowest-ladder-level item for a concept (the rung to teach next).
    pub(crate) fn lowest_level_item(&self, concept_id: i64) -> Result<Option<Item>> {
        self.db
            .prepare_cached(
                "SELECT id, concept_id, level, difficulty, source_ref, ai_generated,
                        stem, choices, answer, explanation
                 FROM speedrun_item WHERE concept_id = ? ORDER BY level, id LIMIT 1",
            )?
            .query_and_then([concept_id], row_to_item)?
            .next()
            .transpose()
    }

    /// Smallest unused positive id for a new transfer review.
    pub(crate) fn next_transfer_review_id(&self) -> Result<i64> {
        Ok(self
            .db
            .prepare_cached("SELECT COALESCE(MAX(id), 0) + 1 FROM transfer_review")?
            .query_row([], |r| r.get(0))?)
    }

    pub(crate) fn add_transfer_review(&self, r: &TransferReview) -> Result<()> {
        self.db
            .prepare_cached(
                "INSERT OR REPLACE INTO transfer_review
                   (id, guid, item_id, concept_id, correct, latency_ms, ts, difficulty, usn)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            )?
            .execute(params![
                r.id,
                r.guid,
                r.item_id,
                r.concept_id,
                r.correct as i64,
                r.latency_ms,
                r.ts,
                r.difficulty,
            ])?;
        Ok(())
    }

    pub(crate) fn remove_transfer_review(&self, id: i64) -> Result<()> {
        self.db
            .prepare_cached("DELETE FROM transfer_review WHERE id = ?")?
            .execute([id])?;
        Ok(())
    }

    /// The full review log, ordered canonically by `(ts, guid)` so that any two
    /// devices holding the same set of reviews replay them in the same order.
    pub(crate) fn all_transfer_reviews(&self) -> Result<Vec<TransferReview>> {
        self.db
            .prepare_cached(
                "SELECT id, guid, item_id, concept_id, correct, latency_ms, ts, difficulty
                 FROM transfer_review ORDER BY ts, guid",
            )?
            .query_and_then([], row_to_transfer_review)?
            .collect()
    }

    /// Reviews for one concept in canonical replay order.
    pub(crate) fn transfer_reviews_for_concept(
        &self,
        concept_id: i64,
    ) -> Result<Vec<TransferReview>> {
        self.db
            .prepare_cached(
                "SELECT id, guid, item_id, concept_id, correct, latency_ms, ts, difficulty
                 FROM transfer_review WHERE concept_id = ? ORDER BY ts, guid",
            )?
            .query_and_then([concept_id], row_to_transfer_review)?
            .collect()
    }

    /// Set of guids already present, used to dedupe an incoming sync log.
    pub(crate) fn transfer_review_guids(&self) -> Result<std::collections::HashSet<String>> {
        self.db
            .prepare_cached("SELECT guid FROM transfer_review")?
            .query_and_then([], |r| Ok(r.get::<_, String>(0)?))?
            .collect()
    }

    /// Map of item id -> difficulty, for replaying the log without an N+1
    /// lookup per review.
    pub(crate) fn item_difficulties(&self) -> Result<std::collections::HashMap<i64, f64>> {
        self.db
            .prepare_cached("SELECT id, difficulty FROM speedrun_item")?
            .query_and_then([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, f64>(1)?)))?
            .collect()
    }

    pub(crate) fn transfer_obs_count(&self, concept_id: i64) -> Result<u32> {
        Ok(self
            .db
            .prepare_cached("SELECT COUNT(*) FROM transfer_review WHERE concept_id = ?")?
            .query_row([concept_id], |r| r.get(0))?)
    }

    pub(crate) fn get_concept_state(&self, concept_id: i64) -> Result<Option<ConceptState>> {
        self.db
            .prepare_cached(
                "SELECT concept_id, theta, n_obs, r_cache, last_practiced
                 FROM concept_state WHERE concept_id = ?",
            )?
            .query_and_then([concept_id], row_to_concept_state)?
            .next()
            .transpose()
    }

    pub(crate) fn upsert_concept_state(&self, s: &ConceptState) -> Result<()> {
        self.db
            .prepare_cached(
                "INSERT OR REPLACE INTO concept_state
                   (concept_id, theta, n_obs, r_cache, last_practiced, usn, mtime_secs)
                 VALUES (?, ?, ?, ?, ?, 0, 0)",
            )?
            .execute(params![
                s.concept_id,
                s.theta,
                s.n_obs,
                s.r_cache,
                s.last_practiced,
            ])?;
        Ok(())
    }

    pub(crate) fn remove_concept_state(&self, concept_id: i64) -> Result<()> {
        self.db
            .prepare_cached("DELETE FROM concept_state WHERE concept_id = ?")?
            .execute([concept_id])?;
        Ok(())
    }
}

fn row_to_concept(row: &rusqlite::Row) -> Result<Concept> {
    Ok(Concept {
        id: row.get(0)?,
        outline_id: row.get(1)?,
        section: row.get(2)?,
        title: row.get(3)?,
        exam_weight: row.get(4)?,
    })
}

fn row_to_item(row: &rusqlite::Row) -> Result<Item> {
    let choices_json: String = row.get(7)?;
    Ok(Item {
        id: row.get(0)?,
        concept_id: row.get(1)?,
        level: row.get(2)?,
        difficulty: row.get(3)?,
        source_ref: row.get(4)?,
        ai_generated: row.get::<_, i64>(5)? != 0,
        stem: row.get(6)?,
        choices: serde_json::from_str(&choices_json).unwrap_or_default(),
        answer: row.get(8)?,
        explanation: row.get(9)?,
    })
}

fn row_to_transfer_review(row: &rusqlite::Row) -> Result<TransferReview> {
    Ok(TransferReview {
        id: row.get(0)?,
        guid: row.get(1)?,
        item_id: row.get(2)?,
        concept_id: row.get(3)?,
        correct: row.get::<_, i64>(4)? != 0,
        latency_ms: row.get(5)?,
        ts: row.get(6)?,
        difficulty: row.get(7)?,
    })
}

fn row_to_concept_state(row: &rusqlite::Row) -> Result<ConceptState> {
    Ok(ConceptState {
        concept_id: row.get(0)?,
        theta: row.get(1)?,
        n_obs: row.get(2)?,
        r_cache: row.get(3)?,
        last_practiced: row.get(4)?,
    })
}
