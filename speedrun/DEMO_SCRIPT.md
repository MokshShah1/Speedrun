# Speedrun — Sunday demo video script (read-aloud)

3–5 minutes, every required element in order. **DO** = what to click/run.
**SAY** = read aloud while you do it. Record each clip separately and stitch them.

Required elements (Section 12) and where they land: Rust change (Clip 2), three
scores with ranges (Clip 3), AI features (Clip 5), review session + phone→desktop
sync (Clip 6), test results (Clip 7).

---

## PREP (before recording)

1. Terminal at `C:\dev\speedrun-anki`.
2. **Seed a video-ready collection** so the dashboard shows real scores (with
   desktop Anki **closed**):
   ```powershell
   python speedrun\demo_seed.py "$env:APPDATA\Anki2\User 1\collection.anki2"
   ```
   This produces ~68% coverage, Memory ≈ 67% > Performance ≈ 41% (a real
   illusion-of-mastery gap), Readiness ≈ 495 with a range. Without it the
   dashboard correctly shows "No score yet" (the abstention rule).
3. Start desktop Anki: `.\run.bat`.
4. Two sync servers up: `python -m anki.syncserver` (8080) and
   `python -m speedrun.sync.transfer_sync_server --port 8090 --data out\transfer-log.json`.
5. Emulator booted, AnkiDroid pointed at `http://10.0.2.2:8080/`, logged in.
6. logcat ready: `adb logcat | findstr Speedrun`.

---

## Clip 1 — Intro + what changed since the MVP (~25s) — to camera
**SAY:** "This is Speedrun — an MCAT app I built by forking Anki and changing its
core Rust engine. Since the Wednesday MVP I added three things: an **AI item
pipeline that's checked before anything reaches a student**, **two-way
phone–desktop sync**, and **calibrated models** for all three scores. Anki's FSRS
already handles memory; I built the two harder bridges — can you *use* a fact, and
are you *actually ready* — and I can prove each one."

## Clip 2 — The Rust engine change *(required)* (~30s)
**DO:** `git log -1 --format="%H"` (optionally show `.\run.bat` compiling → Anki opens → Help ▸ About = `26.05-speedrun`).
**SAY:** "My change lives in Anki's **Rust engine** — `rslib/src/speedrun`: new
tables, a transfer model, new protobuf RPCs, all transactional and undoable. It's
in Rust on purpose — it's fast, and the *same* compiled engine ships to both
desktop and phone."

## Clip 3 — Three scores with ranges + the G gap *(required)* (~60s)
**DO:** Tools ▸ **Speedrun Dashboard**.
**SAY:** "Three *separate* scores, because they're three different questions.
**Memory (R)** — recall, from FSRS. **Performance (T)** — can you solve a *novel*
exam-style question, modeled with a 1-PL IRT / Elo update. **Readiness** — T mapped
onto the real 472–528 scale, and it's a **range, not one number** — the band
widens as coverage drops."
**SAY (point at Gap):** "The headline is **G = R − T**, the illusion of mastery —
here memory is 67% but performance is 41%, so there's a real gap: I recognize this
material but can't yet *use* it. The app tells me exactly where to start."
**SAY (honesty rule):** "And it **refuses to guess** — below 50 graded answers and
25% coverage it shows *'No score yet'* with what's missing. An honest 'not enough
data' beats a confident guess in a nice font."

## Clip 4 — Transfer Review: measuring performance, not memory (~30s)
**DO:** Tools ▸ **Speedrun: Transfer Review** → read an item → answer → result → Next.
**SAY:** "This is where **performance** is measured — exam-style questions along a
difficulty ladder, L0 definition up to L5 full passage. Every graded answer updates
that concept's transfer ability. The score anchors on *machine-checkable* answers,
not on me clicking 'Good' — the student is the least reliable sensor in the loop."

## Clip 5 — AI: generated, checked, beats a baseline, works with AI off *(required)* (~45s)
**DO:** `out\pyenv\Scripts\python.exe -m speedrun.ai.run_eval`
**SAY:** "AI generates transfer questions from a **named source**, but a raw model
output never touches the score — every item clears a mechanical **checker** and a
**leakage scan** first. On a 50-item held-out gold set the checker hits **1.000
accuracy versus 0.500** for accept-all, with cutoffs committed before I looked."
**DO:** `out\pyenv\Scripts\python.exe -m speedrun.ai.prove_ai_off`
**SAY:** "And it still scores with **AI switched off** — live-generated items, each
traceable to a concept, ladder level, and source, driving the engine with the AI
provider disabled. The model helps *make* questions; it never *grades* you."

## Clip 6 — One engine, phone → desktop sync + review session *(required)* (~50s)
**DO:** On the **emulator**: open a deck → review 1–2 cards (Show Answer → Good) → back → tap **↻ Sync**.
**SAY:** "Same engine on mobile — AnkiDroid built on my *forked Rust backend*. I
reviewed cards on the phone and synced."
**DO:** On **desktop Anki**: click **↻ Sync** → open the deck / Browse → show the reviews from the phone.
**SAY:** "Sync the desktop and the phone's reviews show up here — two-way, nothing
lost or double-counted because the transfer log is append-only and merged by unique
ID. It works offline too, then syncs when the connection returns."
**DO (optional, point at logcat):** "And the phone computes all three scores
**on-device** with that shared engine — here in the log."

## Clip 7 — Test results: re-runnable *(required)* (~30s)
**DO:** `out\pyenv\Scripts\python.exe speedrun\eval\paraphrase.py` (fast; don't run the full 5-min suite on camera).
**SAY:** "None of this is a promise — it's re-runnable. One command,
`sunday_proof.ps1`, runs **all 15 headless proofs** and prints PASS/FAIL: memory
calibration, transfer calibration, this paraphrase test proving performance isn't
just memory, the interleaving ablation, crash recovery, sync, benchmarks — all
green. And `SUBMISSION.md` maps every rubric item to the exact file and command."

## Clip 8 — Close (~10s)
**SAY:** "One exam, two apps on one Rust engine, three honest scores I can back up —
memory and performance both calibrated, AI that's checked before it's trusted, and
a readiness number that knows when to stay quiet. Thanks for watching."

---

## Learning-science cheat-sheet (what changed vs. plain Anki, and why)
- **Anki/FSRS = memory** (spacing + retrieval practice). Kept and *inherited* as R.
- **New: Transfer (T)** — application on novel items (transfer-appropriate
  processing), what memory alone doesn't predict. (`rslib/src/speedrun/mod.rs`.)
- **New: G = R − T** — operationalizes metacognitive miscalibration / illusion of mastery.
- **Don't trust the grade button** — scores anchor on machine-graded answers.
- **Interleaving** as the study feature, validated by an *ablation* across 3 builds.
- **Difficulty ladder L0–L5** = desirable difficulties; transfer across a gradient.
- **Give-up rule + abstention** = honest uncertainty; no score without enough data.
- **AI items are gold-set gated** — a raw model output never touches the score.
