# CogniLoop: Personalizing Open-Domain Video Curricula

**Author**: Kavya Aggarwal

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Tests Passed](https://img.shields.io/badge/tests-442%20passed-emerald.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-amber.svg)](LICENSE)
[![Evaluation](https://img.shields.io/badge/evaluation-simulation%20only-lightgrey.svg)](#evaluation-status)

An advanced, standalone closed-loop adaptive learning platform that converts passive video lecture consumption into an active concept mastery loop. Built by **Kavya Aggarwal**, CogniLoop combines Item Response Theory (IRT)-grounded Bayesian Knowledge Tracing (BKT), Thompson Sampling Contextual Bandits, Retrieval-Augmented Generation (RAG) for transcript-grounded quizzing, and behavioral micro-pattern clustering.

---

## Why CogniLoop Stands Out

- **Advanced Adaptive Engine**: Implements IRT-grounded BKT mastery tracking + Thompson Sampling Contextual Bandits + K-Means pacing behavior clustering.
- **Transcript-Grounded Quiz Generation**: Uses semantic transcript vector indexing (`ChromaDB`) to ground LLM assessment generation exclusively in factual lecture material.
- **Actionable AI Growth Analytics**: Replaces static scores with personalized cognitive diagnoses (rushed guessing vs. deep conceptual confusion), rapid 5-minute study drills, and an exportable executive PDF cheat sheet report.
- **Graceful Degradation**: Quiz generation, grading and insights each fall back from a hosted model to a local one to a curated static pool, so a missing API key or an unreachable provider degrades the experience rather than breaking it.
- **Security**: PBKDF2-HMAC-SHA256 password hashing at 600,000 iterations with constant-time comparison, per-account and per-address login throttling, `SameSite=Lax` and `Secure` session cookies, and baseline security headers including a frame-ancestors policy.
- **Honest Evaluation Status**: CogniLoop has not been evaluated with real learners. An earlier simulated result reported here was found to be confounded and has been withdrawn; see [Evaluation status](#evaluation-status).

---

## System Architecture & Curriculum Structure

For technical system blueprints, mathematical models, module boundaries, and request pipelines, review [ARCHITECTURE.md](ARCHITECTURE.md).

The analysis of the estimator confound is written up as a manuscript. Its source is deliberately not tracked here, because similarity checkers crawl public repositories and the manuscript would match itself at submission. The code it refers to is public, which is what the reproducibility statement means.

### Core Computer Science Curriculum
CogniLoop structures core university CS topics into modular learning paths. The system includes **16 distinct submodules** across four primary domain areas:

1. **Operating Systems (OS)**: Process & Thread Lifecycle / Virtual Memory & Paging / Synchronization & Deadlocks / File Systems & Disk Scheduling
2. **Data Structures (DS)**: Linear Structures & Pointers / Balanced Trees (AVL, Red-Black) / Graph Algorithms & Hashing / Advanced Heaps & Priority Queues
3. **Database Management Systems (DBMS)**: Relational Algebra & SQL Mastery / Schema Normalization & ER Modeling / ACID Transactions & Concurrency Control / Indexing B-Trees & Query Optimization
4. **Computer Networks (CN)**: Network Architecture & IP Addressing / Transport Layer (TCP vs UDP dynamics) / Application Protocols & Routing / Network Security & Cryptographic Protocols

Every submodule includes:
- A dedicated educational video lecture with uninterrupted playback integration.
- 3 embedded concept checkpoints triggered dynamically at 30%, 65%, and 85% video completion milestones.
- GATE exam focus tips and structured conceptual study summaries.
- A future roadmap announcement for transitioning AI study anchors into comprehensive, expert-curated textbook modules.

---

## Key Feature Highlights

### 1. Closed-Loop Adaptive Assessments
- Generates conceptually engaging Multiple Choice Questions using **Groq API** (`openai/gpt-oss-20b`, configurable) with automatic fallback to local **Ollama** (`llama3.2`).
- Questions evolve in real-time across Basic -> Intermediate -> Advanced operational logic based on student mastery trajectories.
- Implements strict deduplication filtering to eliminate question repetition across attempts.
- Evaluates student answers using hybrid semantic parsing combined with deterministic comparison logic.

### 2. Time-Signal Diagnosis & AI Analytics
- Diagnoses student errors based on interaction speed and cognitive load:
  - **Rushed Guessing** (< 5 seconds): Alerts learners to careless execution.
  - **Conceptual Gap** (> 25 seconds): Identifies deep theoretical confusion and triggers remedial study links.
- Generates topic-wise revision action plans and 5-minute rapid recall drills.
- Provides an executive revision cheat sheet exportable directly as a high-resolution PDF document.

### 3. Comprehensive Verification & QA
- Protected by a suite of **442 automated tests** executing with 100% reliability in pytest.
- Covers BKT transitions and parameter fitting, bandit selection, concurrency safety of all persisted state, credential handling and abuse limits, LLM provider routing, and full-stack route flows.

---

## Configuration

All model parameters and storage paths are read from `backend/config.py` and can
be overridden by environment variable; nothing needs editing in code to retune a
deployment. The values that matter most:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | unset | Hosted model for generation, grading and insights. Without it the system falls back to the static pool and exact-match grading. |
| `OLLAMA_ENABLED` | `true` | Set `false` wherever no local Ollama runs, otherwise every request pays a connection timeout. |
| `BANDIT_STRATEGY` | `thompson` | `target` selects the tier nearest `BANDIT_TARGET_RATE` instead of maximising reward. Opt-in: it needs a target calibrated from real learners. |
| `BKT_USE_FITTED_PARAMS` | `true` | Loads per-skill parameters fitted by `scripts/train_models.py`; falls back to defaults when absent or unidentifiable. |
| `SESSION_COOKIE_SECURE` | on in production | Follows `FLASK_ENV`; must stay off for local HTTP development. |
| `DATABASE_URL` | unset | Postgres connection string. Set, documents are stored in Postgres; unset, they are JSON files under `data/`. Required in any deployment with an ephemeral filesystem, which is every free tier. Use the pooled endpoint. |

## Maintenance

Every script in `scripts/` resolves `backend` as a top-level package, so run
them from the repository root with it on the path:

```bash
PYTHONPATH=. python3 scripts/<name>.py
```

Without it they stop at `ModuleNotFoundError: No module named 'backend'`.

- `python3 scripts/check_video_links.py` verifies every curriculum video still
  resolves and is long enough to be a lecture rather than a trailer. It exits
  non-zero on failure, so it can be scheduled. Third-party videos disappear
  without warning and the player simply shows "unavailable".
- `python3 scripts/train_models.py` fits BKT parameters from recorded responses.
  Fits that rest on a constraint boundary are rejected rather than deployed.
- `PYTHONPATH=. python3 scripts/migrate_json_to_postgres.py` copies the JSON
  documents in `data/` into Postgres. Run once per environment. It refuses to
  overwrite a document that already exists unless given `--overwrite`, so a
  second run cannot replace live data with a local copy, and `--dry-run`
  reports what it would do. The files are left in place as a point-in-time
  backup.

### Database maintenance

- **Schema.** One table, `documents(key TEXT PRIMARY KEY, data JSONB,
  updated_at TIMESTAMPTZ)`, created on first use. There is no migration tool
  and none is needed while the schema is one table; a second table would be
  the point to add one.
- **Backups.** Neon keeps point-in-time restore on its free tier, which covers
  accidental deletion. For an independent copy, read every document out with
  `PgStore` and write it to disk; the JSON files from the original migration
  are such a copy.
- **Connections.** The pool is `max_size=4` with `min_size=0`, so an idle
  instance holds none and a free Postgres is never exhausted. Prepared
  statements are disabled because a transaction-mode pooler reassigns backend
  connections between executions.
- **Growth.** `quiz_attempts` is the document that grows without bound. JSONB
  stores it compressed, 221 kB of files became 34 kB in the database, but the
  whole document is still read and rewritten on each append. Splitting
  attempts into rows is the next change if it becomes slow.
- **Tests.** `tests/test_storage_postgres.py` exercises the real database and
  skips without `DATABASE_URL`, so the default suite needs nothing installed:
  `DATABASE_URL=... PYTHONPATH=. pytest tests/test_storage_postgres.py`. It
  writes under a `tests/_pg_*` key prefix and deletes it afterwards, so it is
  safe to point at the production database.

## Quick Start & Installation

### Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- Optional: Local Ollama runtime with `llama3.2` for offline development. Not viable in a small production container: the model file alone is several times the memory of a free-tier instance, so set `OLLAMA_ENABLED=false` there.
- Optional: Free Groq API key (`GROQ_API_KEY`) for ultra-fast (~2 second) generation

### Installation Step-by-Step
```bash
# 1. Clone the repository and navigate into the workspace
git clone <repository-url>
cd UpdatedEnancedNPTEL-main

# 2. Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install required dependencies
pip install -r requirements.txt

# 4. Configure environment variables (optional for Groq)
cp .env.template .env
# Edit .env to add your GROQ_API_KEY if available

# 5. Run the full automated verification suite
python3 -m pytest tests/

# 6. Launch the application server
python3 app.py
```

Open your web browser and navigate to `http://127.0.0.1:5001` to access the platform.

---

## Evaluation status

CogniLoop has **not** been evaluated with real learners, and makes no claim of
measured learning gains.

An earlier version of this project reported a statistically significant gain
from a simulation of 60 learner profiles. That result was withdrawn after the
evaluation was found to be confounded: it read the Bayesian Knowledge Tracing
posterior back as the learning outcome while assigning the two arms different
learn rates, so the reported gain restated an assumption rather than measuring
anything. The scripts that produced it (`generate_report.py`,
`scripts/full_verified_analysis.py`,
`scripts/verify_and_export_figure_data.py`) are retained for provenance and
carry a notice at the top; their output should not be cited.

The corrected harness is `scripts/latent_learning_simulation.py`. It keeps
latent mastery separate from the estimator's belief, scores on a
difficulty-neutral probe, and is verified to reproduce the deployed knowledge
tracing implementation exactly. Analysis of the original failure mode is in the manuscript, which is not
tracked in this repository.

What the simulation does support, and what it does not:

| Claim | Status |
| --- | --- |
| The system runs end to end and persists state safely under concurrency | Covered by the test suite |
| Routing configuration changes measurably affect simulated outcomes | Supported, simulation only |
| CogniLoop improves learning for real students | **Not evaluated** |

---

## Legal Compliance & Licensing

- **YouTube Player Integration**: Streams open educational content using the official YouTube IFrame Player API in complete compliance with Sections 4.C and 4.D of the YouTube API Terms of Service. Original creator monetization and attribution are fully preserved.
- **Transcript Processing**: Captions are indexed programmatically for transformative analytical testing under U.S. Fair Use laws (17 U.S.C. Section 107).
- **License**: Distributed under the MIT License. See [LICENSE](LICENSE) for complete terms.
