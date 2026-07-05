# Speedrun — Demo / Recording Script (read-aloud)

How to use this: **DO** = what to click or run. **SAY** = read it aloud while you do it.
Go top to bottom. Total ~4–5 min. (AI is a Friday item, so the Wednesday recording stays AI-free.)

Before you start: have a terminal open at `C:\dev\speedrun-anki`, and the Android emulator
booted with AnkiDroid installed.

---

## 0. One-liner intro (10 sec) — say to camera
**SAY:** "This is Speedrun — an MCAT study app I built by forking Anki and changing its core
Rust engine. Anki's FSRS already nails one thing: memory — *will you recall a fact.* But a real
exam needs two harder things: can you *use* that fact on a brand-new question, and are you
*actually ready.* Those two bridges are what I built, and every piece is grounded in learning
science."

---

## 1. The engine change + clean build  ▶ (Recording 1)
**DO:**
```powershell
cd C:\dev\speedrun-anki
git log -1 --format="%H"
.\run.bat
```
**SAY (while it compiles):** "My change lives in Anki's **Rust engine**, not just the Python
screens — new tables, a transfer model, and new RPCs under `rslib/src/speedrun`. It's in Rust on
purpose: it's fast, and the *same* engine ships to both desktop and phone. This is building the
whole thing from source right now."
**SAY (when Anki opens):** "And there's the forked app running."

---

## 2. The dashboard — three scores + the "illusion of mastery" gap
**DO:** Tools ▸ **Speedrun Dashboard**
**SAY:** "Three *separate* scores, because they're three different questions. **Memory (R)** —
recall, straight from FSRS. **Performance (T)** — can you solve a *novel* exam-style problem,
modeled with a 1-PL IRT / Elo update. **Readiness** — T scaled onto the real 472–528 MCAT scale
with a confidence band."
**SAY (point at G):** "The headline number is **G = R − T** — the *illusion of mastery* gap. High
recall but low transfer means you memorized the wording, not the concept. The learning science
here: people are terribly *miscalibrated* about their own learning — the feeling of knowing isn't
knowing — so I don't trust that feeling, I *measure* the gap and study the biggest one first."
**SAY (if it shows no score / low coverage):** "Right now it *abstains* on readiness because I
haven't logged enough graded answers yet — that's the **give-up rule**. An honest 'not enough data'
beats a confident guess in a nice font. As I study, R and readiness fill in."

---

## 3. Transfer Review — measuring performance, not memory
**DO:** Tools ▸ **Speedrun: Transfer Review** → read an item → pick an answer → see the result → Next.
**SAY:** "This is where **performance** is measured — exam-style questions along a difficulty
ladder, L0 definition up to L5 full passage (that's *desirable difficulty* — you don't measure
transfer at a single point). Every graded answer updates that concept's transfer ability with an Elo-style
update. And the score comes from these *machine-checkable* answers — **not** from me clicking
'Good.' The student is the least reliable sensor in the loop."

---

## 4. The study feature: interleaving (tested with an ablation)
**SAY:** "The study feature I chose is **interleaving** — mixing related concepts in a session
instead of blocking one topic at a time. Blocked practice *feels* more efficient but it hurts
transfer. I didn't just assert that — I ran an **ablation**: with an order-agnostic learner
interleaving made *no* difference (no free lunch, exactly as expected), but with a forgetting
learner it improved transfer by about **+0.28, confidence interval excluding zero**. A fair test
that could have shown 'no effect' — and that's a real result either way."

---

## 5. Tests + engine harnesses  ▶ (Recording 2)
**DO:**
```powershell
.\speedrun\wednesday_proof.ps1
```
**SAY:** "The Rust change is covered by **16 unit tests** plus Python tests that call it through the
backend, and then the harnesses: the **transfer model is calibrated** — it beats the baselines,
including a difficulty-only baseline, so it's really *learning ability*, not just knowing the question
difficulty; the **memory model (FSRS recall) is separately calibrated** on held-out reviews (Brier /
log-loss + a reliability table); a **hard-kill crash-recovery** test; the interleaving ablation; and a
soak test. All green — and anyone can re-run this one command."

---

## 6. One engine, on the phone  ▶ (Recording 4)
**DO:** switch to the emulator → open **AnkiDroid** → open a deck → **study a card**: front →
**Show answer** → **Good** → show the count change (`1 0 0` → `0 1 0`).
**SAY:** "Same engine on mobile. This is AnkiDroid built on my *forked Rust backend* — the exact
same scheduler and Speedrun engine as desktop, compiled into the app. Reviewing here runs on that
shared engine, and my exam deck (MileDown) is loaded on the desktop side, so both apps review the
same material."

---

## 7. It ships — installer on a clean machine  ▶ (Recording 3)
**DO:** on a fresh Windows VM, run `anki-26.05-win-x64.msi` → install → launch → **Help ▸ About**
shows `26.05-speedrun` → open **Tools ▸ Speedrun Dashboard**.
**SAY:** "And it packages into a real Windows installer that runs on a clean machine."

---

## Learning-science cheat-sheet (what changed vs. plain Anki, and why)
- **Anki/FSRS = memory (spacing + retrieval practice).** I kept it and *inherited* R from it.
- **New: Transfer (T).** Measures application on novel items — *transfer-appropriate processing*,
  the thing memory alone doesn't predict. (`rslib/src/speedrun/mod.rs`, Elo/IRT.)
- **New: G = R − T.** Operationalizes the *metacognitive miscalibration* / illusion of mastery.
- **Don't trust the grade button.** Scores anchor on machine-graded answers, not self-report.
- **Interleaving** as the study feature, validated by an *ablation* (the honest test).
- **Difficulty ladder L0–L5** = desirable difficulties; measure transfer across a gradient.
- **Give-up rule + confidence band** = honest uncertainty; abstain without enough data.
- **AI items are gold-set gated** (Friday): a raw model output never touches the score.
