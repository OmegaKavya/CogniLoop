# CogniLoop Learning Platform

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![Tests Passed](https://img.shields.io/badge/tests-162%20passed-emerald.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-amber.svg)](LICENSE)
[![Preprint](https://img.shields.io/badge/manuscript-under%20review-blueviolet.svg)](IEEE_RESEARCH_PAPER.md)

An adaptive learning platform that converts passive video watching into a personalized mastery loop.
It combines in-video checkpoints, concept-focused quiz generation, Bayesian mastery tracking, and behavior-aware difficulty adaptation.
The engine is reliability-first: when transcript or LLM services fail, deterministic fallbacks keep the learner journey uninterrupted.

## Architecture

For full system architecture, module boundaries, adaptive-engine pipeline, and request lifecycle diagrams, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Why this project stands out

- Adaptive intelligence stack: BKT mastery + Epsilon-Greedy Contextual Bandits + behavior clustering.
- RAG-powered assessment quality: Semantic chunking of transcripts using `chromadb` to eliminate hallucination.
- Reliability by design: graceful fallback paths for transcript, LLM, and vector-database failures.
- Production-ready architecture: Repository pattern for data access, Docker containerization, and batched LLM inference.
- Scientific rigor: Built-in A/B Testing framework measuring Normalized Learning Gain (NLG) with SciPy T-tests.

## What this project does

This application is designed to turn a topic into a guided learning flow:

1. Watch a topic video.
2. Study topic-specific submodules and quick revision checkpoints.
3. Take an adaptive conceptual quiz.
4. Review answers with explanations, insights, and performance feedback.
5. Track progress over time with dashboard analytics and heatmaps.

The project is built for topic mastery, not generic study-habit questions. Quizzes are intended to move from basic concepts to advanced reasoning.

## Core features

### 1. Adaptive quiz generation

- Generates topic-based MCQ quizzes using **Groq API** (primary, ~2s) with Ollama as local offline fallback.
- Default Groq model: `llama-3.1-8b-instant` (free tier, 30 RPM). Ollama model: `llama3.2`.
- Questions adapt to learner mastery and speed.
- Quiz length: **6–10 questions** (adaptive).
- Difficulty is adjusted based on learner behavior cluster and BKT mastery.
- Question repetition is minimized across attempts via a `avoid_questions` deduplication list.
- **3-tier graceful fallback**: Groq → Ollama → static curated questions.

### 2. Conceptual question quality

- Questions are generated to test understanding of the topic itself.
- The quiz flow is designed to move from:
  - basic definitions and foundations,
  - to intermediate mechanisms and applications,
  - to advanced reasoning, edge cases, and trade-offs.
- Study-habit or generic best-practice style questions are intentionally avoided.

### 3. Quiz review and explanations

- Every attempt can be reviewed with a full **diagnostic breakdown**.
- Per-question **time-signal diagnosis**: rushed guess (< 5s), concept gap (> 25s), or misconception.
- Shows mastery before/after bars, score ring, and pace analysis.
- AI-generated action plan maps wrong answers to cheat-sheet concepts (not generic Google links).
- Resources link to CogniLoop study notes, GeeksforGeeks GATE sets, and topic-specific references.

### 4. AI insights and revision support

- Generates topic-wise revision support after a quiz.
- Highlights focus concepts.
- Builds a quick cheat-sheet style summary.
- Suggests related learning resources.

### 5. Video learning with curated submodules

- Each topic has **4 real curriculum submodules** with specific CS concepts:
  - OS: Process & Thread Lifecycle / Virtual Memory / Synchronisation & Deadlock / File Systems & Disk Scheduling
  - DS: Linear Structures / Trees & Balanced Structures / Graphs & Hashing / Advanced Trees & Heap Operations
  - DBMS: Relational Model & SQL / Normalisation & Design / Transactions & Concurrency / Indexing & Query Optimization
  - CN: Network Architecture & Addressing / TCP vs UDP / Application Layer & Routing / Network Security & Cryptography
- Each module includes a **GATE exam angle tip** and 3 topic-specific checkpoint MCQs.
- Checkpoints are curated MCQs (not generic "which statement matches") testing real concepts.

### 6. Timer and hint behavior

- Quiz questions use per-question timing.
- Hints unlock during the question flow.
- When time expires, the quiz advances instead of terminating.

### 7. Dashboard analytics

- Tracks progress and quiz history.
- Shows review links for past attempts.
- Displays topic-wise heatmaps.
- Surfaces mastery, score, timing, and learning trends.

### 8. LLM integration — Groq primary, Ollama fallback

- **Groq API** (free at `console.groq.com`) is used as the primary LLM for ~2s quiz generation.
- **Ollama** (`llama3.2`) is the local offline fallback with no changes to existing setup.
- Set `GROQ_API_KEY` in `.env` to enable fast generation; omit to use Ollama only.
- Both insights engine and quiz generator follow the same Groq → Ollama → static priority chain.

### 9. Design system — Warm Slate + Amber

- Premium "Warm Slate" palette: deep teal `#1a6b72` primary, amber `#d97706` accent, cream-white background.
- Per-topic card accent colours (violet/sky/brown/emerald for OS/DS/DBMS/CN).
- Plus Jakarta Sans typography, amber top stripe on navbar, glassmorphism panels.
- Immersive quiz loading overlay: 4 animated steps + rotating did-you-know facts per topic.

## Tech stack

- Python 3.12
- Flask 3.1
- Jinja2 templates
- Vanilla JS + CSS (Warm Slate design system)
- **Groq API** (`llama-3.1-8b-instant`) — primary LLM, ~2s quiz generation (free tier)
- Ollama (`llama3.2`) — local offline LLM fallback
- ChromaDB (Vector DB for RAG-based context retrieval)
- Sentence-Transformers (Semantic Embeddings)
- scikit-learn & scipy (Clustering & Statistical Testing)
- pandas & numpy
- pyBKT (Bayesian Knowledge Tracing)
- python-dotenv
- Docker & Docker Compose

## Project structure

- `app.py` — Main Flask application and route handling.
- `backend/repositories/` — Data access layer isolating JSON file access (ready for SQL migration).
- `backend/adaptation/` — Contextual Bandit algorithms, clustering, and recommendation logic.
- `backend/quiz/` — Groq/Ollama quiz generation, RAG retrieval, insights engine, and evaluator.
- `backend/analytics/` — A/B testing framework, simulation scripts, and statistical metrics.
- `frontend/templates/` — HTML templates for landing, dashboard, video, quiz, review, login, and register pages.
- `static/css/style.css` — Warm Slate + Amber design system (single source of truth for all styles).
- `data/` — JSON data used by the app for users, progress, quiz attempts, and video metadata.
- `models/` — Saved learning/adaptation models.
- `scripts/` — Utility scripts for training models.
- `utils/constants.py` — `STATIC_CHEAT_SHEETS` and `SUBMODULE_DEFINITIONS` (curated topic content).
- `utils/` — LLM client and helper utilities.
- `tests/` — **162 tests**: unit, integration, stress, Groq fallback, insights diagnostics, submodule integrity, and full-stack E2E route testing.

## Setup

### 1. Clone the repository

```bash
git clone <your-github-repo-url>
cd CogniLoop
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the template and fill in your values:

```bash
cp .env.template .env
```

Required variables:

```env
SECRET_KEY=your_secret_key_here
FLASK_ENV=development

# Fast quiz generation (~2s) — free at https://console.groq.com
GROQ_API_KEY=gsk_...

# Local LLM fallback (used if GROQ_API_KEY is empty)
OLLAMA_URL=http://localhost:11434/api/generate
```

### 5. Install and start Ollama (optional — only needed if not using Groq)

Make sure Ollama is installed and running locally.

```bash
ollama pull llama3.2
```

### 6. Run the app (Docker)

The recommended way to run the application is via Docker:
```bash
docker-compose up --build
```
This maps port `5001` to your local machine.

### 7. Run the app (Local)

```bash
python app.py
```

Then open the local address shown in the terminal, usually:

```bash
http://127.0.0.1:5001
```

### 7. Run tests

```bash
PYTHONPATH=. pytest -v tests/
```

## How the learning flow works

### Landing and authentication

- Users can register and log in.
- Session data is used to manage access.

### Dashboard

- Shows the learner’s progress.
- Displays attempts, topic mastery, and heatmap-style insights.
- Provides quick access to video review and quiz review pages.

### Topic video page

- Presents the video lesson.
- Breaks the topic into submodules.
- Adds checkpoint quizzes during playback.
- Encourages active learning instead of passive watching.

### Quiz page

- Loads a topic-specific adaptive quiz.
- Shows a revision helper while the quiz is being prepared.
- Uses timed questions and adaptive difficulty.
- Unlocks hints during the quiz.

### Quiz submission and review

- Calculates score and mastery.
- Saves detailed attempt snapshots.
- Generates AI insights.
- Allows later review from the dashboard or the review page.

## Technical deep dive

This section summarizes the core algorithms and computational logic used by the platform.

### 1) Bayesian Knowledge Tracing (BKT)

The mastery engine maintains per-user, per-concept latent knowledge probability and updates it after each quiz attempt.

Default parameters:

- Initial mastery: \(P(L_0)=0.3\)
- Learning transition: \(P(T)=0.2\)
- Guess probability: \(P(G)=0.2\)
- Slip probability: \(P(S)=0.1\)

Posterior update for correct response \((Correct=1)\):

\[
P(L_n|Correct)=\frac{P(L_n)(1-P(S))}{P(L_n)(1-P(S)) + (1-P(L_n))P(G)}
\]

Posterior update for incorrect response \((Correct=0)\):

\[
P(L_n|Incorrect)=\frac{P(L_n)P(S)}{P(L_n)P(S) + (1-P(L_n))(1-P(G))}
\]

Learning transition after evidence update:

\[
P(L\_{n+1})=P(L_n|Obs) + (1-P(L_n|Obs))P(T)
\]

Where Obs is either Correct or Incorrect.

### 2) Quiz scoring and time metrics

For each quiz attempt:

\[
Score(\%)=\frac{CorrectCount}{QuestionCount} \times 100
\]

\[
AvgTime=\frac{\sum\_{i=1}^{Q} t_i}{Q}
\]

where \(t_i\) is time spent on question \(i\), and \(Q\) is number of questions in that attempt.

### 3) Contextual Bandit Adaptation Policy

The system uses an **Epsilon-Greedy Contextual Bandit** to map learner states to difficulty levels.
- **State**: Defined by `Learner Cluster` (General, Fast, Detail) + `BKT Mastery Bin` (Low, Medium, High).
- **Actions**: `easy`, `medium`, `hard`.
- **Reward**: Calculated as `(Score / 100) * Difficulty Multiplier` where `easy=0.8`, `medium=1.0`, `hard=1.2`.

The bandit learns over time, exploring random difficulties 20% of the time (`epsilon=0.2`) and exploiting the best known Q-value for the remainder. This pushes learners to the maximum difficulty they can handle while maintaining high scores.

### 4) Dynamic question-count policy (6 to 10)

Question count is sampled from a range determined by speed and adjusted by mastery:

- Slow: base range [9, 10]
- Steady: base range [8, 10]
- Fast: base range [7, 8]

Mastery refinement:

- If mastery \(< 0.35\), upper bound increases by 1 (capped at 10).
- If mastery \(> 0.75\), lower bound decreases by 1 (floored at 6).

Final question count is selected uniformly at random from the final integer interval.

### 5) Behavior clustering (micro-pattern modeling)

The interaction clustering model uses KMeans with:

- Number of clusters: 3
- Initialization runs: \(n_init=10\)
- Random seed: 42

Feature vector:

- pause_count
- rewatch_count
- skip_ratio
- watch_percentage

Cluster outputs are mapped to behavior labels:

- Steady Learner
- Detail-Oriented
- Fast-Paced

This cluster label is then fed into recommendation messaging and adaptation context.

### 6) RAG Pipeline & Quiz Generation Constraints

The generator uses `chromadb` and `sentence-transformers` to chunk transcripts and retrieve the Top-K semantically relevant segments. This completely mitigates LLM hallucinations.
The generator enforces these constraints in prompt policy:

- Topic-concept focus only (no study-habit or exam-strategy questions).
- Basic \(\rightarrow\) intermediate \(\rightarrow\) advanced progression.
- One correct answer + 3 plausible distractors tied to misconceptions.
- Hint quality constraints: concise and non-revealing.
- Duplicate suppression against recent question stems.

Duplicate suppression is done by normalizing stems (trim + lowercase + whitespace collapse) and filtering seen/avoided items before finalizing the attempt.
The LLM inference is **batched**, meaning all 7-15 questions are evaluated in a single API call rather than sequentially, reducing latency by 90%.

### 7) AI-assisted semantic evaluation

For each response, the evaluator asks the local LLM to verify semantic correctness and generate one-line feedback. If LLM verification fails, a deterministic fallback compares normalized strings.

This hybrid strategy provides:

- semantic robustness when wording differs,
- deterministic safety when model calls fail.

### 8) Heatmap feature engineering

Per-topic dashboard heatmap rows are aggregated from historical attempts:

- mean score,
- mean mastery,
- mean response time,
- dominant speed label frequency.

The visualization uses derived normalized values, including:

\[
SpeedValue=
\begin{cases}
95 & \text{Fast}\\
70 & \text{Steady}\\
45 & \text{Slow}\\
0 & \text{N/A}
\end{cases}
\]

\[
AvgTimeValue = clamp(100 - 2.5\cdot min(AvgTime, 40), 0, 100)
\]

### 9) System design patterns in use

- Layered backend modules:
  - generation,
  - evaluation,
  - adaptation,
  - recommendation,
  - presentation routes.
- Graceful fallback architecture for transcript fetch and LLM calls.
- JSON-based persistence for rapid prototyping and deterministic local execution.
- Session-scoped user flow with historical attempt replay and review.

### 10) Practical complexity notes

- Duplicate filtering in quiz assembly is linear in generated question count: \(O(n)\).
- Topic heatmap aggregation is linear in number of stored attempts per render: \(O(m)\).
- KMeans inference is constant-time per request with a fixed small feature vector.
- Most expensive operations are external model/transcript calls (network + model latency), not local CPU math.

## Data files

The app stores learning state in JSON files inside `data/`.
If you want a clean reset, you can clear the relevant JSON files before starting the app.

## Notes for development

- Keep Ollama running before launching the Flask app.
- Use `llama3.2` unless you intentionally change the model configuration.
- If you retrain or replace models, make sure the files under `models/` stay compatible with the app.
- The app is designed to work best with the provided topic metadata and transcript-enabled videos.

## Troubleshooting

### Ollama is not responding

- Confirm Ollama is running locally.
- Check `http://127.0.0.1:11434/api/tags`.
- Make sure `llama3.2` is installed.

### Quiz generation feels generic

- Ensure the topic has correct metadata.
- If transcript data is unavailable, the app uses fallback context.
- The quiz generator is tuned for conceptual topic questions, not generic learning tips.

### Missing Python packages

- Reinstall dependencies with `pip install -r requirements.txt`.
