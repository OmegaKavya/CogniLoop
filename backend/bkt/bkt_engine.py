from backend import config
from backend.storage import JsonStore


class BKTEngine:
    """Bayesian Knowledge Tracing with per-skill fitted parameters.

    `prior` and `learn` are learner-skill properties and are read from fitted
    parameters when available (see backend/bkt/fitting.py and
    scripts/train_models.py). `guess` and `slip` are item properties and come
    from the difficulty tier of the item being answered.

    Any skill without fitted parameters falls back to the configured defaults.
    """

    def __init__(self, storage_path=None, params=None, difficulty_params=None,
                 params_path=None, use_fitted_params=None):
        self.storage_path = storage_path or config.BKT_STATE_PATH
        self._store_cache = None
        defaults = dict(config.BKT_DEFAULTS)
        if params:
            defaults.update({k: v for k, v in params.items() if k in defaults})

        self.p_init = defaults["prior"]
        self.p_learn = defaults["learn"]
        self.p_guess = defaults["guess"]
        self.p_slip = defaults["slip"]

        self.difficulty_params = difficulty_params or config.DIFFICULTY_PARAMS
        self.precision = config.BKT_STATE_PRECISION

        use_fitted = config.BKT_USE_FITTED_PARAMS if use_fitted_params is None \
            else use_fitted_params
        self.fitted_params = config.load_fitted_bkt_params(params_path) if use_fitted else {}

        self._ensure_storage()

    def params_for(self, concept_id, difficulty=None):
        """Resolve the four BKT parameters for one response.

        Fitted values supply prior/learn for the skill; the difficulty tier
        supplies guess/slip for the item. Falls back to instance defaults.
        """
        fitted = self.fitted_params.get(concept_id, {})
        prior = fitted.get("prior", self.p_init)
        learn = fitted.get("learn", self.p_learn)

        tier = self.difficulty_params.get(str(difficulty).lower().strip()) if difficulty else None
        if tier:
            guess, slip = tier["guess"], tier["slip"]
        else:
            guess = fitted.get("guess", self.p_guess)
            slip = fitted.get("slip", self.p_slip)
        return {"prior": prior, "learn": learn, "guess": guess, "slip": slip}

    @property
    def _store(self):
        """Resolved from `storage_path` on each access, not captured at init.

        `storage_path` is the single source of truth for where mastery state
        lives. Binding a store at construction time would ignore later
        reassignment, which is how tests redirect state to a temporary file.
        """
        if self._store_cache is None or self._store_cache.path != self.storage_path:
            self._store_cache = JsonStore(self.storage_path)
        return self._store_cache

    def _ensure_storage(self):
        self._store.ensure_exists()

    def _prior_for(self, concept_id):
        return self.fitted_params.get(concept_id, {}).get("prior", self.p_init)

    def get_mastery(self, user_id, concept_id):
        states = self._store.read()
        return states.get(user_id, {}).get(concept_id, self._prior_for(concept_id))

    def update_mastery(self, user_id, concept_id, is_correct, difficulty=None):
        """Apply one BKT observation and persist the result.

        The read, the Bayesian update and the write happen inside a single
        exclusive lock. Splitting them loses concurrent updates: two requests
        for the same learner would both read the same prior and the second
        write would discard the first.
        """
        resolved = self.params_for(concept_id, difficulty)
        p_guess = resolved["guess"]
        p_slip = resolved["slip"]
        p_learn = resolved["learn"]
        prior = self._prior_for(concept_id)

        def mutate(states):
            p_known_prev = states.get(user_id, {}).get(concept_id, prior)

            if is_correct:
                p_known_ev = (p_known_prev * (1 - p_slip)) / \
                             (p_known_prev * (1 - p_slip) + (1 - p_known_prev) * p_guess)
            else:
                p_known_ev = (p_known_prev * p_slip) / \
                             (p_known_prev * p_slip + (1 - p_known_prev) * (1 - p_guess))

            p_known_new = p_known_ev + (1 - p_known_ev) * p_learn

            states.setdefault(user_id, {})[concept_id] = round(p_known_new, self.precision)
            return p_known_new

        return self._store.update(mutate)

    def get_all_states(self):
        """Return the full states dict {user_id: {concept_id: mastery}}."""
        return self._store.read()

bkt_engine = BKTEngine()
