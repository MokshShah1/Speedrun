// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Aggregates recall R (FSRS retrievability) to the concept level.
//!
//! A card teaches a concept when its note carries the tag
//! `speedrun::<outline_id>` (see speedrun/README.md). A concept's R is the mean
//! current retrievability of those cards, using the same FSRS computation Anki
//! uses for its retrievability graph. This is the R in the gap G = R - T.

use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use crate::prelude::*;
use crate::search::JoinSearches;
use crate::search::Negated;
use crate::search::SearchNode;
use crate::search::SortMode;
use crate::search::StateKind;

impl Collection {
    /// Mean current FSRS retrievability across the cards tagged to a concept.
    /// Returns None when the concept has no tagged cards with a memory state.
    pub(crate) fn concept_recall(&mut self, outline_id: &str) -> Result<Option<f64>> {
        // Build the tag search through SearchNode so the outline_id is escaped
        // (a wildcard or space would otherwise match the wrong cards), and
        // exclude intentionally-suspended cards: their retrievability keeps
        // decaying and would drag the concept's recall toward zero even though
        // the user removed them from scheduling.
        let search = SearchNode::from_tag_name(&format!("speedrun::{outline_id}"))
            .and(StateKind::Suspended.negated());
        let card_ids = self.search_cards(search, SortMode::NoOrder)?;
        if card_ids.is_empty() {
            return Ok(None);
        }
        let timing = self.timing_today()?;
        let fsrs = FSRS::new(None).unwrap();
        let mut sum = 0.0f64;
        let mut n = 0u32;
        for cid in card_ids {
            let Some(card) = self.storage.get_card(cid)? else {
                continue;
            };
            if let Some(state) = card.memory_state {
                let elapsed = card.seconds_since_last_review(&timing).unwrap_or_default();
                let r = fsrs.current_retrievability_seconds(
                    state.into(),
                    elapsed,
                    card.decay.unwrap_or(FSRS5_DEFAULT_DECAY),
                );
                sum += r as f64;
                n += 1;
            }
        }
        Ok(if n == 0 { None } else { Some(sum / n as f64) })
    }
}
