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
        self.db
            .prepare_cached(
                "INSERT OR REPLACE INTO speedrun_item
                   (id, concept_id, level, difficulty, source_ref, ai_generated, usn, mtime_secs)
                 VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
            )?
            .execute(params![
                i.id,
                i.concept_id,
                i.level,
                i.difficulty,
                i.source_ref,
                i.ai_generated as i64,
            ])?;
        Ok(())
    }

    pub(crate) fn get_item(&self, id: i64) -> Result<Option<Item>> {
        self.db
            .prepare_cached(
                "SELECT id, concept_id, level, difficulty, source_ref, ai_generated
                 FROM speedrun_item WHERE id = ?",
            )?
            .query_and_then([id], row_to_item)?
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
                   (id, item_id, concept_id, correct, latency_ms, ts, usn)
                 VALUES (?, ?, ?, ?, ?, ?, 0)",
            )?
            .execute(params![
                r.id,
                r.item_id,
                r.concept_id,
                r.correct as i64,
                r.latency_ms,
                r.ts,
            ])?;
        Ok(())
    }

    pub(crate) fn remove_transfer_review(&self, id: i64) -> Result<()> {
        self.db
            .prepare_cached("DELETE FROM transfer_review WHERE id = ?")?
            .execute([id])?;
        Ok(())
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
    Ok(Item {
        id: row.get(0)?,
        concept_id: row.get(1)?,
        level: row.get(2)?,
        difficulty: row.get(3)?,
        source_ref: row.get(4)?,
        ai_generated: row.get::<_, i64>(5)? != 0,
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
