import json
import os
import random

class ContextualBanditAdapter:
    """
    Thompson Sampling Contextual Bandit for Adaptive Difficulty Selection.
    Replaces Epsilon-Greedy with a Bayesian policy that maps 
    (Cluster + Mastery) -> Difficulty.
    Keeps backward-compatible Q-table structure.
    """
    def __init__(self, epsilon=0.2, storage_path="data/bandit_q_table.json"):
        self.epsilon = epsilon
        self.storage_path = storage_path
        self.actions = ["easy", "medium", "hard"]
        self.multipliers = {"easy": 0.8, "medium": 1.0, "hard": 1.2}
        self.q_table = self._load_q_table()
        
    def _load_q_table(self):
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                # Ensure backward compatibility by populating alpha/beta parameters if missing
                for state in data:
                    for action in self.actions:
                        if action not in data[state]:
                            data[state][action] = {"q_value": 0.5, "count": 0}
                        item = data[state][action]
                        if "alpha" not in item or "beta" not in item:
                            q = item.get("q_value", 0.5)
                            c = item.get("count", 0)
                            # Estimate historical counts
                            item["alpha"] = max(0.1, q * max(2.0, float(c)))
                            item["beta"] = max(0.1, (1.0 - q) * max(2.0, float(c)))
                return data
        except json.JSONDecodeError:
            return {}
            
    def _save_q_table(self):
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.q_table, f, indent=4)
            
    def _get_state_key(self, cluster, mastery):
        mastery_bin = "High" if mastery > 0.75 else "Medium" if mastery > 0.4 else "Low"
        return f"{cluster}_{mastery_bin}"
        
    def _ensure_alpha_beta_parameters(self, state):
        for a in self.actions:
            if a not in self.q_table[state]:
                self.q_table[state][a] = {"q_value": 0.5, "count": 0}
            item = self.q_table[state][a]
            if "alpha" not in item or "beta" not in item:
                q = item.get("q_value", 0.5)
                c = item.get("count", 0)
                # Reconstruct pseudo-observations representing the historical state
                item["alpha"] = max(0.1, q * max(2.0, float(c)))
                item["beta"] = max(0.1, (1.0 - q) * max(2.0, float(c)))

    def get_action(self, cluster, mastery):
        state = self._get_state_key(cluster, mastery)
        
        if state not in self.q_table:
            # Initialize with Beta(1, 1) prior representing a Uniform distribution
            self.q_table[state] = {
                a: {"q_value": 0.5, "count": 0, "alpha": 1.0, "beta": 1.0} 
                for a in self.actions
            }
            self._save_q_table()
        else:
            self._ensure_alpha_beta_parameters(state)
            
        # Exploration/Exploitation handling
        if random.random() < self.epsilon:
            # Epsilon-forced random exploration (primarily for testing purposes)
            selected_action = random.choice(self.actions)
        else:
            if self.epsilon == 0.0:
                # Force exploit mode: select the action with the maximum expected reward (posterior mean)
                selected_action = max(
                    self.actions,
                    key=lambda a: (self.q_table[state][a]["alpha"] / 
                                   (self.q_table[state][a]["alpha"] + self.q_table[state][a]["beta"])) * self.multipliers[a]
                )
            else:
                # Standard Thompson Sampling: sample expected performance from Beta distribution
                samples = {}
                for a in self.actions:
                    alpha = self.q_table[state][a]["alpha"]
                    beta = self.q_table[state][a]["beta"]
                    # Sample performance and multiply by difficulty weight
                    samples[a] = random.betavariate(alpha, beta) * self.multipliers[a]
                selected_action = max(samples.keys(), key=lambda a: samples[a])
            
        return selected_action
            
    def update_policy(self, cluster, mastery, action, score):
        """
        Updates the Beta distribution parameters based on continuous score reward.
        Normalized reward r in [0, 1].
        """
        if action not in self.actions:
            return
            
        reward = (score / 100.0) * self.multipliers[action]
        # Max reward is 1.2, so normalize to [0, 1] range
        r = max(0.0, min(1.0, reward / 1.2))
        
        state = self._get_state_key(cluster, mastery)
        if state not in self.q_table:
            self.q_table[state] = {
                a: {"q_value": 0.5, "count": 0, "alpha": 1.0, "beta": 1.0} 
                for a in self.actions
            }
        else:
            self._ensure_alpha_beta_parameters(state)
            
        # Update Beta parameters (fractional updates representing continuous outcomes)
        self.q_table[state][action]["alpha"] += r
        self.q_table[state][action]["beta"] += (1.0 - r)
        self.q_table[state][action]["count"] += 1
        
        # Keep q_value equal to the expected value (mean) of the Beta distribution
        alpha = self.q_table[state][action]["alpha"]
        beta = self.q_table[state][action]["beta"]
        self.q_table[state][action]["q_value"] = alpha / (alpha + beta)
        
        self._save_q_table()

bandit_adapter = ContextualBanditAdapter()
