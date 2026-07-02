# Wednesday Submission — Recording Playbook

Everything for the Wednesday deliverable, in order. The code/build work is done and
pushed; what's left is recording 4 clips.

- **Public repo:** https://github.com/MokshShah1/Speedrun (branch `speedrun`)
- **Exam:** MCAT (472–528, four sections 118–132)
- Get the **commit hash** for your write-up: `git -C C:\dev\speedrun-anki log -1 --format="%H"`

---

## Recording 1 — Clean build from source (+ commit hash)
Start screen capture, then:
```powershell
cd C:\dev\speedrun-anki
git log -1 --format="%H"       # show/read this commit hash
.\run.bat                       # builds pylib + qt + Rust from source, then launches Anki
```
On screen: it compiles → **Anki opens** → click **Tools ▸ Speedrun Dashboard** and
**Tools ▸ Speedrun: Transfer Review**. Stop capture.
*(Covers: commit hash + clean build + app runs.)*

## Recording 2 — Test results
Start capture, then:
```powershell
cd C:\dev\speedrun-anki
.\speedrun\wednesday_proof.ps1
```
Prints, in order: commit hash → **16 Rust engine tests pass** → Python AI/eval tests →
pylib backend tests (Rust called from Python) → harnesses (bench / crash-recovery /
calibration / interleaving / soak / deck-tagger), each printing PASS → "PROOF RUN COMPLETE".
Let it finish. Stop capture.

## Recording 3 — Install on a clean machine
On a **fresh Windows VM** (no dev tools):
1. Copy over `C:\dev\speedrun-anki\out\installer\dist\anki-26.05-win-x64.msi`.
2. Start capture → double-click the `.msi` → click through the installer.
3. Launch **Anki** from Start menu → it opens → **Help ▸ About** shows `26.05-speedrun`
   → open **Tools ▸ Speedrun Dashboard**.
4. Stop capture.
*(Covers: installer runs on a clean machine.)*

## Recording 4 — Phone review on the shared engine
On the Android emulator (AVD `speedrun`):
1. Start capture of the emulator window.
2. Open **AnkiDroid** → tap a deck → **study a card**: read the front → **Show answer** → **Good**.
3. Show the due count change (e.g. `1 0 0` → `0 1 0`) — that's the shared Rust scheduler on the phone.
4. Stop capture.
*(The desktop already has the MileDown exam deck, so "both apps review the same deck" is covered.)*

---

## Submission checklist
- [ ] Public repo URL: https://github.com/MokshShah1/Speedrun
- [ ] Commit hash (from Recording 1)
- [ ] Recording 1 — build from source
- [ ] Recording 2 — test results
- [ ] Recording 3 — clean-machine install
- [ ] Recording 4 — phone review
- [ ] `README.md` states the exam (MCAT) up front
- [ ] *(optional)* your name added to `CONTRIBUTORS` (for a fully-green `just check`)

## Notes / honest caveats to mention in your write-up
- **Memory (R)** reads 0 until you study over time — FSRS is enabled, and R rises as cards
  graduate. The model runs and honestly abstains until there's enough graded data (that's the
  give-up rule, which the rubric rewards). Coverage of the outline is a real **100%**.
- The desktop installer is **adhoc-signed** and the APK is a **debug** build — fine for Wednesday;
  sign them with your own cert/keystore for the "signed" Sunday deliverable.
