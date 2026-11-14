# CogniLoop: Personalizing Open-Domain Video Curricula

**Author**: Kavya Aggarwal

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Tests Passed](https://img.shields.io/badge/tests-290%20passed-emerald.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-amber.svg)](LICENSE)
[![Evaluation](https://img.shields.io/badge/evaluation-simulation%20only-lightgrey.svg)](#evaluation-status)

An advanced, standalone closed-loop adaptive learning platform that converts passive video lecture consumption into an active concept mastery loop. Built by **Kavya Aggarwal**, CogniLoop combines Item Response Theory (IRT)-grounded Bayesian Knowledge Tracing (BKT), Thompson Sampling Contextual Bandits, Retrieval-Augmented Generation (RAG) for transcript-grounded quizzing, and behavioral micro-pattern clustering.

---

## Why CogniLoop Stands Out

- **Advanced Adaptive Engine**: Implements IRT-grounded BKT mastery tracking + Thompson Sampling Contextual Bandits + K-Means pacing behavior clustering.
- **Transcript-Grounded Quiz Generation**: Uses semantic transcript vector indexing (`ChromaDB`) to ground LLM assessment generation exclusively in factual lecture material.
- **Actionable AI Growth Analytics**: Replaces static scores with personalized cognitive diagnoses (rushed guessing vs. deep conceptual confusion), rapid 5-minute study drills, and an exportable executive PDF cheat sheet report.
- **Enterprise Reliability & Security**: Features a 3-tier fallback architecture (Groq API -> Ollama Local -> Curated Static Questions), timing-attack resistant PBKDF2-HMAC-SHA256 password hashing, and a client-side interface protection layer (`security_guard.js`).
- **Honest Evaluation Status**: CogniLoop has not been evaluated with real learners. An earlier simulated result reported here was found to be confounded and has been withdrawn; see [Evaluation status](#evaluation-status).

---

## System Architecture & Curriculum Structure

For technical system blueprints, mathematical models, module boundaries, and request pipelines, review [ARCHITECTURE.md](ARCHITECTURE.md) and the paper in [paper/Estimator_Confound_JEDM.tex](paper/Estimator_Confound_JEDM.tex).

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
- Protected by a suite of **290 automated tests** executing with 100% reliability in pytest.
- Covers BKT transitions and parameter fitting, bandit selection, concurrency safety of all persisted state, credential handling and abuse limits, LLM provider routing, and full-stack route flows.

---

## Quick Start & Installation

### Prerequisites
- Python 3.10+ (Python 3.12 recommended)
- Optional: Local Ollama runtime with `llama3.2` model installed for offline execution
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
tracing implementation exactly. Analysis of the original failure mode is in
`paper/Estimator_Confound_JEDM.tex`.

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
