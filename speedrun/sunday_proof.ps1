# Speedrun - Sunday (final) proof runner.
# Run from the repo root:   .\speedrun\sunday_proof.ps1
#
# One command that re-runs EVERY headless proof behind the submission and prints
# a PASS/FAIL summary at the end, so a grader can verify the whole build without
# hunting. Each underlying script exits non-zero on regression, so this gates.
#
# What still needs a human (not headless): the 3-5 min demo video, the live
# phone<->desktop sync recording, and the clean-machine installer run. See
# speedrun\SUBMISSION.md for how those map to the rubric.

$ErrorActionPreference = "Continue"
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
$PY = "out\pyenv\Scripts\python.exe"

$results = [System.Collections.ArrayList]::new()
function Step($name, $script) {
    Write-Host "`n=============== $name ===============" -ForegroundColor Cyan
    & $script
    $ok = ($LASTEXITCODE -eq 0)
    [void]$results.Add([pscustomobject]@{ Step = $name; Result = if ($ok) { "PASS" } else { "FAIL" } })
}

Write-Host "COMMIT (put this hash in your submission):" -ForegroundColor Yellow
git log -1 --format="  %H  %s"

# --- AI: added, checked, beats a baseline, traceable, still scores with AI off ---
Step "AI 1/3 - held-out gold-set eval vs accept-all baseline (accuracy + cutoff)" { & $PY -m speedrun.ai.run_eval }
Step "AI 2/3 - pipeline unit tests (provider, CHECKER, LEAKAGE scanner, generate, eval)" { & $PY -m pytest speedrun\ai\test_ai.py -q }
Step "AI 3/3 - live items drive the engine with AI OFF (traceability + scores)" { & $PY -m speedrun.ai.prove_ai_off }

# --- Models: memory calibrated, performance calibrated, performance != memory ---
Step "MODEL 1/3 - MEMORY (FSRS recall) calibration on held-out reviews" { & $PY speedrun\eval\memory_calibration.py }
Step "MODEL 2/3 - PERFORMANCE (transfer) calibration, beats difficulty-only prior" { & $PY speedrun\eval\calibration.py }
Step "MODEL 3/3 - PARAPHRASE test (7d): performance T is not a copy of memory R" { & $PY speedrun\eval\paraphrase.py }

# --- Study feature: 3 builds (feature on / off / plain Anki), equal practice ---
Step "STUDY FEATURE - interleaving ablation, 3 builds (PRD section 8)" { & $PY speedrun\eval\interleaving.py }

# --- Engine change + sync: Rust tests, two-device convergence, offline-then-sync ---
Step "ENGINE - Rust unit tests (T/G/Elo, undo, gap queue, sync merge/replay)" { cargo test -p anki --lib speedrun:: }
Step "SYNC 1/2 - two-device transfer-log sync over real HTTP (7b)" { & $PY -m speedrun.sync.test_transfer_sync }
$env:PYTHONPATH = "out\pylib"
Step "SYNC 2/2 - pylib two-device convergence (engine called from Python)" { & $PY -m pytest pylib\tests\test_speedrun_sync.py -q }
$env:PYTHONPATH = ""

# --- Reliability + performance: crash recovery, soak/restart, benchmark, latency ---
Step "RELIABILITY 1/2 - hard-kill crash recovery, no corruption (7g)" { & $PY speedrun\eval\crash_kill.py }
Step "RELIABILITY 2/2 - 20x soak / restart durability" { & $PY speedrun\eval\soak.py }
Step "BENCH - one-command engine throughput floors (7h)" { & $PY speedrun\eval\bench.py }
Step "LATENCY - p50/p95 of the hot paths" { & $PY -m speedrun.bench.latency }

# --- Coverage / deck mapping ---
Step "COVERAGE - deck auto-tagger self-test (concept coverage, 7c)" { & $PY speedrun\tag_deck.py --self-test }

Write-Host "`n=============== SUMMARY ===============" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host
$fails = @($results | Where-Object { $_.Result -eq "FAIL" }).Count
if ($fails -eq 0) {
    Write-Host "ALL HEADLESS PROOFS PASSED." -ForegroundColor Green
} else {
    Write-Host "$fails step(s) FAILED - see output above." -ForegroundColor Red
}
Write-Host "Human-recorded proofs (see speedrun\SUBMISSION.md): demo video, live" -ForegroundColor Yellow
Write-Host "phone<->desktop sync, clean-machine installer run." -ForegroundColor Yellow
exit $fails
