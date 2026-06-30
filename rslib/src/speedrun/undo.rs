// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Undo support for transfer reviews, following Anki's Added/Removed pattern so
//! that recording a review is fully reversible (and redoable).

use crate::prelude::*;
use crate::speedrun::ConceptState;
use crate::speedrun::TransferReview;

#[derive(Debug)]
pub(crate) enum UndoableSpeedrunChange {
    TransferReviewAdded(TransferReview),
    TransferReviewRemoved(TransferReview),
    ConceptStateChanged {
        concept_id: i64,
        previous: Option<ConceptState>,
    },
}

impl Collection {
    pub(crate) fn undo_speedrun_change(&mut self, change: UndoableSpeedrunChange) -> Result<()> {
        match change {
            UndoableSpeedrunChange::TransferReviewAdded(r) => {
                self.remove_transfer_review_undoable(r)
            }
            UndoableSpeedrunChange::TransferReviewRemoved(r) => {
                self.add_transfer_review_undoable(r)
            }
            UndoableSpeedrunChange::ConceptStateChanged {
                concept_id,
                previous,
            } => {
                // Record the current state so the change can be redone, then
                // restore the previous one.
                let current = self.storage.get_concept_state(concept_id)?;
                self.save_undo(UndoableSpeedrunChange::ConceptStateChanged {
                    concept_id,
                    previous: current,
                });
                match previous {
                    Some(s) => self.storage.upsert_concept_state(&s),
                    None => self.storage.remove_concept_state(concept_id),
                }
            }
        }
    }

    pub(super) fn add_transfer_review_undoable(&mut self, review: TransferReview) -> Result<()> {
        self.storage.add_transfer_review(&review)?;
        self.save_undo(UndoableSpeedrunChange::TransferReviewAdded(review));
        Ok(())
    }

    pub(super) fn remove_transfer_review_undoable(&mut self, review: TransferReview) -> Result<()> {
        self.storage.remove_transfer_review(review.id)?;
        self.save_undo(UndoableSpeedrunChange::TransferReviewRemoved(review));
        Ok(())
    }

    pub(super) fn update_concept_state_undoable(
        &mut self,
        new_state: ConceptState,
        previous: Option<ConceptState>,
    ) -> Result<()> {
        self.save_undo(UndoableSpeedrunChange::ConceptStateChanged {
            concept_id: new_state.concept_id,
            previous,
        });
        self.storage.upsert_concept_state(&new_state)
    }
}
