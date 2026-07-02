// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use std::collections::HashMap;

use anki_proto::speedrun as pb;

use crate::ops::Op;
use crate::prelude::*;
use crate::speedrun::concept_transfer;
use crate::speedrun::gap;
use crate::speedrun::scale_score;
use crate::speedrun::Concept;
use crate::speedrun::ConceptState;
use crate::speedrun::Item;
use crate::speedrun::TransferReview;
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
            stem: input.stem,
            choices: input.choices,
            answer: input.answer,
            explanation: input.explanation,
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

    fn mastery_query(
        &mut self,
        input: pb::MasteryQueryRequest,
    ) -> Result<pb::MasteryQueryResponse> {
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

    fn readiness_report(&mut self, _input: pb::ReadinessRequest) -> Result<pb::ReadinessResponse> {
        self.storage.ensure_speedrun_tables()?;
        self.readiness_report_inner()
    }

    fn next_transfer_item(
        &mut self,
        input: pb::NextTransferItemRequest,
    ) -> Result<pb::NextTransferItemResponse> {
        self.storage.ensure_speedrun_tables()?;
        if input.concept_id != 0 {
            let item = self.storage.next_unanswered_item(input.concept_id)?;
            return Ok(pb::NextTransferItemResponse {
                found: item.is_some(),
                item: item.map(item_to_proto),
                concept_id: input.concept_id,
            });
        }
        // Walk the transfer-gap queue and return the first concept that still
        // has an unanswered item to study (a concept whose whole ladder is done
        // is skipped).
        for concept_id in self.transfer_gap_queue_inner(0)?.concept_ids {
            if let Some(item) = self.storage.next_unanswered_item(concept_id)? {
                return Ok(pb::NextTransferItemResponse {
                    found: true,
                    item: Some(item_to_proto(item)),
                    concept_id,
                });
            }
        }
        Ok(pb::NextTransferItemResponse {
            found: false,
            item: None,
            concept_id: 0,
        })
    }

    fn export_transfer_log(
        &mut self,
        _input: pb::ExportTransferLogRequest,
    ) -> Result<pb::TransferLog> {
        let reviews = Collection::export_transfer_log(self)?
            .into_iter()
            .map(|r| pb::TransferReviewProto {
                guid: r.guid,
                item_id: r.item_id,
                concept_id: r.concept_id,
                correct: r.correct,
                latency_ms: r.latency_ms,
                ts: r.ts,
                difficulty: r.difficulty,
            })
            .collect();
        Ok(pb::TransferLog { reviews })
    }

    fn import_transfer_log(
        &mut self,
        input: pb::TransferLog,
    ) -> Result<pb::ImportTransferLogResponse> {
        let incoming = input
            .reviews
            .into_iter()
            .map(|r| TransferReview {
                id: 0, // assigned locally on insert
                guid: r.guid,
                item_id: r.item_id,
                concept_id: r.concept_id,
                correct: r.correct,
                latency_ms: r.latency_ms,
                ts: r.ts,
                difficulty: r.difficulty,
            })
            .collect();
        let stats = Collection::import_transfer_log(self, incoming)?;
        Ok(pb::ImportTransferLogResponse {
            added: stats.added,
            total: stats.total,
        })
    }
}

fn item_to_proto(i: Item) -> pb::Item {
    pb::Item {
        id: i.id,
        concept_id: i.concept_id,
        level: i.level,
        difficulty: i.difficulty,
        source_ref: i.source_ref,
        ai_generated: i.ai_generated,
        stem: i.stem,
        choices: i.choices,
        answer: i.answer,
        explanation: i.explanation,
    }
}

/// Per-concept snapshot used to build the readiness report.
struct ReadinessRow {
    concept_id: i64,
    outline_id: String,
    section: String,
    weight: f64,
    recall: f64,
    transfer: f64,
    n_obs: i64,
    covered: bool,
}

#[derive(Default)]
struct SectionAccum {
    weight: f64,
    weighted_recall: f64,
    weighted_transfer: f64,
    covered_weight: f64,
}

impl Collection {
    fn record_transfer_review_inner(
        &mut self,
        item_id: i64,
        concept_id: i64,
        correct: bool,
        latency_ms: i64,
    ) -> Result<()> {
        let previous = self.storage.get_concept_state(concept_id)?;

        // Capture the item's difficulty now so it travels in the log record; a
        // replay (here or on a peer that lacks the item) is then self-contained.
        let difficulty = self
            .storage
            .item_difficulties()?
            .get(&item_id)
            .copied()
            .unwrap_or(crate::speedrun::REPRESENTATIVE_DIFFICULTY);
        // Append the review to the log first; `theta` is then *derived* by
        // replaying that log, so the live score equals what a sync replay would
        // produce (single source of truth, no incremental drift).
        let review = TransferReview {
            id: self.storage.next_transfer_review_id()?,
            guid: crate::notes::base91_u64(),
            item_id,
            concept_id,
            correct,
            latency_ms,
            ts: TimestampMillis::now().0,
            difficulty,
        };
        self.add_transfer_review_undoable(review)?;

        let (theta, n_obs, last_practiced) =
            self.replayed_concept_state(concept_id)?
                .unwrap_or((0.0, 0, TimestampSecs::now().0));
        let new_state = ConceptState {
            concept_id,
            theta,
            n_obs,
            r_cache: previous.as_ref().map(|s| s.r_cache).unwrap_or(0.0),
            last_practiced,
        };
        // Saved as a reversible change carrying the prior snapshot, so undo
        // restores the exact previous state (and the review removal above).
        self.update_concept_state_undoable(new_state, previous)?;
        Ok(())
    }

    fn mastery_query_inner(&mut self, concept_ids: Vec<i64>) -> Result<pb::MasteryQueryResponse> {
        let all = self.storage.all_concepts()?;
        let outline_by_id: HashMap<i64, String> =
            all.iter().map(|c| (c.id, c.outline_id.clone())).collect();
        let target_ids: Vec<i64> = if concept_ids.is_empty() {
            all.iter().map(|c| c.id).collect()
        } else {
            concept_ids
        };

        let mut entries = Vec::with_capacity(target_ids.len());
        for id in target_ids {
            let state = self.storage.get_concept_state(id)?;
            let theta = state.as_ref().map(|s| s.theta).unwrap_or(0.0);
            let n_obs = state.as_ref().map(|s| s.n_obs).unwrap_or(0) as u32;
            // Live recall from FSRS-tagged cards, falling back to the cached
            // value (then 0) when the concept has no tagged cards yet.
            let recall = match outline_by_id.get(&id) {
                Some(code) => self.concept_recall(code)?,
                None => None,
            }
            .or_else(|| state.as_ref().map(|s| s.r_cache))
            .unwrap_or(0.0);
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
            let n_obs = state.as_ref().map(|s| s.n_obs).unwrap_or(0);
            let transfer = concept_transfer(theta);
            // Honour the give-up rule: a concept the readiness report told the
            // user to abandon (enough attempts, transfer still low) must not be
            // recommended back to them by the study queue.
            if n_obs >= crate::speedrun::GIVE_UP_MIN_OBS
                && transfer < crate::speedrun::GIVE_UP_TRANSFER
            {
                continue;
            }
            let recall = self
                .concept_recall(&c.outline_id)?
                .or_else(|| state.as_ref().map(|s| s.r_cache))
                .unwrap_or(0.0);
            let g = gap(recall, transfer);
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

    fn readiness_report_inner(&mut self) -> Result<pb::ReadinessResponse> {
        use crate::speedrun::SCORE_MAX;
        use crate::speedrun::SCORE_MIN;
        use crate::speedrun::SECTION_SCORE_MAX;
        use crate::speedrun::SECTION_SCORE_MIN;

        // One pass to snapshot every concept's R, T and observation state.
        let concepts = self.storage.all_concepts()?;
        let mut rows: Vec<ReadinessRow> = Vec::with_capacity(concepts.len());
        for c in &concepts {
            let state = self.storage.get_concept_state(c.id)?;
            let theta = state.as_ref().map(|s| s.theta).unwrap_or(0.0);
            let n_obs = state.as_ref().map(|s| s.n_obs).unwrap_or(0);
            let recall = self
                .concept_recall(&c.outline_id)?
                .or_else(|| state.as_ref().map(|s| s.r_cache))
                .unwrap_or(0.0);
            rows.push(ReadinessRow {
                concept_id: c.id,
                outline_id: c.outline_id.clone(),
                section: c.section.clone(),
                weight: c.exam_weight,
                recall,
                transfer: concept_transfer(theta),
                n_obs,
                covered: n_obs > 0,
            });
        }

        // Aggregate per section (BTreeMap for deterministic ordering).
        let mut sections: std::collections::BTreeMap<String, SectionAccum> = Default::default();
        let mut total = SectionAccum::default();
        for r in &rows {
            let acc = sections.entry(r.section.clone()).or_default();
            acc.weight += r.weight;
            acc.weighted_recall += r.weight * r.recall;
            acc.weighted_transfer += r.weight * r.transfer;
            if r.covered {
                acc.covered_weight += r.weight;
            }
            total.weight += r.weight;
            total.weighted_recall += r.weight * r.recall;
            total.weighted_transfer += r.weight * r.transfer;
            if r.covered {
                total.covered_weight += r.weight;
            }
        }

        let safe = |num: f64, den: f64| if den > 0.0 { num / den } else { 0.0 };
        let span = (SCORE_MAX - SCORE_MIN) as f64;
        let coverage = safe(total.covered_weight, total.weight);

        let mut section_reports = Vec::with_capacity(sections.len());
        for (name, acc) in &sections {
            let performance = safe(acc.weighted_transfer, acc.weight);
            let memory = safe(acc.weighted_recall, acc.weight);
            let sec_cov = safe(acc.covered_weight, acc.weight);
            let score = scale_score(performance, SECTION_SCORE_MIN, SECTION_SCORE_MAX);
            let sec_span = (SECTION_SCORE_MAX - SECTION_SCORE_MIN) as f64;
            let half = (sec_span * 0.5 * (1.0 - sec_cov)).round() as i32;
            section_reports.push(pb::SectionReadiness {
                section: name.clone(),
                memory,
                performance,
                score,
                score_low: (score - half).max(SECTION_SCORE_MIN),
                score_high: (score + half).min(SECTION_SCORE_MAX),
                coverage: sec_cov,
            });
        }

        let memory = safe(total.weighted_recall, total.weight);
        let performance = safe(total.weighted_transfer, total.weight);
        let readiness = scale_score(performance, SCORE_MIN, SCORE_MAX);
        // Range widens as coverage drops: a small floor of uncertainty plus a
        // term proportional to the un-observed share of the exam.
        let half_width =
            (span * 0.08).round() as i32 + (span * 0.5 * (1.0 - coverage)).round() as i32;

        // Give-up list and reasons.
        let give_up: Vec<i64> = rows
            .iter()
            .filter(|r| {
                r.n_obs >= crate::speedrun::GIVE_UP_MIN_OBS
                    && r.transfer < crate::speedrun::GIVE_UP_TRANSFER
            })
            .map(|r| r.concept_id)
            .collect();

        let covered_count = rows.iter().filter(|r| r.covered).count();
        let mut reasons = vec![format!(
            "Coverage {:.0}% - {} of {} concepts have transfer data.",
            coverage * 100.0,
            covered_count,
            rows.len()
        )];
        if performance + 0.10 < memory {
            reasons.push(format!(
                "Illusion of mastery: memory {:.0}% but performance {:.0}% - study transfer, not more recall.",
                memory * 100.0,
                performance * 100.0
            ));
        }
        if let Some(top) = rows
            .iter()
            .max_by(|a, b| {
                (a.weight * (a.recall - a.transfer))
                    .partial_cmp(&(b.weight * (b.recall - b.transfer)))
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .filter(|r| r.recall - r.transfer > 0.0)
        {
            reasons.push(format!(
                "Largest weighted gap: {} (G={:.2}). Start here.",
                top.outline_id,
                top.recall - top.transfer
            ));
        }
        if !give_up.is_empty() {
            reasons.push(format!(
                "{} concept(s) flagged by the give-up rule (transfer still low after {}+ attempts).",
                give_up.len(),
                crate::speedrun::GIVE_UP_MIN_OBS
            ));
        }

        Ok(pb::ReadinessResponse {
            memory,
            performance,
            readiness,
            readiness_low: (readiness - half_width).max(SCORE_MIN),
            readiness_high: (readiness + half_width).min(SCORE_MAX),
            coverage,
            sections: section_reports,
            reasons,
            give_up_concept_ids: give_up,
        })
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
                stem: "stem".into(),
                choices: vec!["a".into(), "b".into()],
                answer: 0,
                explanation: "because".into(),
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
    fn recall_from_tagged_cards_feeds_gap() -> Result<()> {
        use fsrs::FSRS5_DEFAULT_DECAY;

        use crate::card::FsrsMemoryState;

        let mut col = open_col();
        add_concept(&mut col, 1, 0.5); // outline_id "C1"

        // A well-remembered card tagged to the concept (high stability, just
        // reviewed -> retrievability ~1).
        let nt = col.get_notetype_by_name("Basic")?.unwrap();
        let mut note = nt.new_note();
        note.tags = vec!["speedrun::C1".to_string()];
        let _ = col.add_note(&mut note, DeckId(1))?;
        let mut card = col.storage.all_cards_of_note(note.id)?.pop().unwrap();
        card.memory_state = Some(FsrsMemoryState {
            stability: 200.0,
            difficulty: 5.0,
        });
        card.decay = Some(FSRS5_DEFAULT_DECAY);
        card.last_review_time = Some(TimestampSecs::now());
        col.storage.update_card(&card)?;

        let m = SpeedrunService::mastery_query(
            &mut col,
            pb::MasteryQueryRequest {
                concept_ids: vec![1],
            },
        )?;
        // High recall, prior transfer (theta 0) -> a large positive gap.
        assert!(
            m.entries[0].recall > 0.9,
            "recall = {}",
            m.entries[0].recall
        );
        assert!((m.entries[0].gap - (m.entries[0].recall - m.entries[0].transfer)).abs() < 1e-9);
        assert!(m.entries[0].gap > 0.4, "gap = {}", m.entries[0].gap);
        Ok(())
    }

    #[test]
    fn readiness_report_scores_and_give_up_rule() -> Result<()> {
        use crate::speedrun::SCORE_MAX;
        use crate::speedrun::SCORE_MIN;

        let mut col = open_col();
        add_concept(&mut col, 1, 0.5);
        add_concept(&mut col, 2, 0.5);

        // Empty: no observations -> coverage 0 and the widest range. Readiness
        // reflects the prior transfer (theta 0), so it is within the band.
        let empty = SpeedrunService::readiness_report(&mut col, pb::ReadinessRequest {})?;
        assert!(empty.readiness >= SCORE_MIN && empty.readiness <= SCORE_MAX);
        assert!((empty.coverage - 0.0).abs() < 1e-9);
        let empty_width = empty.readiness_high - empty.readiness_low;

        // Concept 1: strong transfer. Concept 2: many failed attempts -> give-up.
        col.storage.upsert_concept_state(&ConceptState {
            concept_id: 1,
            theta: 3.0,
            n_obs: 5,
            r_cache: 0.0,
            last_practiced: 0,
        })?;
        col.storage.upsert_concept_state(&ConceptState {
            concept_id: 2,
            theta: -3.0,
            n_obs: 12,
            r_cache: 0.0,
            last_practiced: 0,
        })?;

        let report = SpeedrunService::readiness_report(&mut col, pb::ReadinessRequest {})?;
        assert!(report.readiness > SCORE_MIN && report.readiness <= SCORE_MAX);
        assert!(report.performance > 0.0);
        assert!(report.coverage > 0.0);
        assert!(report.readiness_low <= report.readiness);
        assert!(report.readiness_high >= report.readiness);
        // Concept 2 meets the give-up rule (>=8 obs, transfer < 0.35).
        assert!(report.give_up_concept_ids.contains(&2));
        assert!(!report.give_up_concept_ids.contains(&1));
        assert!(!report.reasons.is_empty());
        // Some coverage should narrow the range versus the empty report.
        assert!(report.readiness_high - report.readiness_low <= empty_width);
        Ok(())
    }

    #[test]
    fn scale_score_maps_fraction_to_band() {
        assert_eq!(scale_score(0.0, 472, 528), 472);
        assert_eq!(scale_score(1.0, 472, 528), 528);
        assert_eq!(scale_score(0.5, 472, 528), 500);
        assert_eq!(scale_score(2.0, 472, 528), 528); // clamped
    }

    #[test]
    fn next_transfer_item_returns_lowest_level_and_round_trips_content() -> Result<()> {
        let mut col = open_col();
        add_concept(&mut col, 1, 0.5);
        // Add an L3 then an L0 item; the L0 (lowest rung) should come first.
        add_item(&mut col, 50, 1, 0.4); // level 3 per helper
        let _ = SpeedrunService::upsert_item(
            &mut col,
            pb::Item {
                id: 51,
                concept_id: 1,
                level: 0,
                difficulty: -1.5,
                source_ref: "seed".into(),
                ai_generated: false,
                stem: "Glycolysis is best defined as:".into(),
                choices: vec!["breakdown of glucose".into(), "synthesis".into()],
                answer: 0,
                explanation: "definition".into(),
            },
        )?;

        let resp = SpeedrunService::next_transfer_item(
            &mut col,
            pb::NextTransferItemRequest { concept_id: 1 },
        )?;
        assert!(resp.found);
        let item = resp.item.unwrap();
        assert_eq!(item.id, 51);
        assert_eq!(item.level, 0);
        assert_eq!(item.stem, "Glycolysis is best defined as:");
        assert_eq!(item.choices.len(), 2);
        assert_eq!(item.answer, 0);

        // concept_id = 0 falls back to the gap queue (only concept 1 exists).
        let from_queue = SpeedrunService::next_transfer_item(
            &mut col,
            pb::NextTransferItemRequest { concept_id: 0 },
        )?;
        assert!(from_queue.found);
        assert_eq!(from_queue.concept_id, 1);
        Ok(())
    }

    /// The review loop advances the ladder: after an item is answered it is not
    /// served again, so the next call returns the next rung, and once every rung
    /// is answered the concept yields nothing.
    #[test]
    fn next_transfer_item_advances_ladder_and_skips_answered() -> Result<()> {
        let mut col = open_col();
        add_concept(&mut col, 1, 0.5);
        for (id, level) in [(51i64, 0u32), (52i64, 1u32)] {
            let _ = SpeedrunService::upsert_item(
                &mut col,
                pb::Item {
                    id,
                    concept_id: 1,
                    level,
                    difficulty: -1.0,
                    source_ref: "seed".into(),
                    ai_generated: false,
                    stem: format!("L{level}"),
                    choices: vec!["a".into(), "b".into()],
                    answer: 0,
                    explanation: "x".into(),
                },
            )
            .unwrap();
        }

        let answer = |col: &mut Collection, item_id: i64| {
            let _ = SpeedrunService::record_transfer_review(
                col,
                pb::RecordTransferReviewRequest {
                    item_id,
                    concept_id: 1,
                    correct: true,
                    latency_ms: 100,
                },
            )
            .unwrap();
        };

        // Lowest rung first.
        let first =
            SpeedrunService::next_transfer_item(&mut col, pb::NextTransferItemRequest { concept_id: 1 })?;
        assert_eq!(first.item.as_ref().unwrap().id, 51);
        answer(&mut col, 51);

        // Advances to the next rung rather than repeating L0.
        let second =
            SpeedrunService::next_transfer_item(&mut col, pb::NextTransferItemRequest { concept_id: 1 })?;
        assert_eq!(second.item.as_ref().unwrap().id, 52);
        answer(&mut col, 52);

        // Whole ladder answered -> nothing left.
        let done =
            SpeedrunService::next_transfer_item(&mut col, pb::NextTransferItemRequest { concept_id: 1 })?;
        assert!(!done.found);
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

    /// A concept flagged by the give-up rule (enough attempts, transfer still
    /// low) must not be recommended by the study queue.
    #[test]
    fn queue_excludes_given_up_concepts() -> Result<()> {
        let mut col = open_col();
        add_concept(&mut col, 1, 0.5);
        add_concept(&mut col, 2, 0.5);
        // Concept 2: many attempts, transfer still low -> give-up fires.
        col.storage.upsert_concept_state(&ConceptState {
            concept_id: 2,
            theta: -3.0,
            n_obs: 12,
            r_cache: 0.9,
            last_practiced: 0,
        })?;
        let queue = SpeedrunService::transfer_gap_queue(
            &mut col,
            pb::TransferGapQueueRequest { limit: 0 },
        )?;
        assert!(!queue.concept_ids.contains(&2));
        assert!(queue.concept_ids.contains(&1));
        Ok(())
    }
}
