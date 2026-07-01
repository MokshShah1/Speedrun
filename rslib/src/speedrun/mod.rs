// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun transfer engine.
//!
//! Upstream Anki schedules on recall R (probability you remember a card). The
//! Speedrun thesis is that the grade-relevant quantity is *transfer* T: the
//! probability you can solve a novel problem that requires a concept under
//! changed wording or context. We model T per concept with a one-parameter
//! (Elo / 1-PL IRT) ability `theta`, updated online from graded transfer items,
//! and expose the gap G = R - T, which drives the study queue and dashboard.

pub(crate) mod recall;
pub mod service;
pub(crate) mod sync;
pub(crate) mod undo;

/// Representative MCAT item difficulty (around ladder levels L3-L4) at which a
/// concept's overall transfer probability is reported on the dashboard.
pub const REPRESENTATIVE_DIFFICULTY: f64 = 0.5;

/// Online learning rate for the ability (theta) update. Small so a single lucky
/// or unlucky answer cannot swing the estimate too far.
pub const ELO_K: f64 = 0.3;

/// MCAT total score band.
pub const SCORE_MIN: i32 = 472;
pub const SCORE_MAX: i32 = 528;
/// Per-section score band.
pub const SECTION_SCORE_MIN: i32 = 118;
pub const SECTION_SCORE_MAX: i32 = 132;

/// Give-up rule defaults (confirmed in the PRD): a concept with at least this
/// many transfer observations whose transfer probability is still below
/// `GIVE_UP_TRANSFER` is flagged for deprioritisation.
pub const GIVE_UP_MIN_OBS: i64 = 8;
pub const GIVE_UP_TRANSFER: f64 = 0.35;

/// Map a 0..1 ability fraction onto an MCAT score band `[lo, hi]`. This is the
/// v0 readiness mapping (linear in transfer); it is intentionally explicit so
/// it can be replaced by the calibrated mapping in the prove/ship phase.
pub fn scale_score(fraction: f64, lo: i32, hi: i32) -> i32 {
    let f = fraction.clamp(0.0, 1.0);
    lo + ((hi - lo) as f64 * f).round() as i32
}

/// A concept, mapped 1:1 to the AAMC content outline. The engine's unit of
/// mastery (not a card).
#[derive(Debug, Clone, PartialEq)]
pub struct Concept {
    pub id: i64,
    pub outline_id: String,
    pub section: String,
    pub title: String,
    pub exam_weight: f64,
}

/// A transfer item: one question testing a concept at a ladder level.
#[derive(Debug, Clone, PartialEq)]
pub struct Item {
    pub id: i64,
    pub concept_id: i64,
    pub level: u32,
    /// Item difficulty `b` for the IRT model; frozen after authoring.
    pub difficulty: f64,
    pub source_ref: String,
    pub ai_generated: bool,
    pub stem: String,
    pub choices: Vec<String>,
    /// Index into `choices` of the correct answer.
    pub answer: u32,
    pub explanation: String,
}

/// One graded answer to a transfer item. The append-only unit of sync: the
/// concept's learned `theta` is *derived* by replaying these in canonical
/// order, so syncing the log (union by `guid`) is conflict-free and idempotent.
#[derive(Debug, Clone, PartialEq)]
pub struct TransferReview {
    /// Device-local row id (not stable across devices).
    pub id: i64,
    /// Globally-unique identity for sync/merge.
    pub guid: String,
    pub item_id: i64,
    pub concept_id: i64,
    pub correct: bool,
    pub latency_ms: i64,
    pub ts: i64,
    /// Item difficulty (IRT b) captured at answer time. Persisted and synced in
    /// the review record so replay is self-contained and converges across
    /// devices even when an item is missing from the local item table.
    pub difficulty: f64,
}

/// The learned transfer state for a concept.
#[derive(Debug, Clone, PartialEq)]
pub struct ConceptState {
    pub concept_id: i64,
    /// Estimated ability on this concept.
    pub theta: f64,
    pub n_obs: i64,
    /// Cached recall R aggregated from FSRS (wired in a later phase).
    pub r_cache: f64,
    pub last_practiced: i64,
}

#[inline]
pub fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}

/// Probability of correctly solving a novel item of difficulty `b` given the
/// concept ability `theta` (1-PL IRT / Elo expected score).
#[inline]
pub fn transfer_probability(theta: f64, b: f64) -> f64 {
    sigmoid(theta - b)
}

/// A concept's headline transfer probability, evaluated at the representative
/// MCAT difficulty.
#[inline]
pub fn concept_transfer(theta: f64) -> f64 {
    transfer_probability(theta, REPRESENTATIVE_DIFFICULTY)
}

/// One online Elo/IRT update of the ability after grading an item.
#[inline]
pub fn elo_update(theta: f64, b: f64, correct: bool, k: f64) -> f64 {
    let expected = transfer_probability(theta, b);
    let actual = if correct { 1.0 } else { 0.0 };
    theta + k * (actual - expected)
}

/// Gap G = R - T. Positive means the illusion of mastery: you can recall the
/// fact but not yet use it.
#[inline]
pub fn gap(recall: f64, transfer: f64) -> f64 {
    recall - transfer
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn correct_answer_raises_ability_wrong_lowers_it() {
        let b = 0.0;
        let after_correct = elo_update(0.0, b, true, ELO_K);
        let after_wrong = elo_update(0.0, b, false, ELO_K);
        assert!(after_correct > 0.0, "correct answer should raise theta");
        assert!(after_wrong < 0.0, "wrong answer should lower theta");
        // Symmetric around the prior when expected == 0.5.
        assert!((after_correct + after_wrong).abs() < 1e-9);
    }

    #[test]
    fn transfer_probability_is_monotonic_in_ability_and_difficulty() {
        // Higher ability -> higher transfer at fixed difficulty.
        assert!(transfer_probability(1.0, 0.0) > transfer_probability(-1.0, 0.0));
        // Harder item -> lower transfer at fixed ability.
        assert!(transfer_probability(0.0, 1.0) < transfer_probability(0.0, -1.0));
        // Equal ability and difficulty -> coin flip.
        assert!((transfer_probability(0.7, 0.7) - 0.5).abs() < 1e-9);
    }

    #[test]
    fn gap_captures_recall_minus_transfer() {
        // Strong recall, weak transfer -> large positive gap (illusion of mastery).
        let g = gap(0.95, concept_transfer(-1.0));
        assert!(g > 0.5, "expected a large positive gap, got {g}");
        // Updating beyond an expected-correct prediction yields a smaller step
        // than an unexpected one.
        let confident = elo_update(2.0, 0.0, true, ELO_K) - 2.0;
        let surprised = elo_update(-2.0, 0.0, true, ELO_K) - (-2.0);
        assert!(surprised > confident);
    }
}
