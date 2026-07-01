# Speedrun on Android (Phase 5) — turn-key build kit

Goal: run **AnkiDroid on top of our forked engine**, so the phone and desktop
share the exact same Rust backend (and therefore the same Speedrun transfer
engine, scores, and sync). This is the "desktop + mobile on a shared engine"
bar.

This kit is everything that can be prepared without an Android device. The steps
you run need Android Studio + an emulator/device; everything else is scripted or
spelled out.

---

## How it fits together

```
AnkiDroid (Kotlin app)
   │  depends on
   ▼
Anki-Android-Backend  ──►  produces anki-android-backend.aar
   │  has `anki/` as a git SUBMODULE                     │
   ▼                                                     │ contains
our fork's rslib (the Speedrun engine)  ─────────────────┘  Rust compiled for
                                                            Android + Kotlin/JNI
                                                            bindings generated
                                                            from our .proto
```

Two facts make this work in our favour:

1. **The backend wraps `rslib` via a git submodule.** To put Speedrun on the
   phone we just point that submodule at our fork's `speedrun` branch and build
   the `.aar`. No backend source changes needed.
2. **Bindings are generated from the `.proto` at build time.** Because we added
   `proto/anki/speedrun.proto`, the backend build emits Kotlin/JNI bindings for
   `UpsertConcept`, `RecordTransferReview`, `MasteryQuery`, `ReadinessReport`,
   `ExportTransferLog`, `ImportTransferLog`, etc. **automatically** — the
   Speedrun RPCs become callable from Kotlin with zero extra wiring.

So "normal AnkiDroid review runs" already proves the shared engine, and the
Speedrun RPCs are additionally available to call.

---

## Versions (pinned, verified against the backend repo)

| thing                    | value                                   | note                                                           |
| ------------------------ | --------------------------------------- | -------------------------------------------------------------- |
| Rust toolchain           | **1.92.0**                              | matches our fork's `rust-toolchain.toml` exactly — no mismatch |
| NDK                      | **29.0.14206865**                       | from backend `gradle/libs.versions.toml`                       |
| compileSdk / targetSdk   | 36                                      |                                                                |
| minSdk                   | 23                                      |                                                                |
| backend build entrypoint | `cargo run -p build_rust` (`build.bat`) | downloads target libs + builds `.aar`                          |

## Prerequisites

You already have from Phase 0: **Rust 1.92.0, MSVC, MSYS2 (`git`, `rsync`) on
PATH, N2**. New things to install:

- **Android Studio** (latest stable) + Android SDK.
- **NDK 29.0.14206865** (install via SDK Manager → SDK Tools → check "show
  package details", or command line — see step 3).
- **JDK**: use the one bundled with Android Studio (no separate install).
- **An x86_64 emulator** (AVD) or an arm64 device with USB debugging. (x86_64
  emulator is the smoothest on a Windows PC.)
- Rust Android targets — the `build_speedrun_backend.ps1` script adds these.

---

## Steps

> Scripts live next to this file. Run them from a PowerShell where `cargo` and
> `c:\msys64\usr\bin` are on `PATH` (same shell you used for the desktop build).

### 1. Clone the two AnkiDroid repos side by side

They must sit in the same parent folder and **`Anki-Android-Backend` must keep
that exact name** (hard-coded in AnkiDroid's gradle):

```powershell
mkdir C:\dev\ankidroid ; cd C:\dev\ankidroid
git clone https://github.com/ankidroid/Anki-Android.git
git clone https://github.com/ankidroid/Anki-Android-Backend.git
cd Anki-Android-Backend
git submodule update --init --recursive
```

### 2. Point the backend's `anki` submodule at our fork, and build the `.aar`

Run the kit script (edit the `$Fork`/`$BackendRepo` variables at the top if your
paths differ):

```powershell
C:\dev\speedrun-anki\speedrun\android\build_speedrun_backend.ps1
```

It will: add our local fork as a git remote inside the `anki` submodule, fetch
and check out the `speedrun` branch, add the Rust Android targets, set
`ANDROID_HOME`/`ANDROID_NDK_HOME`, refresh `Cargo.lock` (`cargo check`), and run
the backend build (`cargo run -p build_rust`). On success the `.aar` is under
`Anki-Android-Backend/` (the script prints the path).

### 3. (If you skipped the script) install the NDK and set env manually

```powershell
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_NDK_VERSION = "29.0.14206865"
$env:ANDROID_NDK_HOME = "$env:ANDROID_HOME\ndk\$env:ANDROID_NDK_VERSION"
& "$env:ANDROID_HOME\cmdline-tools\latest\bin\sdkmanager.bat" --install "ndk;$env:ANDROID_NDK_VERSION"
$env:PATH += ";c:\msys64\usr\bin"
```

### 4. Tell AnkiDroid to use the locally-built backend

In the **Anki-Android** repo, edit `local.properties` and add:

```
local_backend=true
```

Then make the versions match: compare
`Anki-Android-Backend/gradle.properties` → `BACKEND_VERSION` with
`Anki-Android/AnkiDroid/build.gradle` → `ext.ankidroid_backend_version`. If they
differ, set AnkiDroid's value to the backend's.

### 5. Build & run AnkiDroid on the emulator/device

Open **Anki-Android** in Android Studio, let gradle sync (cargo must be on PATH —
launch Studio from the same shell if it complains), then Run on your x86_64
emulator (or arm64 device).

**Proof of the shared engine:** import the MileDown `.apkg` and do a normal
review. AnkiDroid is now running entirely on our forked Rust backend.

### 6. Prove the Speedrun RPCs are live (optional, no device needed)

The backend also builds a host `.jar` for Robolectric/JVM tests. Drop the
template test in `speedrun/android/SpeedrunBackendTest.kt` into the backend's
JVM test sources and run it (`./gradlew test`) to call `upsertConcept` /
`recordTransferReview` / `readinessReport` directly on the host — proving the
Speedrun engine is compiled into the Android backend without needing a phone.

---

## Copy-paste checklist

- [ ] Android Studio + SDK installed; x86_64 emulator created (or arm64 device).
- [ ] NDK `29.0.14206865` installed.
- [ ] `Anki-Android` and `Anki-Android-Backend` cloned in the same parent folder.
- [ ] `git submodule update --init --recursive` done in the backend.
- [ ] `build_speedrun_backend.ps1` run → `.aar` produced from the `speedrun` branch.
- [ ] `local_backend=true` in `Anki-Android/local.properties`.
- [ ] `BACKEND_VERSION` == `ext.ankidroid_backend_version`.
- [ ] AnkiDroid builds & runs on the emulator/device.
- [ ] MileDown `.apkg` imported; a card reviewed (shared engine confirmed).
- [ ] (optional) `SpeedrunBackendTest.kt` green (Speedrun RPCs confirmed on Android backend).
- [ ] Screen recording of the phone review captured (Wednesday artifact).

---

## Troubleshooting

- **`cargo not found` during gradle sync** — Android Studio didn't inherit PATH.
  Close it and relaunch from a shell where `cargo` works.
- **Rust target errors** — run `rustup target add aarch64-linux-android
  armv7-linux-androideabi x86_64-linux-android i686-linux-android` (the script
  does this).
- **NDK mismatch** — the version in `gradle/libs.versions.toml` is authoritative;
  install that exact one.
- **`rsync`/`git` missing in build** — ensure `c:\msys64\usr\bin` is on PATH.
- **Version mismatch error at app build** — re-check step 4's two version values.
- **Submodule reverted to upstream commit** — re-run the checkout in
  `build_speedrun_backend.ps1`; a `git submodule update` can reset it.

## What needs you vs done here

- **Prepared (no device):** architecture, exact versions, the submodule-repoint
  build script, the AnkiDroid wiring steps, the host-JVM proof test, and this
  checklist.
- **Needs your machine:** installing Android Studio/NDK, running the emulator,
  the actual `.aar` + APK build, importing MileDown, and the screen recording.
