# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Speedrun dashboard: the three honest scores (Memory, Performance, Readiness)
with ranges, coverage, plain-language reasons and the give-up list.

The numbers come straight from the Rust engine's ReadinessReport RPC, so the
desktop and (later) the phone show the identical computation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aqt.qt import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import showWarning

if TYPE_CHECKING:
    from aqt.main import AnkiQt


def _bar(label: str, pct: float, sub: str) -> str:
    width = max(0, min(100, round(pct * 100)))
    return f"""
    <div style="margin:10px 0;">
      <div style="font-weight:bold;">{label}</div>
      <div style="background:#e6e6e6;border-radius:6px;height:18px;width:100%;">
        <div style="background:#3b82f6;height:18px;border-radius:6px;width:{width}%;"></div>
      </div>
      <div style="color:#666;font-size:12px;">{sub}</div>
    </div>"""


def _report_html(report) -> str:
    mem = report.memory
    perf = report.performance
    sections_rows = ""
    for s in report.sections:
        sections_rows += (
            f"<tr><td>{s.section}</td>"
            f"<td style='text-align:right;'>{s.memory*100:.0f}%</td>"
            f"<td style='text-align:right;'>{s.performance*100:.0f}%</td>"
            f"<td style='text-align:right;'>{s.score} ({s.score_low}-{s.score_high})</td>"
            f"<td style='text-align:right;'>{s.coverage*100:.0f}%</td></tr>"
        )
    reasons = "".join(f"<li>{r}</li>" for r in report.reasons)
    give_up = (
        f"<p><b>Give-up rule:</b> {len(report.give_up_concept_ids)} concept(s) "
        f"flagged (concept ids: {', '.join(map(str, report.give_up_concept_ids))}).</p>"
        if report.give_up_concept_ids
        else "<p><b>Give-up rule:</b> nothing flagged.</p>"
    )

    return f"""
    <html><body style="font-family:sans-serif;">
      <h1 style="margin-bottom:0;">Readiness {report.readiness}
        <span style="color:#666;font-size:16px;">
          ({report.readiness_low}-{report.readiness_high}, 472-528 scale)
        </span></h1>
      <p style="color:#666;margin-top:4px;">Coverage {report.coverage*100:.0f}%
         of the exam has transfer data. Readiness is built on transfer, not recall.</p>
      {_bar("Memory (recall R)", mem, f"{mem*100:.0f}% - what you can remember")}
      {_bar("Performance (transfer T)", perf, f"{perf*100:.0f}% - what you can actually use")}
      <h3>By section</h3>
      <table cellpadding="6" style="border-collapse:collapse;width:100%;">
        <tr style="border-bottom:1px solid #ccc;text-align:left;">
          <th>Section</th><th style='text-align:right;'>Memory</th>
          <th style='text-align:right;'>Performance</th>
          <th style='text-align:right;'>Score</th>
          <th style='text-align:right;'>Coverage</th></tr>
        {sections_rows}
      </table>
      <h3>Why</h3>
      <ul>{reasons}</ul>
      {give_up}
    </body></html>"""


def show_dashboard(mw: AnkiQt) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    try:
        report = mw.col._backend.readiness_report()
    except Exception as exc:  # pragma: no cover - defensive
        showWarning(f"Could not build the readiness report: {exc}")
        return

    dialog = QDialog(mw)
    dialog.setWindowTitle("Speedrun - Readiness")
    dialog.resize(640, 620)
    layout = QVBoxLayout(dialog)
    browser = QTextBrowser()
    browser.setHtml(_report_html(report))
    layout.addWidget(browser)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    qconnect(buttons.rejected, dialog.reject)
    qconnect(buttons.accepted, dialog.accept)
    layout.addWidget(buttons)
    dialog.show()


def add_dashboard_action(mw: AnkiQt) -> None:
    """Add a 'Speedrun Dashboard' item to the Tools menu."""
    action = QAction("Speedrun Dashboard", mw)
    action.setObjectName("actionSpeedrunDashboard")
    qconnect(action.triggered, lambda: show_dashboard(mw))
    mw.form.menuTools.addAction(action)
