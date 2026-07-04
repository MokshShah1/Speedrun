# Speedrun - Friday proof runner.
# Run from the repo root:   .\speedrun\friday_proof.ps1
# Covers the two Friday pillars that can be shown headlessly:
#   (A) AI added & checked: held-out gold-set eval beats the baseline, + leakage.
#   (B) Transfer-log sync: two devices converge, idempotent, offline-then-sync.
# The live phone<->desktop recording is a separate screen capture (see
# speedrun\FRIDAY_SUBMISSION.md).

$ErrorActionPreference = "Continue"
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
$PY = "out\pyenv\Scripts\python.exe"

function Section($t) { Write-Host "`n=============== $t ===============" -ForegroundColor Cyan }

Section "1. COMMIT (put this hash in your submission)"
git log -1 --format="commit %H%nauthor %an <%ae>%n%s"

Section "2. AI - held-out gold-set eval vs baseline (the Friday headline number)"
& $PY -m speedrun.ai.run_eval

Section "3. AI - pipeline unit tests (provider, checker, leakage, generate, eval)"
& $PY -m pytest speedrun\ai\test_ai.py -q

Section "3b. AI - live items drive the engine with AI OFF (traceability + scores)"
& $PY -m speedrun.ai.prove_ai_off

Section "4. SYNC ENGINE - Rust unit tests (merge/converge/idempotent/replay)"
cargo test -p anki --lib speedrun::sync::

Section "5. SYNC - two-device transfer-log sync over real HTTP"
Write-Host "(spins up the transfer-sync server on an ephemeral port, drives two collections)"
& $PY -m speedrun.sync.test_transfer_sync

Section "6. SYNC - pylib two-device convergence (engine called from Python)"
$env:PYTHONPATH = "out\pylib"
& $PY -m pytest pylib\tests\test_speedrun_sync.py -q
$env:PYTHONPATH = ""

Section "7. LATENCY - p50/p95 of the hot paths (engine scores, transfer round-trip, sync)"
Write-Host "(warm-up + monotonic timer over a temp collection; cold vs warm where it matters)"
& $PY -m speedrun.bench.latency

Write-Host "`n=============== FRIDAY PROOF RUN COMPLETE ===============" -ForegroundColor Green
Write-Host "Then screen-record the live phone<->desktop sync per speedrun\FRIDAY_SUBMISSION.md." -ForegroundColor Green
