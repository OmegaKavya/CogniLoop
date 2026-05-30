import os
import sys
import random
from datetime import datetime

# Setup path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.repositories.core_repositories import user_repo, quiz_repo
from backend.analytics.metrics import analytics_engine
from backend.adaptation.bandit_policy import bandit_adapter
from backend.bkt.bkt_engine import bkt_engine

def simulate_users(num_users=40):
    print(f"Simulating {num_users} users...")
    
    # Generate users
    for i in range(num_users):
        uid = f"sim_user_{i}"
        group = "experimental" if i % 2 == 0 else "control"
        user_repo.save(uid, {
            "id": uid,
            "name": f"Simulated User {i}",
            "email": f"sim{i}@test.com",
            "password": "password",
            "study_group": group,
            "created_at": datetime.now().isoformat()
        })
        
        # Simulate 3 attempts per user
        topic_id = "test_topic"
        mastery = 0.3
        
        for attempt_idx in range(3):
            # 1. Get action
            if group == "control":
                difficulty = "medium"
            else:
                cluster = "General Learner"
                difficulty = bandit_adapter.get_action(cluster, mastery)
                
            # 2. Simulate score (Experimental group learns faster)
            base_score = 40 + (attempt_idx * 15)
            if group == "experimental":
                base_score += 15 # Boost for adaptive
            
            # Difficulty modifier
            if difficulty == "hard": base_score -= 10
            elif difficulty == "easy": base_score += 10
            
            score = max(0, min(100, base_score + random.randint(-5, 5)))
            
            # 3. Update state
            is_correct = score >= 70
            mastery = bkt_engine.update_mastery(uid, topic_id, is_correct, difficulty=difficulty)
            
            if group == "experimental":
                bandit_adapter.update_policy("General Learner", mastery, difficulty, score)
                
            # 4. Save attempt
            quiz_repo.add_attempt({
                "attempt_id": f"att_{uid}_{attempt_idx}",
                "user_id": uid,
                "topic_id": topic_id,
                "score": score,
                "mastery": mastery,
                "adaptation": {"new_difficulty": difficulty, "speed_label": "Steady"},
                "behavior_cluster": "General Learner",
                "timestamp": datetime.now().isoformat(),
                "question_results": []
            })
            
    print("Simulation complete.")
    
def run_analytics():
    print("Running Analytics Engine...")
    report = analytics_engine.generate_experiment_report()
    import json
    print(json.dumps(report, indent=4))
    
    assert "control" in report, "Control group missing"
    assert "experimental" in report, "Experimental group missing"
    assert "statistical_significance" in report, "Significance missing"
    
    print("Validation SUCCESS. Analytics pipeline handles simulated data perfectly.")

if __name__ == "__main__":
    simulate_users(60) # 30 control, 30 experimental
    run_analytics()
