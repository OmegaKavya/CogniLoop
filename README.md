# CogniLoop: Personalizing Open-Domain Video Curricula

**Author & Research Lead**: Kavya Aggarwal | **IEEE Research Project**

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Tests Passed](https://img.shields.io/badge/tests-162%20passed-emerald.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-amber.svg)](LICENSE)
[![Validation](https://img.shields.io/badge/simulations-N=60%20validated-blueviolet.svg)](SIMULATION_60_PROFILES_REPORT.md)

An advanced, standalone closed-loop adaptive learning platform that converts passive video lecture consumption into an active concept mastery loop. Built by **Kavya Aggarwal**, CogniLoop combines Item Response Theory (IRT)-grounded Bayesian Knowledge Tracing (BKT), Thompson Sampling Contextual Bandits, Retrieval-Augmented Generation (RAG) for zero-hallucination conceptual quizzing, and behavioral micro-pattern clustering.

---

## Why CogniLoop Stands Out

- **Advanced Adaptive Engine**: Implements IRT-grounded BKT mastery tracking + Thompson Sampling Contextual Bandits + K-Means pacing behavior clustering.
- **RAG-Grounded Zero-Hallucination Quizzes**: Uses semantic transcript vector indexing (`ChromaDB`) to ground LLM assessment generation exclusively in factual lecture material.
- **Actionable AI Growth Analytics**: Replaces static scores with personalized cognitive diagnoses (rushed guessing vs. deep conceptual confusion), rapid 5-minute study drills, and an exportable executive PDF cheat sheet report.
- **Enterprise Reliability & Security**: Features a 3-tier fallback architecture (Groq API -> Ollama Local -> Curated Static Questions), timing-attack resistant PBKDF2-HMAC-SHA256 password hashing, and a client-side interface protection layer (`security_guard.js`).
- **Empirical Scientific Validation**: Rigorously validated across a simulated cohort of N=60 student profiles, achieving a statistically significant +169.2% improvement in Normalized Learning Gain (NLG) compared to static sequential control paths (p < 0.0001).

---

## System Architecture & Curriculum Structure

For technical system blueprints, mathematical models, module boundaries, and request pipelines, review [ARCHITECTURE.md](ARCHITECTURE.md) and the formal paper in [IEEE_RESEARCH_PAPER.tex](IEEE_RESEARCH_PAPER.tex).

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
- Generates conceptually engaging Multiple Choice Questions using **Groq API** (`llama-3.1-8b-instant`) with automatic fallback to local **Ollama** (`llama3.2`).
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
- Protected by a verified suite of **162 automated tests** executing with 100% reliability in pytest.
- Covers mathematical BKT transitions, bandit reward convergence, file locking under concurrent load, RAG indexing pipelines, and full-stack route flows.

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

Open your web browser and navigate to `http://127.0.0.1:5000` to access the platform.

---

## Legal Compliance & Licensing

- **YouTube Player Integration**: Streams open educational content using the official YouTube IFrame Player API in complete compliance with Sections 4.C and 4.D of the YouTube API Terms of Service. Original creator monetization and attribution are fully preserved.
- **Transcript Processing**: Captions are indexed programmatically for transformative analytical testing under U.S. Fair Use laws (17 U.S.C. Section 107).
- **License**: Distributed under the MIT License. See [LICENSE](LICENSE) for complete terms.
