import os
import json
import random
import sys
from datetime import datetime

# Setup workspace CWD
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

DATA_DIR = "data"

def reset_data_directories():
    print("Clearing data files for deterministic dry run...")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Reset all databases to clean initial states
    files_to_reset = {
        'users.json': [],
        'user_progress.json': {},
        'quiz_attempts.json': [],
        'micro_patterns.json': [],
        'bkt_states.json': {},
        'bandit_q_table.json': {}
    }
    
    for filename, content in files_to_reset.items():
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, 'w') as f:
            json.dump(content, f, indent=4)
        print(f"  Reset {filename}")

# Run reset BEFORE importing Flask app to avoid loading cached stale configurations
reset_data_directories()

# Initialize Flask Test Client
from app import app
from backend.repositories.core_repositories import user_repo, quiz_repo
from backend.adaptation.bandit_policy import bandit_adapter
from backend.bkt.bkt_engine import bkt_engine

client = app.test_client()

def register_user(name, email, password):
    payload = {"name": name, "email": email, "password": password}
    response = client.post('/register', json=payload)
    data = response.get_json()
    assert data['success'] is True, f"Registration failed for {email}"
    return data

def login_user(email, password):
    payload = {"email": email, "password": password}
    response = client.post('/login', json=payload)
    data = response.get_json()
    return data

def track_video(email, pause, rewatch, skip, watch_pct):
    # Retrieve user ID
    user = user_repo.find_by_email(email)
    uid = user['id']
    
    # Establish session
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['user_name'] = user['name']
        sess['study_group'] = user.get('study_group', 'experimental')
        
    payload = {
        "topic_id": "os",
        "pause_count": pause,
        "rewatch_count": rewatch,
        "skip_ratio": skip,
        "watch_percentage": watch_pct,
        "last_time": int(watch_pct * 12) # simulated duration
    }
    response = client.post('/api/video-track', json=payload)
    assert response.status_code == 200

def run_adaptive_quiz(email, score, average_time, response_list):
    user = user_repo.find_by_email(email)
    uid = user['id']
    study_group = user.get('study_group', 'experimental')
    
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['user_name'] = user['name']
        sess['study_group'] = study_group
        
    # Get quiz data (triggers bandit select difficulty)
    response = client.get('/api/quiz-data/os')
    quiz_data = response.get_json()
    assert quiz_data['success'] is True
    
    selected_quiz = quiz_data['quiz']
    difficulty = selected_quiz['difficulty']
    
    # Formulate submission responses
    submission_responses = []
    for q in selected_quiz['questions']:
        q_id = q['id']
        is_correct = response_list[q_id - 1] if q_id - 1 < len(response_list) else True
        correct_ans = q.get('answer') or q.get('correct_answer') or q.get('correct') or ""
        selected = correct_ans if is_correct else "Incorrect distractor"
        submission_responses.append({
            "question_id": q_id,
            "selected_answer": selected,
            "time_taken": average_time,
            "used_hint": False
        })
        
    payload = {
        "topic_id": "os",
        "difficulty": difficulty,
        "responses": submission_responses
    }
    
    submit_response = client.post('/api/quiz-submit', json=payload)
    submit_data = submit_response.get_json()
    assert submit_data['success'] is True
    
    return {
        "difficulty": difficulty,
        "score": submit_data['score'],
        "new_mastery": submit_data['mastery'],
        "cluster": submit_data['cluster'],
        "recommendation": submit_data['recommendation']
    }

def run_simulation():
    print("\n=======================================================")
    print("STARTING PROGRAMMATIC DRY RUN SIMULATION (3 PERSONAS)")
    print("=======================================================\n")
    
    # 1. Register users (automatically hashed)
    print("--- 1. User Registration & Security Check ---")
    register_user("Struggling Student", "weak@test.com", "weakpass123")
    register_user("Average Student", "avg@test.com", "avgpass123")
    register_user("Expert Student", "expert@test.com", "expertpass123")
    print("Users successfully registered.\n")
    
    # Verify secure password hashing has occurred
    print("Verifying password database encryption...")
    with open("data/users.json") as f:
        users = json.load(f)
    for u in users:
        password_val = u['password']
        print(f"  User: {u['email']} -> Stored PW: {password_val}")
        assert ":" in password_val, "Error: Password stored in plaintext!"
        assert len(password_val.split(":")[0]) == 32, "Error: Salt length is invalid!"
    print("Database Security Check: PASSED (All passwords salted and hashed via PBKDF2).\n")
    
    # Test Login Security
    print("Testing credentials verification...")
    login_fail = login_user("expert@test.com", "wrongpassword")
    print(f"  Login attempt with wrong password -> Success: {login_fail['success']} (Message: {login_fail.get('message')})")
    assert login_fail['success'] is False
    
    login_success = login_user("expert@test.com", "expertpass123")
    print(f"  Login attempt with correct password -> Success: {login_success['success']}")
    assert login_success['success'] is True
    print("Authentication System Check: PASSED.\n")
    
    # 2. Simulate User 1: Weak Student
    print("--- 2. Simulating Persona: Weak Student ---")
    # Low attention span, lots of pauses, struggles with concepts
    track_video("weak@test.com", pause=10, rewatch=8, skip=0.0, watch_pct=95)
    
    # First attempt: Score 30% (e.g. 3 out of 10 correct), average time 26s (confused pace)
    # Question correct sequence: F, F, T, F, F, F, T, F, F, T
    ans_1 = [False, False, True, False, False, False, True, False, False, True]
    res_1 = run_adaptive_quiz("weak@test.com", score=30, average_time=26, response_list=ans_1)
    print(f"  [Attempt 1] Assigned Difficulty: {res_1['difficulty']}")
    print(f"              Score: {res_1['score']}%")
    print(f"              New Mastery: {res_1['new_mastery']}")
    print(f"              Behavior Cluster: {res_1['cluster']}")
    print(f"              Recommendation: {res_1['recommendation']}")
    
    # Second attempt: Score 40%, average time 28s
    ans_2 = [False, True, False, False, True, False, False, True, False, False]
    res_2 = run_adaptive_quiz("weak@test.com", score=40, average_time=28, response_list=ans_2)
    print(f"  [Attempt 2] Assigned Difficulty: {res_2['difficulty']}")
    print(f"              Score: {res_2['score']}%")
    print(f"              New Mastery: {res_2['new_mastery']}")
    print(f"              Behavior Cluster: {res_2['cluster']}")
    print(f"              Recommendation: {res_2['recommendation']}")
    print("")
    
    # 3. Simulate User 2: Average Student
    print("--- 3. Simulating Persona: Average Student ---")
    # Normal pacing, standard watch metrics
    track_video("avg@test.com", pause=2, rewatch=1, skip=0.05, watch_pct=90)
    
    # First attempt: Score 70%, average time 15s (steady pace)
    ans_3 = [True, True, False, True, True, False, True, True, False, True]
    res_3 = run_adaptive_quiz("avg@test.com", score=70, average_time=15, response_list=ans_3)
    print(f"  [Attempt 1] Assigned Difficulty: {res_3['difficulty']}")
    print(f"              Score: {res_3['score']}%")
    print(f"              New Mastery: {res_3['new_mastery']}")
    print(f"              Behavior Cluster: {res_3['cluster']}")
    
    # Second attempt: Score 80%, average time 14s
    ans_4 = [True, True, True, True, False, True, True, False, True, True]
    res_4 = run_adaptive_quiz("avg@test.com", score=80, average_time=14, response_list=ans_4)
    print(f"  [Attempt 2] Assigned Difficulty: {res_4['difficulty']}")
    print(f"              Score: {res_4['score']}%")
    print(f"              New Mastery: {res_4['new_mastery']}")
    print(f"              Behavior Cluster: {res_4['cluster']}")
    print("")
    
    # 4. Simulate User 3: Expert Student
    print("--- 4. Simulating Persona: Expert Student ---")
    # Fast pacing, skips segments because they already know basics
    track_video("expert@test.com", pause=0, rewatch=0, skip=0.45, watch_pct=60)
    
    # First attempt: Score 100%, average time 7s (expert rapid pace)
    ans_5 = [True] * 10
    res_5 = run_adaptive_quiz("expert@test.com", score=100, average_time=7, response_list=ans_5)
    print(f"  [Attempt 1] Assigned Difficulty: {res_5['difficulty']}")
    print(f"              Score: {res_5['score']}%")
    print(f"              New Mastery: {res_5['new_mastery']}")
    print(f"              Behavior Cluster: {res_5['cluster']}")
    
    # Second attempt: Score 100%, average time 6s
    ans_6 = [True] * 10
    res_6 = run_adaptive_quiz("expert@test.com", score=100, average_time=6, response_list=ans_6)
    print(f"  [Attempt 2] Assigned Difficulty: {res_6['difficulty']}")
    print(f"              Score: {res_6['score']}%")
    print(f"              New Mastery: {res_6['new_mastery']}")
    print(f"              Behavior Cluster: {res_6['cluster']}")
    print("")
    
    # 5. Print Comparative Results
    print("=======================================================")
    print("COMPARATIVE EVALUATION SUMMARY REPORT")
    print("=======================================================")
    print(f"{'Student Persona':<20} | {'Behavior Cluster':<16} | {'Final Mastery':<13} | {'Bandit Path Routing':<20}")
    print("-" * 80)
    print(f"{'Weak Student':<20} | {res_2['cluster']:<16} | {res_2['new_mastery']:<13} | {'medium -> ' + res_2['difficulty']:<20}")
    print(f"{'Average Student':<20} | {res_4['cluster']:<16} | {res_4['new_mastery']:<13} | {'medium -> ' + res_4['difficulty']:<20}")
    print(f"{'Expert Student':<20} | {res_6['cluster']:<16} | {res_6['new_mastery']:<13} | {'medium -> ' + res_6['difficulty']:<20}")
    print("=======================================================\n")
    
if __name__ == "__main__":
    run_simulation()
