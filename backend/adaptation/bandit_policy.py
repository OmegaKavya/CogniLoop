import random

from backend import config
from backend.storage import JsonStore

class ContextualBanditAdapter:
    """
    Thompson Sampling Contextual Bandit for Adaptive Difficulty Selection.
    Replaces Epsilon-Greedy with a Bayesian policy that maps 
    (Cluster + Mastery) -> Difficulty.
    Keeps backward-compatible Q-table structure.
    """
    def __init__(self, epsilon=None, storage_path=None,
                 multipliers=None, strategy=None):
        """
        epsilon    Probability of a forced uniform-random action. Thompson
                   sampling already explores through posterior sampling, so
                   this defaults to 0.0 and exists only for ablation.
        strategy   "thompson" samples each arm's success rate from its Beta
                   posterior; "greedy" takes the posterior mean. Choosing the
                   strategy is independent of epsilon.

        Defaults come from backend.config so a deployment can tune routing
        without editing code.
        """
        strategy = config.BANDIT_STRATEGY if strategy is None else strategy
        if strategy not in ("thompson", "greedy"):
            raise ValueError(f"unknown strategy: {strategy}")
        self.epsilon = config.BANDIT_EPSILON if epsilon is None else epsilon
        self.strategy = strategy
        self.storage_path = storage_path or config.BANDIT_TABLE_PATH
        self.actions = list(config.DIFFICULTY_TIERS)
        self.multipliers = dict(multipliers or config.BANDIT_MULTIPLIERS)
        self._store_cache = None
        self.q_table = self._load_q_table()

    @property
    def _store(self):
        """Resolved from `storage_path` on each access, not captured at init."""
        if self._store_cache is None or self._store_cache.path != self.storage_path:
            self._store_cache = JsonStore(self.storage_path)
        return self._store_cache
        
    def _load_q_table(self):
        return self._normalise(self._store.read())

    def _initial_arms(self, state):
        """Beta priors for a state no learner has reached yet.

        Without this, Thompson sampling over uniform priors routes a third of
        first-time learners to the hardest tier. The prior favours the easiest
        tier and is overridden by a handful of observations.
        """
        favoured = config.BANDIT_PRIOR_TIER
        arms = {}
        for action in self.actions:
            alpha = config.BANDIT_PRIOR_PSEUDOCOUNT if action == favoured else 1.0
            arms[action] = {"q_value": alpha / (alpha + 1.0), "count": 0,
                            "alpha": alpha, "beta": 1.0}
        return arms

    def _normalise(self, data):
        """Fill in Beta parameters for tables written by earlier versions."""
        for state in data:
            for action in self.actions:
                if action not in data[state]:
                    data[state][action] = {"q_value": 0.5, "count": 0}
                item = data[state][action]
                if "alpha" not in item or "beta" not in item:
                    q = item.get("q_value", 0.5)
                    c = item.get("count", 0)
                    # Reconstruct pseudo-counts matching the recorded mean
                    item["alpha"] = max(0.1, q * max(2.0, float(c)))
                    item["beta"] = max(0.1, (1.0 - q) * max(2.0, float(c)))
        return data

    def _save_q_table(self):
        self._store.write(self.q_table)

    def _get_state_key(self, cluster, mastery):
        if mastery > config.MASTERY_BIN_HIGH:
            mastery_bin = "High"
        elif mastery > config.MASTERY_BIN_MEDIUM:
            mastery_bin = "Medium"
        else:
            mastery_bin = "Low"
        return f"{cluster}_{mastery_bin}"
        
    def get_action(self, cluster, mastery):
        state = self._get_state_key(cluster, mastery)

        # Read through to disk so that updates made by other workers are seen.
        self.q_table = self._normalise(self._store.read())
        if state not in self.q_table:
            def seed(data):
                self._normalise(data)
                # Beta(1, 1) prior, i.e. uniform over the arm's success rate
                data.setdefault(state, self._initial_arms(state))
                return data
            self.q_table = self._store.update(seed)

        if self.epsilon > 0.0 and random.random() < self.epsilon:
            return random.choice(self.actions)

        def utility(a):
            node = self.q_table[state][a]
            alpha, beta = node["alpha"], node["beta"]
            if self.strategy == "greedy":
                rate = alpha / (alpha + beta)
            else:
                rate = random.betavariate(alpha, beta)
            return rate * self.multipliers[a]

        return max(self.actions, key=utility)
            
    def update_policy(self, cluster, mastery, action, score):
        """
        Updates the Beta distribution parameters based on continuous score reward.
        Normalized reward r = Score / 100.0 in [0, 1].
        Action selection applies utility weights w_a to sample theta_a * w_a.
        """
        if action not in self.actions:
            return
            
        # Normalized score reward in [0, 1] without double-weighting
        r = max(0.0, min(1.0, float(score) / 100.0))
        state = self._get_state_key(cluster, mastery)

        def mutate(data):
            # Re-read and increment inside the lock: reading the counts outside
            # it would let concurrent updates for the same arm overwrite each
            # other, silently discarding observations.
            self._normalise(data)
            arm = data.setdefault(state, self._initial_arms(state))[action]
            arm["alpha"] += r
            arm["beta"] += (1.0 - r)
            arm["count"] += 1
            # q_value is kept equal to the Beta posterior mean
            arm["q_value"] = arm["alpha"] / (arm["alpha"] + arm["beta"])
            return data

        self.q_table = self._store.update(mutate)

bandit_adapter = ContextualBanditAdapter()

