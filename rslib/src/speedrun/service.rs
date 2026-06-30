// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use anki_proto::speedrun as pb;

use crate::ops::Op;
use crate::prelude::*;
use crate::speedrun::concept_transfer;
use crate::speedrun::elo_update;
use crate::speedrun::gap;
use crate::speedrun::Concept;
use crate::speedrun::ConceptState;
use crate::speedrun::Item;
use crate::speedrun::TransferReview;
use crate::speedrun::ELO_K;
use crate::timestamp::TimestampMillis;
use crate::timestamp::TimestampSecs;

impl crate::services::SpeedrunService for Collection {
    fn upsert_concept(&mut self, input: pb::Concept) -> Result<anki_proto::collection::OpChanges> {
        self.storage.ensure_speedrun_tables()?;
        let concept = Concept {
            id: input.id,
            outline_id: input.outline_id,
            section: input.section,
            title: input.title,
            exam_weight: input.exam_weight,
        };
        self.transact(Op::Custom("Upsert concept".into()), |col| {
            col.storage.upsert_concept(&concept)
        })
        .map(Into::into)
    }

    fn upsert_item(&mut self, input: pb::Item) -> Result<anki_proto::collection::OpChanges> {
        self.storage.ensure_speedrun_tables()?;
        let item = Item {
            id: input.id,
            concept_id: input.concept_id,
            level: input.level,
            difficulty: input.difficulty,
            source_ref: input.source_ref,
            ai_generated: input.ai_generated,
        };
        self.transact(Op::Custom("Upsert transfer item".into()), |col| {
            col.storage.upsert_item(&item)
        })
        .map(Into::into)
    }

    fn record_transfer_review(
        &mut self,
        input: pb::RecordTransferReviewRequest,
    ) -> Result<anki_proto::collection::OpChanges> {
        self.storage.ensure_speedrun_tables()?;
        self.transact(Op::Custom("Record transfer review".into()), |col| {
            col.record_transfer_review_inner(
                input.item_id,
                input.concept_id,
                input.correct,
                input.latency_ms as i64,
            )
        })
        .map(Into::into)
    }

    fn mastery_query(&mut self, input: pb::MasteryQueryRequest) -> Result<pb::MasteryQueryResponse> {
        self.storage.ensure_speedrun_tables()?;
        self.mastery_query_inner(input.concept_ids)
    }

    fn transfer_gap_queue(
        &mut self,
        input: pb::TransferGapQueueRequest,
    ) -> Result<pb::TransferGapQueueResponse> {
        self.storage.ensure_speedrun_tables()?;
        self.transfer_gap_queue_inner(input.limit)
    }
}

impl Collection {
    fn record_transfer_review_inner(
        &mut self,
        item_id: i64,
        concept_id: i64,
        correct: bool,
        latency_ms: i64,
    ) -> Result<()> {
        let difficulty = self
            .storage
            .get_item(item_id)?
            .map(|i| i.difficulty)
            .unwrap_or(crate::speedrun::REPRESENTATIVE_DIFFICULTY);

        let previous = self.storage.get_concept_state(concept_id)?;
        let theta0 = previous.as_ref().map(|s| s.theta).unwrap_or(0.0);
        let new_state = ConceptState {
            concept_id,
            theta: elo_update(theta0, difficulty, correct, ELO_K),
            n_obs: previous.as_ref().map(|s| s.n_obs).unwrap_or(0) + 1,
            r_cache: previous.as_ref().map(|s| s.r_cache).unwrap_or(0.0),
            last_practiced: TimestampSecs::now().0,
        };
        // Saved (and applied) before the review insert so that undo replays in
        // the correct reverse order: remove review, then restore state.
        self.update_concept_state_undoable(new_state, previous)?;

        let review = TransferReview {
            id: self.storage.next_transfer_review_id()?,
            item_id,
            concept_id,
            correct,
            latency_ms,
            ts: TimestampMillis::now().0,
        };
        self.add_transfer_review_undoable(review)?;
        Ok(())
    }

    fn mastery_query_inner(&mut self, concept_ids: Vec<i64>) -> Result<pb::MasteryQueryResponse> {
        let all = self.storage.all_concepts()?;
        let target_ids: Vec<i64> = if concept_ids.is_empty() {
            all.iter().map(|c| c.id).collect()
        } else {
            concept_ids
        };

        let mut entries = Vec::with_capacity(target_ids.len());
        for id in target_ids {
            let state = self.storage.get_concept_state(id)?;
            let theta = state.as_ref().map(|s| s.theta).unwrap_or(0.0);
            let recall = state.as_ref().map(|s| s.r_cache).unwrap_or(0.0);
            let n_obs = state.as_ref().map(|s| s.n_obs).unwrap_or(0) as u32;
            let transfer = concept_transfer(theta);
            entries.push(pb::ConceptMastery {
                concept_id: id,
                recall,
                transfer,
                gap: gap(recall, transfer),
                n_transfer_obs: n_obs,
                theta,
            });
        }

        // Coverage: weighted fraction of the exam with at least one observation.
        let total_weight: f64 = all.iter().map(|c| c.exam_weight).sum();
        let mut covered_weight = 0.0;
        for c in &all {
            if self.storage.transfer_obs_count(c.id)? > 0 {
                covered_weight += c.exam_weight;
            }
        }
        let coverage = if total_weight > 0.0 {
            covered_weight / total_weight
        } else {
            0.0
        };

        Ok(pb::MasteryQueryResponse { entries, coverage })
    }

    fn transfer_gap_queue_inner(&mut self, limit: u32) -> Result<pb::TransferGapQueueResponse> {
        let concepts = self.storage.all_concepts()?;
        let mut scored: Vec<(f64, i64)> = Vec::with_capacity(concepts.len());
        for c in &concepts {
            let state = self.storage.get_concept_state(c.id)?;
            let theta = state.as_ref().map(|s| s.theta).unwrap_or(0.0);
            let recall = state.as_ref().map(|s| s.r_cache).unwrap_or(0.0);
            let g = gap(recall, concept_transfer(theta));
            scored.push((c.exam_weight * g, c.id));
        }
        // Highest weighted gap first.
        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut ids: Vec<i64> = scored.into_iter().map(|(_, id)| id).collect();
        if limit > 0 && (limit as usize) < ids.len() {
            ids.truncate(limit as usize);
        }
        Ok(pb::TransferGapQueueResponse { concept_ids: ids })
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::collection::CollectionBuilder;
    use crate::error::Result;
    use crate::services::SpeedrunService;

    fn open_col() -> Collection {
        CollectionBuilder::default().build().unwrap()
    }

    fn add_concept(col: &mut Collection, id: i64, weight: f64) {
        let _ = SpeedrunService::upsert_concept(
            col,
            pb::Concept {
                id,
                outline_id: format!("C{id}"),
                section: "bb".into(),
                title: "t".into(),
                exam_weight: weight,
            },
        )
        .unwrap();
    }

    fn add_item(col: &mut Collection, id: i64, concept_id: i64, difficulty: f64) {
        let _ = SpeedrunService::upsert_item(
            col,
            pb::Item {
                id,
                concept_id,
                level: 3,
                difficulty,
                source_ref: "seed".into(),
                ai_generated: false,
            },
        )
        .unwrap();
    }

    #[test]
    fn review_updates_mastery_and_undo_restores_it() -> Result<()> {
        let mut col = open_col();
        add_concept(&mut col, 1, 0.5);
        add_item(&mut col, 10, 1, 0.0);

        // Baseline: no observations, prior theta == 0.
        let before = SpeedrunService::mastery_query(
            &mut col,
            pb::MasteryQueryRequest {
                concept_ids: vec![1],
            },
        )?;
        assert_eq!(before.entries[0].n_transfer_obs, 0);
        assert!((before.entries[0].theta - 0.0).abs() < 1e-9);

        // A correct answer should raise theta and the observation count.
        let _ = SpeedrunService::record_transfer_review(
            &mut col,
            pb::RecordTransferReviewRequest {
                item_id: 10,
                concept_id: 1,
                correct: true,
                latency_ms: 4200,
            },
        )?;
        let after = SpeedrunService::mastery_query(
            &mut col,
            pb::MasteryQueryRequest {
                concept_ids: vec![1],
            },
        )?;
        assert_eq!(after.entries[0].n_transfer_obs, 1);
        assert!(after.entries[0].theta > 0.0);
        assert!(after.entries[0].transfer > before.entries[0].transfer);
        assert!(after.coverage > 0.0);

        // Undo must fully restore the prior state and drop the review row.
        col.undo()?;
        let undone = SpeedrunService::mastery_query(
            &mut col,
            pb::MasteryQueryRequest {
                concept_ids: vec![1],
            },
        )?;
        assert_eq!(undone.entries[0].n_transfer_obs, 0);
        assert!((undone.entries[0].theta - 0.0).abs() < 1e-9);
        assert!((undone.coverage - 0.0).abs() < 1e-9);
        Ok(())
    }

    #[test]
    fn queue_orders_by_weighted_gap() -> Result<()> {
        let mut col = open_col();
        // Two concepts; give concept 2 a higher recall so it has a larger gap.
        add_concept(&mut col, 1, 0.5);
        add_concept(&mut col, 2, 0.5);
        col.storage.upsert_concept_state(&ConceptState {
            concept_id: 2,
            theta: -1.0,
            n_obs: 1,
            r_cache: 0.95,
            last_practiced: 0,
        })?;
        let queue = SpeedrunService::transfer_gap_queue(
            &mut col,
            pb::TransferGapQueueRequest { limit: 0 },
        )?;
        assert_eq!(queue.concept_ids.first(), Some(&2));
        Ok(())
    }
}
