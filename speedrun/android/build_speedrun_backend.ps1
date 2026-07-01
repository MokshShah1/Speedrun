# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

# Build the Anki-Android-Backend .aar from our Speedrun fork.
#
# Points the backend's `anki` git submodule at this fork's `speedrun` branch
# (added as a LOCAL remote, so no GitHub push is required), aligns the Rust
# Android targets and NDK env, then runs the backend build. The resulting .aar
# contains our Speedrun engine and the Kotlin/JNI bindings generated from
# proto/anki/speedrun.proto.
#
# Run from a PowerShell where `cargo` works and c:\msys64\usr\bin is on PATH.

$ErrorActionPreference = "Stop"

# --- Edit these if your paths differ ------------------------------------------
$Fork        = "C:\dev\speedrun-anki"          # this repository
$ForkBranch  = "speedrun"                       # branch holding the engine
$BackendRepo = "C:\dev\ankidroid\Anki-Android-Backend"
$AndroidHome = "$env:LOCALAPPDATA\Android\Sdk"
$NdkVersion  = "29.0.14206865"                  # from gradle/libs.versions.toml
# ------------------------------------------------------------------------------

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

if (-not (Test-Path $BackendRepo)) {
    throw "Backend repo not found at $BackendRepo. Clone ankidroid/Anki-Android-Backend there first (see ANDROID.md step 1)."
}
$ankiSub = Join-Path $BackendRepo "anki"
if (-not (Test-Path $ankiSub)) {
    throw "anki submodule missing. Run: git -C `"$BackendRepo`" submodule update --init --recursive"
}

Step "Checking toolchain"
cargo --version
$ndkHome = Join-Path $AndroidHome "ndk\$NdkVersion"
if (-not (Test-Path $ndkHome)) {
    Write-Warning "NDK $NdkVersion not found at $ndkHome. Install it (ANDROID.md step 3) before the build will succeed."
}
$env:ANDROID_HOME = $AndroidHome
$env:ANDROID_NDK_HOME = $ndkHome
$env:ANDROID_NDK_VERSION = $NdkVersion
if ($env:PATH -notlike "*msys64*") { $env:PATH += ";c:\msys64\usr\bin" }

Step "Adding Rust Android targets"
rustup target add aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android

Step "Pointing the anki submodule at the Speedrun fork ($ForkBranch)"
Push-Location $ankiSub
try {
    # Add the local fork as a remote named 'speedrun' (idempotent).
    $remotes = git remote
    if ($remotes -notcontains "speedrun") {
        git remote add speedrun $Fork
    } else {
        git remote set-url speedrun $Fork
    }
    git fetch speedrun --tags
    git checkout "speedrun/$ForkBranch"
    # Nested submodules must be updated separately: `checkout --recurse-submodules`
    # can't fetch commits it doesn't have yet, but `submodule update` can.
    git submodule update --init --recursive
    Write-Host "anki submodule now at:" (git rev-parse --short HEAD)
} finally {
    Pop-Location
}

Step "Refreshing Cargo.lock against the fork"
Push-Location $BackendRepo
try {
    # No 2>&1 here: under Windows PowerShell 5.1 + $ErrorActionPreference=Stop,
    # redirecting native stderr turns cargo's progress output into fatal errors.
    cargo check | Out-Host

    Step "Building the backend .aar (cargo run -p build_rust)"
    # Set RELEASE=1 for an optimized build once a debug build is confirmed.
    cargo run -p build_rust | Out-Host

    Step "Done - locating .aar"
    $aars = Get-ChildItem -Recurse -Filter *.aar -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    if ($aars) {
        Write-Host "Newest .aar: $($aars[0].FullName)" -ForegroundColor Green
    } else {
        Write-Warning "No .aar found yet; check the build output above."
    }
} finally {
    Pop-Location
}

Write-Host "`nNext: set local_backend=true in Anki-Android\local.properties and match BACKEND_VERSION (see ANDROID.md step 4)." -ForegroundColor Yellow
