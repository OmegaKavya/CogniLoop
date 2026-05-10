import json
import os
import random

class ContextualBanditAdapter:
    """
    Epsilon-Greedy Contextual Bandit for Adaptive Difficulty Selection.
    Replaces static heuristic rules with a learning policy that maps 
    (Cluster + Mastery) -> Difficulty.
    """
    def __init__(self, epsilon=0.2, storage_path="data/bandit_q_table.json"):
        self.epsilon = epsilon
        self.storage_path = storage_path
        self.actions = ["easy", "medium", "hard"]
        self.q_table = self._load_q_table()
        
    def _load_q_table(self):
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
            
    def _save_q_table(self):
        # Ensure dir exists
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.q_table, f, indent=4)
            
    def _get_state_key(self, cluster, mastery):
        mastery_bin = "High" if mastery > 0.75 else "Medium" if mastery > 0.4 else "Low"
        return f"{cluster}_{mastery_bin}"
        
    def get_action(self, cluster, mastery):
        state = self._get_state_key(cluster, mastery)
        
        if state not in self.q_table:
            # Initialize optimistic Q-values to encourage exploration initially
            self.q_table[state] = {a: {"q_value": 0.5, "count": 0} for a in self.actions}
            self._save_q_table()
            
        # Epsilon-greedy selection
        if random.random() < self.epsilon:
            selected_action = random.choice(self.actions)
        else:
            # Exploit best action
            selected_action = max(self.q_table[state].keys(), key=lambda a: self.q_table[state][a]["q_value"])
            
        return selected_action
            
    def update_policy(self, cluster, mastery, action, score):
        """
        Updates the Q-value for the taken action based on the reward.
        Reward = (score / 100) * difficulty_multiplier
        This encourages pushing the user to harder difficulties IF they can maintain high scores.
        """
        if action not in self.actions:
            return
            
        multipliers = {"easy": 0.8, "medium": 1.0, "hard": 1.2}
        reward = (score / 100.0) * multipliers[action]
        
        state = self._get_state_key(cluster, mastery)
        if state not in self.q_table:
            self.q_table[state] = {a: {"q_value": 0.5, "count": 0} for a in self.actions}
            
        old_q = self.q_table[state][action]["q_value"]
        count = self.q_table[state][action]["count"]
        
        # Incremental average update
        new_q = old_q + (1 / (count + 1)) * (reward - old_q)
        
        self.q_table[state][action]["q_value"] = new_q
        self.q_table[state][action]["count"] = count + 1
        
        self._save_q_table()

bandit_adapter = ContextualBanditAdapter()
