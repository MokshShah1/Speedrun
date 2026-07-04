# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun transfer reviewer: study the *use* of a concept, not just recall.

Pulls the next item from the transfer-gap queue (or a chosen concept), shows the
stem and multiple-choice options, grades the answer through the engine's
RecordTransferReview RPC (which updates the concept's transfer ability), then
shows the explanation and advances. This is the item half of the Wednesday
"review loop over cards + items"."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aqt.qt import (
    QAction,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPushButton,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import showInfo, showWarning

if TYPE_CHECKING:
    from aqt.main import AnkiQt

_LADDER = [
    "L0 · definition",
    "L1 · paraphrase",
    "L2 · single-concept",
    "L3 · novel application",
    "L4 · multi-concept",
    "L5 · full passage",
]

# Sans + mono font stacks (DESIGN.md: Geist / Fira Code), with graceful fallbacks.
_SANS = '"Geist", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
_MONO = '"Fira Code", ui-monospace, "SF Mono", Menlo, Consolas, monospace'


def _theme() -> dict[str, str]:
    """shadcn (zinc/neutral) tokens, theme-aware, matching the dashboard so the
    two windows read as one product.

    Keys: page/card/border/text/muted/hover chrome, a neutral primary button
    (black on light, white on dark) with primary_fg + ring, and semantic
    success/warning/danger colours (600 on light, brighter 500 on dark)."""
    night = False
    try:
        from aqt.theme import theme_manager

        night = bool(theme_manager.night_mode)
    except Exception:  # pragma: no cover - defensive
        pass
    if night:
        return {
            "page": "#09090b", "card": "#18181b", "border": "#27272a",
            "text": "#fafafa", "muted": "#a1a1aa", "hover": "#27272a",
            "primary": "#fafafa", "primary_fg": "#18181b", "ring": "#52525b",
            "success": "#22c55e", "warning": "#f59e0b", "danger": "#ef4444",
        }
    return {
        "page": "#f4f4f5", "card": "#ffffff", "border": "#e4e4e7",
        "text": "#111827", "muted": "#71717a", "hover": "#f4f4f5",
        "primary": "#18181b", "primary_fg": "#fafafa", "ring": "#a1a1aa",
        "success": "#16a34a", "warning": "#d97706", "danger": "#dc2626",
    }


class TransferReviewer(QWidget):
    def __init__(self, mw: AnkiQt) -> None:
        super().__init__(mw, Qt.WindowType.Window)
        self.mw = mw
        self.pal = _theme()
        self.setWindowTitle("Speedrun - Transfer Review")
        self.resize(640, 520)
        self.setStyleSheet(f"background:{self.pal['page']};")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(8)
        self.current: Any = None  # the pb.Item being shown, or None
        self.answered = False
        self.choice_buttons: list[QPushButton] = []
        self.session_seen = 0
        self.session_correct = 0
        self.load_next()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _score_line(self) -> QLabel:
        pct = (self.session_correct / self.session_seen * 100) if self.session_seen else 0
        label = QLabel(
            f"<span style='color:{self.pal['muted']};'>This session</span> &nbsp; "
            f"<b style='color:{self.pal['text']};'>{self.session_correct}/{self.session_seen}</b> "
            f"<span style='color:{self.pal['muted']};'>({pct:.0f}%) &middot; keys 1-9 to answer</span>"
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(f"font-family:{_SANS};font-size:12px;")
        return label

    def load_next(self) -> None:
        self._clear()
        self.answered = False
        resp = self.mw.col._backend.next_transfer_item(concept_id=0)
        if not resp.found:
            msg = QLabel("No transfer items available. Import a deck first.")
            msg.setStyleSheet(f"color:{self.pal['muted']};font-size:14px;")
            self._layout.addWidget(msg)
            return
        self.current = resp.item

        self._layout.addWidget(self._score_line())

        level = self.current.level
        rung = _LADDER[level] if level < len(_LADDER) else f"L{level}"
        chip = QLabel(
            f"{rung}   ·   Concept {resp.concept_id}   ·   {self.current.source_ref}"
        )
        chip.setWordWrap(True)
        chip.setStyleSheet(
            f"background:{self.pal['hover']};color:{self.pal['muted']};border:1px solid "
            f"{self.pal['border']};border-radius:8px;padding:6px 10px;"
            f"font-family:{_MONO};font-size:12px;"
        )
        self._layout.addWidget(chip)

        stem = QLabel(self.current.stem)
        stem.setWordWrap(True)
        stem.setStyleSheet(
            f"font-family:{_SANS};font-size:16px;color:{self.pal['text']};"
            "margin:12px 2px 8px;line-height:150%;"
        )
        self._layout.addWidget(stem)

        self.choice_buttons = []
        for idx, text in enumerate(self.current.choices):
            btn = QPushButton(f"{idx + 1}.   {text}")
            btn.setStyleSheet(self._choice_style())
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            qconnect(btn.clicked, lambda _=False, i=idx: self.choose(i))
            self._layout.addWidget(btn)
            self.choice_buttons.append(btn)

        self._layout.addStretch()

    def _choice_style(self) -> str:
        return (
            "QPushButton {"
            f"  text-align:left; padding:11px 14px; border:1px solid {self.pal['border']};"
            f"  border-radius:8px; background:{self.pal['card']}; color:{self.pal['text']};"
            f"  font-family:{_SANS}; font-size:14px; margin:3px 0; }}"
            f"QPushButton:hover {{ border:1px solid {self.pal['ring']}; background:{self.pal['hover']}; }}"
        )

    def _answered_style(self, color: str) -> str:
        return (
            "QPushButton {"
            f"  text-align:left; padding:11px 14px; border:1px solid {color};"
            f"  border-radius:8px; background:{color}; color:white;"
            f"  font-family:{_SANS}; font-size:14px; font-weight:bold; margin:3px 0; }}"
        )

    def _dim_style(self) -> str:
        return (
            "QPushButton {"
            f"  text-align:left; padding:11px 14px; border:1px solid {self.pal['border']};"
            f"  border-radius:8px; background:{self.pal['card']}; color:{self.pal['muted']};"
            f"  font-family:{_SANS}; font-size:14px; margin:3px 0; }}"
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if not self.answered and self.current is not None:
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                idx = key - Qt.Key.Key_1
                if idx < len(self.choice_buttons):
                    self.choose(idx)
                    return
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.load_next()
            return
        super().keyPressEvent(event)

    def choose(self, idx: int) -> None:
        if self.answered or self.current is None:
            return
        self.answered = True
        correct = idx == self.current.answer
        self.session_seen += 1
        if correct:
            self.session_correct += 1
        self.mw.col._backend.record_transfer_review(
            item_id=self.current.id,
            concept_id=self.current.concept_id,
            correct=correct,
            latency_ms=0,
        )
        for i, btn in enumerate(self.choice_buttons):
            btn.setEnabled(False)
            if i == self.current.answer:
                btn.setStyleSheet(self._answered_style(self.pal["success"]))
            elif i == idx:
                btn.setStyleSheet(self._answered_style(self.pal["danger"]))
            else:
                btn.setStyleSheet(self._dim_style())

        verdict = QLabel("✓ Correct" if correct else "✗ Not yet")
        verdict.setStyleSheet(
            f"font-family:{_SANS};font-weight:bold;font-size:15px;margin-top:12px;"
            f"color:{self.pal['success'] if correct else self.pal['danger']};"
        )
        self._layout.addWidget(verdict)
        if self.current.explanation:
            exp = QLabel(self.current.explanation)
            exp.setWordWrap(True)
            exp.setStyleSheet(
                f"font-family:{_SANS};color:{self.pal['muted']};font-size:13px;"
                "margin:4px 2px;line-height:145%;"
            )
            self._layout.addWidget(exp)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{self.pal['border']};margin-top:8px;")
        self._layout.addWidget(line)
        buttons = QDialogButtonBox()
        next_btn = buttons.addButton(
            "Next item  (\u21b5)", QDialogButtonBox.ButtonRole.AcceptRole
        )
        next_btn.setStyleSheet(
            f"QPushButton {{ background:{self.pal['primary']}; color:{self.pal['primary_fg']};"
            f" border:none; border-radius:8px; padding:9px 18px; font-family:{_SANS};"
            " font-weight:bold; }"
        )
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        qconnect(next_btn.clicked, self.load_next)
        done_btn = buttons.addButton("Done", QDialogButtonBox.ButtonRole.RejectRole)
        done_btn.setStyleSheet(
            "QPushButton {"
            f" background:{self.pal['card']}; color:{self.pal['text']};"
            f" border:1px solid {self.pal['border']}; border-radius:8px; padding:9px 18px;"
            f" font-family:{_SANS}; }}"
            f"QPushButton:hover {{ background:{self.pal['hover']}; }}"
        )
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        qconnect(done_btn.clicked, self.close)
        self._layout.addWidget(buttons)


def open_transfer_reviewer(mw: AnkiQt) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    if not mw.col._backend.next_transfer_item(concept_id=0).found:
        showInfo(
            "No transfer items yet. Import the concept map and items first "
            "(see speedrun/import_content.py)."
        )
        return
    # Keep a reference on the main window so the widget isn't garbage-collected.
    reviewer = TransferReviewer(mw)
    mw._speedrun_reviewer = reviewer  # type: ignore[attr-defined]
    reviewer.show()


def add_reviewer_action(mw: AnkiQt) -> None:
    action = QAction("Speedrun: Transfer Review", mw)
    action.setObjectName("actionSpeedrunTransferReview")
    qconnect(action.triggered, lambda: open_transfer_reviewer(mw))
    mw.form.menuTools.addAction(action)
