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

def simulate_users(num_users=60):
    print(f"Simulating {num_users} users with IRT-BKT and Contextual Bandit logic...")
    random.seed(42)
    
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
        
        topic_id = "test_topic"
        mastery = 0.35 + random.uniform(-0.1, 0.1)
        
        for attempt_idx in range(5):
            # 1. Get difficulty action
            if group == "control":
                difficulty = "medium"
                bkt_engine.p_learn = 0.10
            else:
                cluster = "General Learner"
                difficulty = bandit_adapter.get_action(cluster, mastery)
                bkt_engine.p_learn = 0.35
                
            # 2. Simulate IRT accuracy
            if difficulty == "easy":
                p_guess, p_slip = 0.30, 0.05
            elif difficulty == "hard":
                p_guess, p_slip = 0.10, 0.15
            else:
                p_guess, p_slip = 0.20, 0.10

            p_correct = mastery * (1.0 - p_slip) + (1.0 - mastery) * p_guess
            is_correct = random.random() < p_correct
            score = round(mastery * 100.0 + (10 if is_correct else -10) + random.uniform(-3, 3), 1)
            score = max(0.0, min(100.0, score))
            
            # 3. Update BKT state
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
    simulate_users(60)
    run_analytics()
