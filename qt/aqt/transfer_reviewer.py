# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun transfer reviewer: study the *use* of a concept, not just recall.

Pulls the next item from the transfer-gap queue (or a chosen concept), shows the
stem and multiple-choice options, grades the answer through the engine's
RecordTransferReview RPC (which updates the concept's transfer ability), then
shows the explanation and advances. This is the item half of the Wednesday
"review loop over cards + items"."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from aqt.qt import (
    QAction,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    Qt,
    QWidget,
    qconnect,
)
from aqt.utils import showInfo, showWarning

if TYPE_CHECKING:
    from aqt.main import AnkiQt


class TransferReviewer(QWidget):
    def __init__(self, mw: AnkiQt) -> None:
        super().__init__(mw, Qt.WindowType.Window)
        self.mw = mw
        self.setWindowTitle("Speedrun - Transfer Review")
        self.resize(620, 480)
        self._layout = QVBoxLayout(self)
        self.current = None  # type: Optional[object]
        self.answered = False
        self.load_next()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def load_next(self) -> None:
        self._clear()
        self.answered = False
        resp = self.mw.col._backend.next_transfer_item(concept_id=0)
        if not resp.found:
            self._layout.addWidget(QLabel("No transfer items available. Import a deck first."))
            return
        self.current = resp.item

        ladder = ["L0 definition", "L1 paraphrase", "L2 single-concept",
                  "L3 novel application", "L4 multi-concept", "L5 full passage"]
        level = self.current.level
        header = QLabel(
            f"<b>Concept {resp.concept_id}</b> &nbsp; "
            f"<span style='color:#666;'>{ladder[level] if level < len(ladder) else level} "
            f"&middot; {self.current.source_ref}</span>"
        )
        header.setWordWrap(True)
        self._layout.addWidget(header)

        stem = QLabel(self.current.stem)
        stem.setWordWrap(True)
        stem.setStyleSheet("font-size:15px;margin:10px 0;")
        self._layout.addWidget(stem)

        self.choice_buttons = []
        for idx, text in enumerate(self.current.choices):
            btn = QPushButton(f"{chr(65 + idx)}.  {text}")
            btn.setStyleSheet("text-align:left;padding:8px;")
            qconnect(btn.clicked, lambda _=False, i=idx: self.choose(i))
            self._layout.addWidget(btn)
            self.choice_buttons.append(btn)

        self._layout.addStretch()

    def choose(self, idx: int) -> None:
        if self.answered or self.current is None:
            return
        self.answered = True
        correct = idx == self.current.answer
        self.mw.col._backend.record_transfer_review(
            item_id=self.current.id,
            concept_id=self.current.concept_id,
            correct=correct,
            latency_ms=0,
        )
        for i, btn in enumerate(self.choice_buttons):
            btn.setEnabled(False)
            if i == self.current.answer:
                btn.setStyleSheet("text-align:left;padding:8px;background:#16a34a;color:white;")
            elif i == idx:
                btn.setStyleSheet("text-align:left;padding:8px;background:#dc2626;color:white;")

        verdict = QLabel("Correct" if correct else "Not yet")
        verdict.setStyleSheet(
            f"font-weight:bold;margin-top:10px;color:{'#16a34a' if correct else '#dc2626'};"
        )
        self._layout.addWidget(verdict)
        if self.current.explanation:
            exp = QLabel(self.current.explanation)
            exp.setWordWrap(True)
            exp.setStyleSheet("color:#444;margin:4px 0;")
            self._layout.addWidget(exp)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        self._layout.addWidget(line)
        buttons = QDialogButtonBox()
        next_btn = buttons.addButton("Next item", QDialogButtonBox.ButtonRole.AcceptRole)
        qconnect(next_btn.clicked, self.load_next)
        done_btn = buttons.addButton("Done", QDialogButtonBox.ButtonRole.RejectRole)
        qconnect(done_btn.clicked, self.close)
        self._layout.addWidget(buttons)


def open_transfer_reviewer(mw: AnkiQt) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    if not mw.col._backend.next_transfer_item(concept_id=0).found:
        showInfo("No transfer items yet. Import the concept map and items first "
                 "(see speedrun/import_content.py).")
        return
    mw._speedrun_reviewer = TransferReviewer(mw)
    mw._speedrun_reviewer.show()


def add_reviewer_action(mw: AnkiQt) -> None:
    action = QAction("Speedrun: Transfer Review", mw)
    action.setObjectName("actionSpeedrunTransferReview")
    qconnect(action.triggered, lambda: open_transfer_reviewer(mw))
    mw.form.menuTools.addAction(action)
