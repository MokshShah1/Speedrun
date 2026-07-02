# Speedrun — an MCAT study app built inside Anki

> **This is a fork of [Anki](https://github.com/ankitects/anki)** (the upstream project and its
> README are preserved below). Speedrun modifies Anki's core **Rust engine** to optimize
> **transfer**, not just recall — desktop + mobile sharing one engine.

**Exam:** MCAT (scored 472–528; four sections scored 118–132).

Speedrun answers three separate questions with three separate scores:

- **Memory (R)** — FSRS retrievability, aggregated per AAMC concept.
- **Performance (T)** — probability of solving a _novel_ exam-style item, from a 1-PL IRT / Elo
  model updated by graded transfer answers.
- **Readiness** — T scaled to 472–528 with a confidence band that widens as coverage drops, plus a
  **give-up rule** that shows no score when there isn't enough graded data.

The headline metric is **G = R − T**, the "illusion of mastery" gap.

**Where things live**

- Engine (Rust): `rslib/src/speedrun/`, storage `rslib/src/storage/speedrun/`, API `proto/anki/speedrun.proto`
- Desktop UI: `qt/aqt/speedrun.py`, `qt/aqt/transfer_reviewer.py` (Tools ▸ Speedrun Dashboard / Transfer Review)
- Module (data, AI pipeline, eval harnesses, Android kit): `speedrun/`
- Full project context: **[speedrun/CONTEXT.md](./speedrun/CONTEXT.md)**
- Submission + recording playbook: **[speedrun/WEDNESDAY_SUBMISSION.md](./speedrun/WEDNESDAY_SUBMISSION.md)**

**Build & run** (Windows — see CONTEXT.md for full details)

- `.\run.bat` — build from source and launch the forked desktop app
- `.\speedrun\wednesday_proof.ps1` — print the commit hash and run the full test suite + engine harnesses
- Android backend + AnkiDroid: `speedrun/android/ANDROID.md`

**License:** AGPL-3.0-or-later, inherited from Anki (some Anki components are BSD-3-Clause).
See [LICENSE](./LICENSE) and credit the upstream contributors in [CONTRIBUTORS](./CONTRIBUTORS).

---

# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
