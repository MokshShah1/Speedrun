// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Append-only sync for the transfer-review log.
//!
//! Anki's own sync moves the standard collection objects (cards, notes,
//! revlog, ...). The Speedrun tables are not part of that schema, so the
//! transfer-review log is synced separately here. The design relies on one
//! fact: a concept's learned ability `theta` is **derived** from its reviews.
//! So we never sync `theta`; we sync the append-only review log and then
//! **replay** it.
//!
//! * Identity is the per-review `guid` (globally unique), not the device-local
//!   `id`. Merging two logs is a set union on guid, so it is idempotent: the
//!   classic "10 reviews here + 10 there = 20 after sync, and 20 again if you
//!   sync twice."
//! * After a merge each affected concept is recomputed by replaying its reviews
//!   in the canonical `(ts, guid)` order. Both devices hold the same union and
//!   sort it identically, so they converge to exactly the same `theta` even
//!   though Elo updates are order-dependent. This is the conflict rule: there
//!   are no conflicts, only a deterministic replay of a shared, ordered log.

use crate::ops::Op;
use crate::prelude::*;
use crate::speedrun::elo_update;
use crate::speedrun::ConceptState;
use crate::speedrun::TransferReview;
use crate::speedrun::ELO_K;

/// Outcome of importing a remote review log.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ImportStats {
    /// Reviews that were new on this device and got added.
    pub added: u32,
    /// Total reviews on this device after the merge.
    pub total: u32,
}

impl Collection {
    /// All reviews on this device, in canonical replay order. This is the
    /// payload a peer would import.
    pub(crate) fn export_transfer_log(&mut self) -> Result<Vec<TransferReview>> {
        self.storage.ensure_speedrun_tables()?;
        self.storage.all_transfer_reviews()
    }

    /// Merge a peer's review log into this device, then recompute the affected
    /// concepts. Deduped on `guid`; imported rows get fresh local ids so they
    /// never clash with this device's own `id` sequence.
    pub(crate) fn import_transfer_log(
        &mut self,
        incoming: Vec<TransferReview>,
    ) -> Result<ImportStats> {
        self.storage.ensure_speedrun_tables()?;
        // Mutable so we can also dedupe *within* a single incoming payload: a
        // guid seen earlier in this batch must not be inserted twice (e.g. a
        // caller concatenating several peers' logs), which would double-apply
        // its Elo update and inflate n_obs.
        let mut existing = self.storage.transfer_review_guids()?;
        let mut next_id = self.storage.next_transfer_review_id()?;

        let mut affected: std::collections::BTreeSet<i64> = Default::default();
        let mut added = 0u32;
        self.transact(Op::Custom("Sync transfer log".into()), |col| {
            for r in &incoming {
                if r.guid.is_empty() || existing.contains(&r.guid) {
                    continue;
                }
                let stored = TransferReview {
                    id: next_id,
                    guid: r.guid.clone(),
                    item_id: r.item_id,
                    concept_id: r.concept_id,
                    correct: r.correct,
                    latency_ms: r.latency_ms,
                    ts: r.ts,
                    difficulty: r.difficulty,
                };
                col.storage.add_transfer_review(&stored)?;
                existing.insert(r.guid.clone());
                next_id += 1;
                added += 1;
                affected.insert(r.concept_id);
            }
            for concept_id in &affected {
                col.recompute_concept_state(*concept_id)?;
            }
            Ok(())
        })?;

        let total = self.storage.all_transfer_reviews()?.len() as u32;
        Ok(ImportStats { added, total })
    }

    /// Replay a concept's full review log from the neutral prior in canonical
    /// `(ts, guid)` order. Returns `None` when there are no reviews. This is
    /// the single source of truth for `theta`: both the live record path
    /// and sync derive state from it, so a device's score is identical
    /// before and after a sync (no incremental-vs-replay drift).
    pub(crate) fn replayed_concept_state(
        &mut self,
        concept_id: i64,
    ) -> Result<Option<(f64, i64, i64)>> {
        let reviews = self.storage.transfer_reviews_for_concept(concept_id)?;
        if reviews.is_empty() {
            return Ok(None);
        }
        let mut theta = 0.0;
        let mut last_practiced = 0i64;
        for r in &reviews {
            // Difficulty travels in the record (not a local item-table lookup),
            // so two devices holding the same log replay to exactly the same
            // theta even if one of them lacks the item locally.
            theta = elo_update(theta, r.difficulty, r.correct, ELO_K);
            // ts is milliseconds; concept_state.last_practiced is seconds.
            last_practiced = last_practiced.max(r.ts / 1000);
        }
        Ok(Some((theta, reviews.len() as i64, last_practiced)))
    }

    /// Recompute and persist a concept's state from its log (used after a sync
    /// merge). Removes the state row when the concept has no reviews.
    pub(crate) fn recompute_concept_state(&mut self, concept_id: i64) -> Result<()> {
        match self.replayed_concept_state(concept_id)? {
            None => self.storage.remove_concept_state(concept_id),
            Some((theta, n_obs, last_practiced)) => {
                let previous = self.storage.get_concept_state(concept_id)?;
                let r_cache = previous.as_ref().map(|s| s.r_cache).unwrap_or(0.0);
                self.storage.upsert_concept_state(&ConceptState {
                    concept_id,
                    theta,
                    n_obs,
                    r_cache,
                    last_practiced,
                })
            }
        }
    }
}

#[cfg(test)]
mod test {
    use anki_proto::speedrun as pb;

    use super::*;
    use crate::collection::CollectionBuilder;
    use crate::services::SpeedrunService;

    fn open_col() -> Collection {
        CollectionBuilder::default().build().unwrap()
    }

    fn seed(col: &mut Collection) {
        let _ = SpeedrunService::upsert_concept(
            col,
            pb::Concept {
                id: 1,
                outline_id: "C1".into(),
                section: "bb".into(),
                title: "t".into(),
                exam_weight: 1.0,
            },
        )
        .unwrap();
        let _ = SpeedrunService::upsert_item(
            col,
            pb::Item {
                id: 10,
                concept_id: 1,
                level: 3,
                difficulty: 0.2,
                source_ref: "seed".into(),
                ai_generated: false,
                stem: "stem".into(),
                choices: vec!["a".into(), "b".into()],
                answer: 0,
                explanation: "x".into(),
            },
        )
        .unwrap();
    }

    fn record(col: &mut Collection, correct: bool) {
        let _ = SpeedrunService::record_transfer_review(
            col,
            pb::RecordTransferReviewRequest {
                item_id: 10,
                concept_id: 1,
                correct,
                latency_ms: 1000,
            },
        )
        .unwrap();
    }

    fn theta(col: &mut Collection) -> f64 {
        col.storage
            .get_concept_state(1)
            .unwrap()
            .map(|s| s.theta)
            .unwrap_or(0.0)
    }

    /// 10 reviews on one device + 10 on another -> both hold 20 unique reviews
    /// after a two-way exchange, with identical recomputed ability. Re-syncing
    /// changes nothing (idempotent).
    #[test]
    fn two_devices_merge_to_union_and_converge() -> Result<()> {
        let mut a = open_col();
        let mut b = open_col();
        seed(&mut a);
        seed(&mut b);

        for i in 0..10 {
            record(&mut a, i % 2 == 0); // 5 correct / 5 wrong
            record(&mut b, i % 3 == 0); // a different pattern
        }

        let log_a = a.export_transfer_log()?;
        let log_b = b.export_transfer_log()?;
        assert_eq!(log_a.len(), 10);
        assert_eq!(log_b.len(), 10);

        let into_b = b.import_transfer_log(log_a.clone())?;
        let into_a = a.import_transfer_log(log_b.clone())?;
        assert_eq!(into_a.added, 10);
        assert_eq!(into_b.added, 10);
        assert_eq!(into_a.total, 20);
        assert_eq!(into_b.total, 20);

        // Converged: identical union replayed in identical order.
        assert!((theta(&mut a) - theta(&mut b)).abs() < 1e-12);

        // Idempotent: importing the same logs again adds nothing and does not
        // move theta.
        let theta_before = theta(&mut a);
        let again = a.import_transfer_log(log_b.clone())?;
        assert_eq!(again.added, 0);
        assert_eq!(again.total, 20);
        assert!((theta(&mut a) - theta_before).abs() < 1e-12);
        Ok(())
    }

    /// Replay order is canonical: importing a log in a shuffled order yields
    /// the same ability as the original device, because both sort by (ts,
    /// guid).
    #[test]
    fn replay_is_order_independent_of_arrival() -> Result<()> {
        let mut a = open_col();
        seed(&mut a);
        for i in 0..6 {
            record(&mut a, i % 2 == 0);
        }
        let theta_a = theta(&mut a);
        let mut log = a.export_transfer_log()?;

        let mut b = open_col();
        seed(&mut b);
        // Deliver the same reviews in reverse order; the canonical sort inside
        // the engine must undo that.
        log.reverse();
        let stats = b.import_transfer_log(log)?;
        assert_eq!(stats.added, 6);
        assert!((theta(&mut b) - theta_a).abs() < 1e-12);
        Ok(())
    }

    /// Recompute reproduces the incremental record path for a single device.
    #[test]
    fn recompute_matches_incremental_record() -> Result<()> {
        let mut col = open_col();
        seed(&mut col);
        for i in 0..7 {
            record(&mut col, i % 2 == 1);
        }
        let incremental = theta(&mut col);
        col.recompute_concept_state(1)?;
        assert!((theta(&mut col) - incremental).abs() < 1e-12);

        let state = col.storage.get_concept_state(1)?.unwrap();
        assert_eq!(state.n_obs, 7);
        Ok(())
    }

    /// A single incoming payload that carries the same guid twice (e.g. a
    /// caller concatenating two peers' logs) must still insert it only
    /// once, so the Elo update is applied once and n_obs is not inflated.
    #[test]
    fn duplicate_guids_within_one_import_are_deduped() -> Result<()> {
        let mut a = open_col();
        seed(&mut a);
        let dup = TransferReview {
            id: 0,
            guid: "DUPGUID".into(),
            item_id: 10,
            concept_id: 1,
            correct: true,
            latency_ms: 1000,
            ts: 1000,
            difficulty: 0.2,
        };
        let stats = a.import_transfer_log(vec![dup.clone(), dup])?;
        assert_eq!(stats.added, 1);
        assert_eq!(stats.total, 1);
        assert_eq!(a.storage.get_concept_state(1)?.unwrap().n_obs, 1);
        Ok(())
    }

    /// A device that imports reviews for an item it does NOT have locally still
    /// converges to the authoring device's theta, because the item difficulty
    /// travels in the review record rather than being looked up locally.
    /// (Before this fix the importer fell back to a representative difficulty
    /// and diverged.)
    #[test]
    fn converges_when_item_missing_locally() -> Result<()> {
        let mut a = open_col();
        seed(&mut a); // A has concept 1 and item 10 (difficulty 0.2)
        for i in 0..6 {
            record(&mut a, i % 2 == 0);
        }
        let theta_a = theta(&mut a);
        let log = a.export_transfer_log()?;
        assert!(log.iter().all(|r| (r.difficulty - 0.2).abs() < 1e-9));

        // B has the concept but NOT the item.
        let mut b = open_col();
        let _ = SpeedrunService::upsert_concept(
            &mut b,
            pb::Concept {
                id: 1,
                outline_id: "C1".into(),
                section: "bb".into(),
                title: "t".into(),
                exam_weight: 1.0,
            },
        )
        .unwrap();
        let stats = b.import_transfer_log(log)?;
        assert_eq!(stats.added, 6);
        assert!(
            (theta(&mut b) - theta_a).abs() < 1e-12,
            "diverged: b={} a={}",
            theta(&mut b),
            theta_a
        );
        Ok(())
    }
}
