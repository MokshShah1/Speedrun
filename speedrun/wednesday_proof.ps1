# Speedrun - Wednesday proof runner.
# Run from the repo root:   .\speedrun\wednesday_proof.ps1
# Records: the commit hash + the full test suite + the engine harnesses.
# (The clean-machine install and the phone review are separate screen recordings.)

$ErrorActionPreference = "Continue"
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
$PY = "out\pyenv\Scripts\python.exe"

function Section($t) { Write-Host "`n=============== $t ===============" -ForegroundColor Cyan }

Section "1. COMMIT (put this hash in your submission)"
git log -1 --format="commit %H%nauthor %an <%ae>%n%s"
".version = " + (Get-Content .version)

Section "2. RUST ENGINE CHANGE - unit tests (should be 16 passed)"
cargo test -p anki --lib speedrun::

Section "3. PYTHON - AI + eval unit tests"
& $PY -m pytest speedrun\eval\test_eval.py speedrun\ai\test_ai.py -q

Section "4. PYTHON - pylib backend tests (Rust engine called from Python)"
$env:PYTHONPATH = "out\pylib"
& $PY -m pytest pylib\tests\test_speedrun.py pylib\tests\test_speedrun_sync.py -q
$env:PYTHONPATH = ""

Section "5. ENGINE HARNESSES (perf, crash-recovery, calibration, interleaving, soak, tagger)"
& $PY speedrun\eval\bench.py
& $PY speedrun\eval\crash_kill.py
& $PY speedrun\eval\calibration.py
& $PY speedrun\eval\interleaving.py
& $PY speedrun\eval\soak.py
& $PY speedrun\tag_deck.py --self-test

Write-Host "`n=============== PROOF RUN COMPLETE ===============" -ForegroundColor Green
Write-Host "Each section above prints its own PASS/'<n> passed'. Screen-record this whole run." -ForegroundColor Green
