"""
Central configuration for the adaptive models.

Every value here was previously a literal embedded in an engine. Collecting
them in one place makes the model's assumptions visible, lets deployments
override them without editing code, and lets the research scripts evaluate the
same parameters the product runs.

Resolution order, strongest first:

    1. an explicit argument passed to the engine constructor
    2. the corresponding environment variable
    3. parameters fitted from response data (BKT prior/learn only, per skill)
    4. the defaults below

Separation of concerns
----------------------
`prior` and `learn` describe a learner's relationship to a skill, so they are
estimated from response data per skill.

`guess` and `slip` describe an *item*: how likely a correct answer is without
mastery, and an incorrect answer despite it. They therefore belong to the
difficulty tier, not the learner, and are configured per tier.
"""

import json
import os

_TRUE = ("1", "true", "yes", "on")


def env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUE


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(name, default_relative):
    return os.environ.get(name) or os.path.join(PROJECT_ROOT, default_relative)


# --- Storage ---------------------------------------------------------------

USERS_PATH = _path("USERS_PATH", "data/users.json")
USER_PROGRESS_PATH = _path("USER_PROGRESS_PATH", "data/user_progress.json")
QUIZ_ATTEMPTS_PATH = _path("QUIZ_ATTEMPTS_PATH", "data/quiz_attempts.json")
VIDEOS_PATH = _path("VIDEOS_PATH", "data/videos.json")
MICRO_PATTERNS_PATH = _path("MICRO_PATTERNS_PATH", "data/micro_patterns.json")
BKT_STATE_PATH = _path("BKT_STATE_PATH", "data/bkt_states.json")
BANDIT_TABLE_PATH = _path("BANDIT_TABLE_PATH", "data/bandit_q_table.json")
BKT_PARAMS_PATH = _path("BKT_PARAMS_PATH", "models/bkt_params.json")
CLUSTERING_MODEL_PATH = _path("CLUSTERING_MODEL_PATH", "models/clustering_model.pkl")
RAG_DB_PATH = _path("RAG_DB_PATH", "data/chroma_db")
ACTIVE_QUIZ_PATH = _path("ACTIVE_QUIZ_PATH", "data/active_quizzes.json")

# --- Quiz integrity --------------------------------------------------------

# How long an issued quiz stays gradable. The answer key lives server-side for
# this long and is then dropped, so an abandoned quiz does not accumulate.
# Long enough for a slow reader to finish a ten-question set; short enough that
# the store stays small without a scheduled job.
ACTIVE_QUIZ_TTL_SECONDS = env_int("ACTIVE_QUIZ_TTL_SECONDS", 3 * 60 * 60)

# Upper bound on simultaneously outstanding quizzes per learner. Each open tab
# issues one. A handful is legitimate; thousands would mean a client looping on
# the issue endpoint, so the oldest are evicted rather than trusted.
ACTIVE_QUIZ_MAX_PER_USER = env_int("ACTIVE_QUIZ_MAX_PER_USER", 8)

# --- BKT -------------------------------------------------------------------

# Fallbacks used for any skill without fitted parameters.
BKT_DEFAULTS = {
    "prior": env_float("BKT_PRIOR", 0.30),
    "learn": env_float("BKT_LEARN", 0.20),
    "guess": env_float("BKT_GUESS", 0.20),
    "slip": env_float("BKT_SLIP", 0.10),
}

# Load fitted parameters at inference time rather than ignoring them.
BKT_USE_FITTED_PARAMS = env_bool("BKT_USE_FITTED_PARAMS", True)

# Mastery is persisted rounded to this many decimals.
BKT_STATE_PRECISION = env_int("BKT_STATE_PRECISION", 4)

# --- Difficulty tiers ------------------------------------------------------

# Item-level measurement parameters per tier.
DIFFICULTY_PARAMS = {
    "easy": {"guess": env_float("DIFFICULTY_EASY_GUESS", 0.30),
             "slip": env_float("DIFFICULTY_EASY_SLIP", 0.05)},
    "medium": {"guess": env_float("DIFFICULTY_MEDIUM_GUESS", 0.20),
               "slip": env_float("DIFFICULTY_MEDIUM_SLIP", 0.10)},
    "hard": {"guess": env_float("DIFFICULTY_HARD_GUESS", 0.10),
             "slip": env_float("DIFFICULTY_HARD_SLIP", 0.15)},
}

DIFFICULTY_TIERS = ("easy", "medium", "hard")

# Tier used whenever a difficulty-neutral measurement is required.
REFERENCE_TIER = os.environ.get("REFERENCE_TIER", "medium")

# --- Bandit ----------------------------------------------------------------

# Utility weights applied to each tier at selection. Non-uniform weights are a
# hand-set prior that biases routing independently of observed reward, so the
# default is neutral.
BANDIT_MULTIPLIERS = {
    "easy": env_float("BANDIT_MULTIPLIER_EASY", 1.0),
    "medium": env_float("BANDIT_MULTIPLIER_MEDIUM", 1.0),
    "hard": env_float("BANDIT_MULTIPLIER_HARD", 1.0),
}

# Thompson sampling explores through posterior sampling, so no forced
# uniform-random exploration is needed by default.
BANDIT_EPSILON = env_float("BANDIT_EPSILON", 0.0)

# "thompson" maximises the sampled success rate; "target" instead selects the
# tier whose sampled rate is closest to BANDIT_TARGET_RATE.
#
# Simulation favours "target": maximising the success rate rewards easy items
# simply for being easy, so the policy collapses toward the easiest tier
# regardless of whether that is pedagogically right, whereas targeting a rate
# does not. It measured better in seven of nine learner-group comparisons and
# much better where learning depends on matching difficulty to mastery.
#
# It is not the default because it needs a target rate, and the right value is
# an empirical property of real learners. Measured worst-case quality is high
# near 0.85 but falls below the parameter-free default if the true target is
# nearer 0.70. Switch to "target" once real response data can calibrate it.
BANDIT_STRATEGY = os.environ.get("BANDIT_STRATEGY", "thompson")

# Wilson, Shenhav, Straccia & Cohen (2019) derive an optimal training accuracy
# of about 85% for gradient-descent learners. Their result is not about human
# classroom learning, so this is a principled starting value, not evidence.
BANDIT_TARGET_RATE = env_float("BANDIT_TARGET_RATE", 0.85)

# Prior pseudo-counts for an arm in a state no learner has reached yet.
#
# With a uniform Beta(1, 1) on every tier, Thompson sampling picks uniformly at
# random, so a third of first-time learners are served the hardest tier on their
# first quiz. Serving a learner above their level costs materially more than
# serving below it, so the prior favours the easiest tier.
#
# The favoured tier is deliberately *not* matched to the learner's mastery bin.
# Bin-matching encodes a zone-of-proximal-development assumption that holds only
# under some learning models, and measuring it over three model specifications
# made worst-case outcomes worse; favouring the easiest tier improved them under
# every model. See scripts/latent_learning_simulation.py.
#
# This is a prior, not a fixed utility weight: it contributes pseudo-counts that
# observed evidence overrides within a few responses, whereas a multiplier would
# bias selection permanently regardless of what the data showed. The strength is
# set where the measured worst-case stops improving.
BANDIT_PRIOR_PSEUDOCOUNT = env_float("BANDIT_PRIOR_PSEUDOCOUNT", 4.0)
BANDIT_PRIOR_TIER = os.environ.get("BANDIT_PRIOR_TIER", "easy")

# Mastery-bin boundaries for the bandit's context.
MASTERY_BIN_HIGH = env_float("MASTERY_BIN_HIGH", 0.75)
MASTERY_BIN_MEDIUM = env_float("MASTERY_BIN_MEDIUM", 0.40)

# --- Sessions and abuse limits ----------------------------------------------

IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"

# Send the session cookie only over HTTPS in production. Local development is
# served over HTTP, where a Secure cookie would simply never be stored.
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
SESSION_LIFETIME_SECONDS = env_int("SESSION_LIFETIME_SECONDS", 7 * 24 * 3600)

# Failed-login throttling. Keyed primarily on the account being attacked, since
# an attacker controls their own source address but not the target account.
LOGIN_MAX_ATTEMPTS = env_int("LOGIN_MAX_ATTEMPTS", 10)
LOGIN_ATTEMPT_WINDOW_SECONDS = env_int("LOGIN_ATTEMPT_WINDOW_SECONDS", 300)
REGISTER_MAX_ATTEMPTS = env_int("REGISTER_MAX_ATTEMPTS", 20)
REGISTER_ATTEMPT_WINDOW_SECONDS = env_int("REGISTER_ATTEMPT_WINDOW_SECONDS", 3600)

# --- Language model providers ----------------------------------------------

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = os.environ.get("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_TIMEOUT = env_float("GROQ_TIMEOUT", 20.0)

# An optional second OpenAI-compatible provider, tried if the primary fails or
# is rate-limited. Any endpoint exposing /chat/completions works unchanged --
# Cloudflare Workers AI and OpenRouter both do -- so adding capacity is a
# configuration change rather than a code change.
LLM_FALLBACK_NAME = os.environ.get("LLM_FALLBACK_NAME", "fallback")
LLM_FALLBACK_URL = os.environ.get("LLM_FALLBACK_URL", "")
LLM_FALLBACK_API_KEY = os.environ.get("LLM_FALLBACK_API_KEY", "")
LLM_FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "")
LLM_FALLBACK_TIMEOUT = env_float("LLM_FALLBACK_TIMEOUT", 20.0)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
OLLAMA_ENABLED = env_bool("OLLAMA_ENABLED", True)
# Ollama runs locally and is slow; generation needs a long budget, grading does
# not. Note that an unreachable host costs the full timeout on every request,
# which is why OLLAMA_ENABLED must be false wherever Ollama is not deployed.
OLLAMA_TIMEOUT = env_float("OLLAMA_TIMEOUT", 120.0)
OLLAMA_EVAL_TIMEOUT = env_float("OLLAMA_EVAL_TIMEOUT", 30.0)

# --- Fitting ---------------------------------------------------------------

BKT_FIT_MIN_RESPONSES = env_int("BKT_FIT_MIN_RESPONSES", 20)
BKT_FIT_MAX_ITERATIONS = env_int("BKT_FIT_MAX_ITERATIONS", 200)
BKT_FIT_TOLERANCE = env_float("BKT_FIT_TOLERANCE", 1e-6)
# Guess/slip above 0.5 invert the meaning of the latent state, so fits are
# constrained below it.
BKT_FIT_MAX_GUESS = env_float("BKT_FIT_MAX_GUESS", 0.45)
BKT_FIT_MAX_SLIP = env_float("BKT_FIT_MAX_SLIP", 0.45)

# Score at or above which a quiz attempt counts as a correct response.
MASTERY_CORRECT_THRESHOLD = env_float("MASTERY_CORRECT_THRESHOLD", 70.0)


def load_fitted_bkt_params(path=None):
    """Return {skill: {prior, learn, ...}} fitted parameters, or {} if absent.

    A missing or unreadable file is not an error: the caller falls back to
    BKT_DEFAULTS. A corrupt file should not take the application down.
    """
    target = path or BKT_PARAMS_PATH
    try:
        with open(target, "r") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return {}
    skills = payload.get("skills", payload)
    if not isinstance(skills, dict):
        return {}
    return {k: v for k, v in skills.items() if isinstance(v, dict)}
