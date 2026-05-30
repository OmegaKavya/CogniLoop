import json
import os

class BKTEngine:
    def __init__(self, storage_path='data/bkt_states.json'):
        self.storage_path = storage_path
        self.p_init = 0.3    
        self.p_learn = 0.2   
        self.p_guess = 0.2   
        self.p_slip = 0.1 
        self._ensure_storage()

    def _ensure_storage(self):
        if not os.path.exists(self.storage_path):
            with open(self.storage_path, 'w') as f:
                json.dump({}, f)

    def get_mastery(self, user_id, concept_id):
        try:
            with open(self.storage_path, 'r') as f:
                states = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            states = {}
        
        user_state = states.get(user_id, {})
        return user_state.get(concept_id, self.p_init)

    def update_mastery(self, user_id, concept_id, is_correct, difficulty=None):
        p_known_prev = self.get_mastery(user_id, concept_id)

        # Baseline guess/slip parameters
        p_guess = self.p_guess
        p_slip = self.p_slip

        # Dynamic mapping grounded in Item Response Theory (IRT)
        if difficulty:
            diff = str(difficulty).lower().strip()
            if diff == "easy":
                p_guess = 0.30  # High probability of guessing an easy question correctly
                p_slip = 0.05   # Low probability of slipping (making an error)
            elif diff == "hard":
                p_guess = 0.10  # Low probability of guessing a hard question
                p_slip = 0.15   # High probability of slipping due to complex calculations
            elif diff == "medium":
                p_guess = 0.20  # Baseline medium guess
                p_slip = 0.10   # Baseline medium slip

        if is_correct:
            p_known_ev = (p_known_prev * (1 - p_slip)) / \
                         (p_known_prev * (1 - p_slip) + (1 - p_known_prev) * p_guess)
        else:
            p_known_ev = (p_known_prev * p_slip) / \
                         (p_known_prev * p_slip + (1 - p_known_prev) * (1 - p_guess))

        p_known_new = p_known_ev + (1 - p_known_ev) * self.p_learn

        self._save_state(user_id, concept_id, p_known_new)
        return p_known_new

    def get_all_states(self):
        """Return the full states dict {user_id: {concept_id: mastery}}."""
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}


    def _save_state(self, user_id, concept_id, mastery_prob):
        try:
            with open(self.storage_path, 'r') as f:
                states = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            states = {}

        if user_id not in states:
            states[user_id] = {}
        states[user_id][concept_id] = round(mastery_prob, 4)
        
        with open(self.storage_path, 'w') as f:
            json.dump(states, f, indent=4)

bkt_engine = BKTEngine()
