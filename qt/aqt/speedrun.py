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
    QPushButton,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import showWarning

if TYPE_CHECKING:
    from aqt.main import AnkiQt

# Data-viz accent colours for the two honest scores. Kept distinct but tuned to
# the shadcn 600-weight family so they sit next to the semantic colours below.
_MEMORY = "#2563eb"       # blue-600
_PERFORMANCE = "#7c3aed"  # violet-600
_READINESS = "#4f46e5"    # indigo-600
# Semantic colours aligned to the shadcn tokens (DESIGN.md): success / warning /
# danger. Meaning is preserved: green = on track, amber = watch, red = big gap.
_GREEN = "#16a34a"  # success  (DESIGN #16A34A)
_AMBER = "#d97706"  # warning  (DESIGN #D97706)
_RED = "#dc2626"    # danger   (DESIGN #DC2626)


def _palette() -> dict[str, str]:
    """shadcn (zinc/neutral) design tokens, theme-aware so the dashboard follows
    Anki's light/dark mode.

    Light values come from DESIGN.md (surface/text + the derived neutral chrome);
    the dark palette is the standard shadcn zinc dark ramp (background zinc-950,
    card zinc-900, border zinc-800, foreground zinc-50, muted zinc-400)."""
    night = False
    try:
        from aqt.theme import theme_manager

        night = bool(theme_manager.night_mode)
    except Exception:  # pragma: no cover - defensive
        pass
    if night:
        return {
            "page": "#09090b",    # background  (zinc-950)
            "card": "#18181b",    # card        (zinc-900)
            "border": "#27272a",  # border      (zinc-800)
            "text": "#fafafa",    # foreground  (zinc-50)
            "muted": "#a1a1aa",   # muted-fg    (zinc-400)
            "track": "#27272a",   # muted       (zinc-800)
            "zebra": "#1c1c1f",   # subtle row tint
            "shadow": "rgba(0,0,0,0.5)",
            "heroa": "#1c1c1f", "herob": "#141416",
        }
    return {
        "page": "#f4f4f5",    # background tint (zinc-100) - subtle, not stark white
        "card": "#ffffff",    # surface     (DESIGN #FFFFFF)
        "border": "#e4e4e7",  # border      (zinc-200)
        "text": "#111827",    # text        (DESIGN #111827)
        "muted": "#71717a",   # muted-fg    (zinc-500)
        "track": "#f4f4f5",   # muted       (zinc-100)
        "zebra": "#fafafa",   # subtle row tint (zinc-50)
        "shadow": "rgba(9,9,11,0.06)",
        "heroa": "#ffffff", "herob": "#f4f4f5",
    }


def _gap_color(gap: float) -> str:
    if gap >= 0.15:
        return _RED
    if gap > 0.03:
        return _AMBER
    return _GREEN


# Typography (DESIGN.md): sans = Geist, mono/label-caps = Fira Code. Both fall
# back gracefully since these fonts may not be installed inside the webview.
# Radii follow the shadcn scale (sm 4px / md 8px, lg 12px for cards); spacing
# uses the 4/8/12/16/24/32 step scale.
_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 24px 32px;
  background: __PAGE__; color: __TEXT__;
  font-family: "Geist", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 16px; -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 680px; margin: 0 auto; }
.card {
  background: __CARD__; border: 1px solid __BORDER__; border-radius: 12px;
  box-shadow: 0 1px 2px __SHADOW__, 0 8px 24px -16px __SHADOW__;
}
.hero {
  background: linear-gradient(135deg, __HEROA__, __HEROB__);
  border: 1px solid __BORDER__; border-radius: 12px; padding: 24px;
  box-shadow: 0 1px 2px __SHADOW__, 0 12px 28px -18px __SHADOW__;
}
.eyebrow { font-family: "Fira Code", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px; font-weight: 600; letter-spacing: 1.2px; color: __MUTED__; }
.score { font-size: 60px; font-weight: 800; line-height: 1.02; margin: 4px 0 2px;
  color: __TEXT__; letter-spacing: -1.5px; }
.range { font-size: 14px; color: __MUTED__; }
.scale { position: relative; height: 8px; border-radius: 4px; margin: 24px 0 8px;
  background: linear-gradient(90deg, __RED__ 0%, __AMBER__ 50%, __GREEN__ 100%); }
.marker { position: absolute; top: -4px; width: 4px; height: 16px; border-radius: 2px;
  background: __TEXT__; box-shadow: 0 0 0 2px __CARD__; transform: translateX(-50%); }
.ticks { display: flex; justify-content: space-between; font-size: 12px; color: __MUTED__; }
.stats { display: flex; gap: 12px; margin: 16px 0; }
.stat { flex: 1; padding: 16px; }
.stat-top { display: flex; align-items: center; font-size: 12px; font-weight: 500; color: __MUTED__; }
.dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }
.stat-val { font-size: 30px; font-weight: 800; letter-spacing: -0.5px; margin: 4px 0 12px; }
.track { height: 6px; border-radius: 4px; background: __TRACK__; overflow: hidden; }
.fill { height: 6px; border-radius: 4px; }
.section-title { font-family: "Fira Code", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px; font-weight: 600; letter-spacing: 0.8px;
  text-transform: uppercase; color: __MUTED__; margin: 24px 4px 8px; }
table { width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 12px; }
thead th { font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.4px;
  color: __MUTED__; text-align: right; padding: 12px; background: __ZEBRA__; }
thead th:first-child { text-align: left; }
tbody td { font-size: 14px; padding: 12px; text-align: right; border-top: 1px solid __BORDER__; }
tbody td:first-child { text-align: left; font-weight: 600; }
tbody tr:nth-child(even) { background: __ZEBRA__; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.muted { color: __MUTED__; font-weight: 400; }
.reasons { padding: 16px 18px; }
.reasons ul { margin: 0; padding-left: 18px; }
.reasons li { font-size: 14px; margin: 6px 0; color: __TEXT__; }
.giveup { margin-top: 16px; padding: 12px 16px; border-radius: 8px; font-size: 14px;
  background: rgba(217,119,6,0.10); border: 1px solid rgba(217,119,6,0.35); }
.giveup b { color: __TEXT__; }
"""


def _css(pal: dict[str, str]) -> str:
    css = _CSS
    tokens = {**pal, "red": _RED, "amber": _AMBER, "green": _GREEN}
    for key, val in tokens.items():
        css = css.replace(f"__{key.upper()}__", val)
    return css


def _stat(label: str, pct: float, color: str) -> str:
    width = max(0, min(100, round(pct * 100)))
    return (
        f'<div class="stat card"><div class="stat-top"><span class="dot" '
        f'style="background:{color}"></span>{label}</div>'
        f'<div class="stat-val" style="color:{color}">{pct * 100:.0f}%</div>'
        f'<div class="track"><div class="fill" style="width:{width}%;background:{color}"></div></div></div>'
    )


def _report_html(report) -> str:
    pal = _palette()
    mem, perf = report.memory, report.performance
    gap = mem - perf
    gcol = _gap_color(gap)
    pos = max(2, min(98, round((report.readiness - 472) / 56 * 100)))

    # Gap stat: bar width shows the magnitude of the gap.
    gap_stat = (
        f'<div class="stat card"><div class="stat-top"><span class="dot" '
        f'style="background:{gcol}"></span>Gap</div>'
        f'<div class="stat-val" style="color:{gcol}">{gap * 100:+.0f}%</div>'
        f'<div class="track"><div class="fill" style="width:{min(100, round(abs(gap) * 100))}%;'
        f'background:{gcol}"></div></div></div>'
    )

    rows = ""
    for s in report.sections:
        s_gap = s.memory - s.performance
        c = _gap_color(s_gap)
        rows += (
            "<tr>"
            f"<td>{s.section}</td>"
            f"<td>{s.memory * 100:.0f}%</td>"
            f"<td>{s.performance * 100:.0f}%</td>"
            f'<td><span class="pill" style="color:{c};background:{c}22">{s_gap * 100:+.0f}%</span></td>'
            f"<td>{s.score} <span class='muted'>({s.score_low}&ndash;{s.score_high})</span></td>"
            f"<td>{s.coverage * 100:.0f}%</td>"
            "</tr>"
        )

    reasons = "".join(
        f"<li>{r}</li>" for r in report.reasons if "give" not in r.lower()
    )
    reasons_block = (
        f'<div class="section-title">Why this score</div><div class="reasons card"><ul>{reasons}</ul></div>'
        if reasons
        else ""
    )

    give_up = ""
    if report.give_up_concept_ids:
        n = len(report.give_up_concept_ids)
        give_up = (
            f'<div class="giveup"><b>Ease off {n} concept'
            f'{"s" if n != 1 else ""}</b> &mdash; lots of attempts, still not clicking.</div>'
        )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{_css(pal)}</style></head><body><div class="wrap">
  <div class="hero">
    <div class="eyebrow">PREDICTED MCAT SCORE</div>
    <div class="score">{report.readiness}</div>
    <div class="range">Likely range {report.readiness_low}&ndash;{report.readiness_high}</div>
    <div class="scale"><div class="marker" style="left:{pos}%"></div></div>
    <div class="ticks"><span>472</span><span>500</span><span>528</span></div>
  </div>
  <div class="stats">
    {_stat("Memory", mem, _MEMORY)}
    {_stat("Performance", perf, _PERFORMANCE)}
    {gap_stat}
  </div>
  <div class="section-title">By section</div>
  <div class="card" style="overflow:hidden">
    <table><thead><tr>
      <th>Section</th><th>Memory</th><th>Perf.</th><th>Gap</th><th>Score</th><th>Cov.</th>
    </tr></thead><tbody>{rows}</tbody></table>
  </div>
  {reasons_block}
  {give_up}
</div></body></html>"""


def show_dashboard(mw: AnkiQt) -> None:
    if mw.col is None:
        showWarning("Open a collection first.")
        return
    try:
        report = mw.col._backend.readiness_report()
    except Exception as exc:  # pragma: no cover - defensive
        showWarning(f"Could not build the readiness report: {exc}")
        return

    from aqt.webview import AnkiWebView, AnkiWebViewKind

    dialog = QDialog(mw)
    dialog.setWindowTitle("Speedrun - Readiness")
    dialog.resize(740, 780)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    web = AnkiWebView(parent=dialog, title="Speedrun Readiness", kind=AnkiWebViewKind.DEFAULT)
    web.setHtml(_report_html(report))
    layout.addWidget(web, 1)

    buttons = QDialogButtonBox()
    buttons.setContentsMargins(12, 8, 12, 10)
    study = QPushButton("Study highest-gap concept")
    buttons.addButton(study, QDialogButtonBox.ButtonRole.ActionRole)
    close = buttons.addButton(QDialogButtonBox.StandardButton.Close)

    def _study() -> None:
        from aqt.transfer_reviewer import open_transfer_reviewer

        dialog.accept()
        open_transfer_reviewer(mw)

    qconnect(study.clicked, _study)
    qconnect(close.clicked, dialog.reject)
    qconnect(dialog.finished, lambda _code: web.cleanup())
    layout.addWidget(buttons)
    dialog.show()


def add_dashboard_action(mw: AnkiQt) -> None:
    """Add a 'Speedrun Dashboard' item to the Tools menu."""
    action = QAction("Speedrun Dashboard", mw)
    action.setObjectName("actionSpeedrunDashboard")
    qconnect(action.triggered, lambda: show_dashboard(mw))
    mw.form.menuTools.addAction(action)
