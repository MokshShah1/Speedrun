# Speedrun — distributable Windows installer + clean-install proof

Reviewer feedback on the Wednesday MVP asked for a **clean-machine installer run**.
This doc records the real, shippable Windows artifact we build from this fork and a
reproducible clean-install proof that it runs **independently of the dev source tree**.

TL;DR:

- **Artifact:** a real Windows MSI — `out\installer\dist\anki-26.5-win-x64.msi`
  (**636,760,189 bytes ≈ 607 MB**), a self-contained Briefcase/WiX bundle with
  embedded Python 3.13 + Qt6/WebEngine and the Speedrun-forked `anki`/`aqt`.
- **Also produced:** the two Python wheels the MSI is built from
  (`anki` 12.05 MB, `aqt` 4.44 MB).
- **Clean-install tier reached: Tier B** — the built wheels install into a brand-new,
  isolated `venv` outside the repo (empty `PYTHONPATH`), the forked engine's Rust
  RPC runs from there, and the app boots from that venv. Additionally the MSI's own
  self-contained `Anki.exe` payload boots with **zero external Python** on this box.
  A true **Tier A** run (separate clean Windows VM) was **not** performed — no VM was
  available on this machine (see "What a grader still needs for Tier A").

---

## 1. Build commands and artifacts

The repo's packaging pipeline is Anki's upstream **Briefcase + WiX** flow, wired into
the build system as `configure/src/installer.rs` → ninja targets `installer:build`
and `installer:package`, driven by `qt/tools/build_installer.py`. It first needs the
two wheels.

### Environment shims (corporate TLS-intercepting proxy)

The corp proxy re-signs TLS with a private CA, so `uv`/`pip`/`briefcase` fail with
`invalid peer certificate: UnknownIssuer` when fetching from PyPI. `curl` works
because it uses the Windows cert store. We reproduce that by pointing the toolchain
at the **Windows root store**, exported to a PEM — the real CA, verification stays on
(no `--insecure`, no `verify=false`):

```powershell
# Export the Windows root CA store to a PEM bundle (one-time)
$certs = Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root
$lines = New-Object System.Collections.Generic.List[string]
foreach ($c in $certs) {
  $lines.Add("-----BEGIN CERTIFICATE-----")
  $lines.Add([Convert]::ToBase64String($c.RawData,'InsertLineBreaks'))
  $lines.Add("-----END CERTIFICATE-----")
}
Set-Content C:\dev\speedrun-anki\out\corp-ca-bundle.pem $lines -Encoding ascii

# Wire it into every fetcher used by the packaging steps
$env:UV_NATIVE_TLS      = "true"                                        # uv: use OS cert store
$ca = "C:\dev\speedrun-anki\out\corp-ca-bundle.pem"
$env:SSL_CERT_FILE      = $ca      # briefcase/requests, stdlib ssl
$env:REQUESTS_CA_BUNDLE = $ca      # requests (briefcase downloads)
$env:PIP_CERT           = $ca      # pip (briefcase's app-requirements install)
$env:NODE_EXTRA_CA_CERTS= $ca      # node, if any web step runs
```

`UV_NATIVE_TLS=true` alone is enough for the wheels; the PEM is needed for the
Briefcase step (it uses `requests`/`pip` under the hood).

### Step 1 — build the wheels

```powershell
cd C:\dev\speedrun-anki
$env:UV_NATIVE_TLS = "true"
tools\ninja wheels
```

Produces (real PEP440 version is `26.5`; internal `anki.buildinfo.version` stays
`26.05-speedrun`):

| wheel | path | size |
| --- | --- | --- |
| anki  | `out\wheels\anki-26.5-cp310-abi3-win_amd64.whl` | 12,640,375 B (≈12.05 MB) |
| aqt   | `out\wheels\aqt-26.5-py3-none-any.whl`          | 4,657,249 B  (≈4.44 MB)  |

### Step 2 — build + package the installer

The ninja targets `installer:build` / `installer:package` exist and are the
supported path, **but** they pass the raw `.version` string (`26.05-speedrun`) to
Briefcase, which rejects it as non-PEP440 (`Version number ... is not valid`). Rather
than edit the committed `.version`, we invoke the same script `build_installer.py`
directly with the normalized version `26.5` (this is a pure build invocation — no
source change). The wheels on disk already carry `26.5`.

```powershell
cd C:\dev\speedrun-anki
# (env shims from above must be set)

# 2a. Build the self-contained app bundle (downloads PyQt6/Qt6/WebEngine + support)
out\pyenv\scripts\python.exe qt\tools\build_installer.py --version 26.5 build `
  --aqt_wheel  out\wheels\aqt-26.5-py3-none-any.whl `
  --anki_wheel out\wheels\anki-26.5-cp310-abi3-win_amd64.whl

# 2b. Package it into the MSI (Briefcase downloads/uses WiX; ad-hoc signed)
out\pyenv\scripts\python.exe qt\tools\build_installer.py --version 26.5 package
```

Produces:

| artifact | path | size |
| --- | --- | --- |
| **Windows MSI installer** | `out\installer\dist\anki-26.5-win-x64.msi` | **636,760,189 B ≈ 607 MB** |
| self-contained app bundle | `out\installer\build\anki\windows\app\src\` (launcher `Anki.exe`) | full app dir w/ embedded Python + Qt |

> If you set `.version` to a PEP440 value (e.g. `26.5` or `26.5+speedrun`) before
> configuring, `tools\ninja installer:package` builds the MSI end-to-end with no
> direct-script invocation. We kept `.version` untouched per the "don't modify
> committed source to force packaging" constraint.

---

## 2. Clean-install proof — Tier B (achieved)

Goal: prove the built wheels install and run in a **brand-new isolated environment**,
with the dev source tree **not** on the path.

```powershell
# Fresh venv OUTSIDE the repo, from a standalone base interpreter (not out\pyenv)
$base = "$env:APPDATA\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe"
& $base -m venv C:\cleanroom\venv

$env:PYTHONPATH = ""                 # nothing from the source tree
$ca = "C:\dev\speedrun-anki\out\corp-ca-bundle.pem"
$py = "C:\cleanroom\venv\Scripts\python.exe"

# Install the two built wheels (pulls PyQt6/Qt6/WebEngine etc. from PyPI via the corp CA)
& $py -m pip install --cert $ca `
  "C:\dev\speedrun-anki\out\wheels\aqt-26.5-py3-none-any.whl[qt,audio]" `
  "C:\dev\speedrun-anki\out\wheels\anki-26.5-cp310-abi3-win_amd64.whl"
```

Result: `Successfully installed anki-26.5 aqt-26.5 ...` (PyQt6 6.11, WebEngine,
anki-audio, flask, etc. — 38 packages).

### Proof it's the Speedrun fork, running from the venv (not the repo)

Run from `C:\` with `PYTHONPATH` empty:

```powershell
& $py -c "import anki, aqt, anki.buildinfo as b; print(b.version); import aqt.speedrun as s; print(s.__file__)"
# 26.05-speedrun
# C:\cleanroom\venv\Lib\site-packages\aqt\speedrun.py
```

- `version = 26.05-speedrun` — the fork, not stock Anki.
- `aqt.speedrun` / `aqt.transfer_reviewer` (the Speedrun Dashboard + Transfer Review
  UI) load from **`C:\cleanroom\venv\Lib\site-packages\`** — definitively the venv.

### Proof the compiled Rust engine runs from the clean install

```powershell
& $py -c "import tempfile,os; from anki.collection import Collection; d=tempfile.mkdtemp(); c=Collection(os.path.join(d,'col.anki2')); print(c._backend.readiness_report()); c.close()"
# ReadinessResponse readiness: 472  readiness_low: 472  readiness_high: 504
#   reasons: "Coverage 0% - 0 of 0 concepts have transfer data."
```

The Speedrun `readiness_report` RPC — implemented in the forked Rust `rslib` and
compiled into `_rsbridge.pyd` inside the wheel — executes end-to-end from the fresh
venv. This is a real functional run of the fork's engine with no source tree present.

### Proof the GUI app boots from the venv

Launched with an **isolated base** (`-b C:\cleanroom\anki-base`) and a unique
`ANKI_SINGLE_INSTANCE_KEY` (so it can't touch/relaunch a real Anki instance):

```
Starting Anki 26.05-speedrun...
```

The process initializes Qt + the profile subsystem and writes `prefs21.db` + `logs`
into the isolated base, then sits on the first-run profile manager (expected on a
brand-new base) without crashing. It is terminated after confirmation — no blocking
GUI is left running.

**Launch/latency signal:** process start → profile DB ready = **~2287 ms (≈2.3 s)**
in the warm venv; still alive 2 s later; then killed cleanly.

### Bonus — the MSI's self-contained payload boots with zero external Python

The installer's bundled launcher runs the embedded interpreter + Qt with no reliance
on any system/dev Python:

```powershell
$env:ANKI_SINGLE_INSTANCE_KEY = "speedrun-bundle-verify"
& "C:\dev\speedrun-anki\out\installer\build\anki\windows\app\src\Anki.exe" -b C:\cleanroom\bundle-base
# -> writes prefs21.db + logs into the isolated base, stays alive, then killed
```

This is what the MSI installs to `C:\Program Files\Anki\`; it boots standalone
(cold start is slower than the warm venv as it loads the embedded runtime).

---

## 3. How a grader reproduces it

1. `cd C:\dev\speedrun-anki`; set the env shims in §1 (export the CA PEM once).
2. `tools\ninja wheels` → wheels in `out\wheels\`.
3. Run the two `build_installer.py` invocations in §1 → MSI at
   `out\installer\dist\anki-26.5-win-x64.msi`.
4. Clean-install check (Tier B): the `python -m venv` + `pip install` + the three
   verification one-liners in §2.
5. Or install the MSI itself (double-click, or
   `msiexec /i out\installer\dist\anki-26.5-win-x64.msi`) → launches as **Anki** from
   `C:\Program Files\Anki\`; Tools ▸ **Speedrun Dashboard** / **Transfer Review**.

---

## 4. Tier reached & honesty

- **Tier B — achieved and proven above.** Wheels install into a fresh isolated venv;
  the forked Rust engine RPC and the GUI both run from it with no source tree on the
  path; the self-contained MSI payload also boots standalone.
- **Tier A — not performed.** No clean Windows VM / spare box was available on this
  machine, and we did not fabricate one. The MSI is a genuine self-contained
  distributable, but it was not installed onto a separate machine with no dev
  toolchain.

### What a grader still needs for a full Tier-A clean-machine run

1. A fresh Windows 10/11 x64 VM or box with **no** Python/Rust/Node/dev toolchain.
2. Copy over `anki-26.5-win-x64.msi` only.
3. Double-click it (or `msiexec /i anki-26.5-win-x64.msi`), accept the AGPL license,
   install to `C:\Program Files\Anki\`.
4. Launch **Anki** from the Start menu; confirm it opens and Tools ▸ **Speedrun
   Dashboard** works. (Time-to-first-window there is the true clean-machine signal.)

The MSI is ad-hoc signed (`--adhoc-sign`); a production release would sign it with a
real code-signing identity (`SIGN_IDENTITY` env var, wired in `build_installer.py`).

## 5. SSL / packaging blockers and how they were handled

- **`uv`/`pip`/`briefcase` TLS failures** through the corp proxy → fixed with
  `UV_NATIVE_TLS=true` and a Windows-cert-store PEM wired via
  `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `PIP_CERT` / `NODE_EXTRA_CA_CERTS`.
  Verification stayed **on** the whole time — no `--insecure`/`verify=false` was used.
- **Non-PEP440 `.version` (`26.05-speedrun`)** rejected by Briefcase → invoked
  `build_installer.py` directly with the normalized `26.5` (the version the wheels
  already carry) instead of editing committed source.
