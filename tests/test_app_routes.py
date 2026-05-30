import json
from unittest.mock import patch

def test_landing_page(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Personalized Learning" in response.data or b"Test Topic" in response.data

def test_register_login_flow(client):
    # Register
    res_reg = client.post('/register', json={
        "name": "Test User",
        "email": "test@test.com",
        "password": "password"
    })
    assert res_reg.status_code == 200
    assert res_reg.json['success'] is True
    
    # Logout
    res_logout = client.get('/logout', follow_redirects=True)
    assert res_logout.status_code == 200
    
    # Login
    res_login = client.post('/login', json={
        "email": "test@test.com",
        "password": "password"
    })
    assert res_login.status_code == 200
    assert res_login.json['success'] is True

def test_dashboard_requires_login(client):
    client.get('/logout') # Ensure logged out
    res = client.get('/dashboard', follow_redirects=False)
    assert res.status_code == 302 # Redirects to login

def test_dashboard_logged_in(client):
    # Register/Login
    client.post('/register', json={"name": "U", "email": "u@test.com", "password": "p"})
    
    res = client.get('/dashboard')
    assert res.status_code == 200
    assert b"Dashboard" in res.data or b"Test Topic" in res.data

@patch('backend.quiz.quiz_generator.quiz_gen.generate_quiz')
def test_api_quiz_data(mock_generate, client):
    # Login
    client.post('/register', json={"name": "U2", "email": "u2@test.com", "password": "p"})
    
    # Mock the generator
    mock_generate.return_value = {
        "difficulty": "medium",
        "questions": [{"id": 1, "text": "Q1", "options": ["A", "B"], "answer": "A"}],
        "num_questions": 1
    }
    
    res = client.get('/api/quiz-data/test_topic')
    assert res.status_code == 200
    assert res.json['success'] is True
    assert res.json['quiz']['num_questions'] == 1
    
@patch('backend.quiz.quiz_evaluator.evaluator.evaluate')
def test_api_quiz_submit(mock_evaluate, client):
    client.post('/register', json={"name": "U3", "email": "u3@test.com", "password": "p"})
    
    # Mock evaluate to return a fixed score
    mock_evaluate.return_value = {
        "score": 80,
        "avg_time": 12,
        "total_time": 12,
        "question_results": [{"question_id": 1, "is_correct": True, "feedback": "Good"}]
    }
    
    # Need to simulate having a quiz in session. Flask test_client allows session transaction
    with client.session_transaction() as sess:
        sess['current_quiz'] = {
            "questions": [{"id": 1, "text": "Q1", "answer": "A"}],
            "difficulty": "medium"
        }
    
    res = client.post('/api/quiz-submit', json={
        "topic_id": "test_topic",
        "responses": [{"question_id": 1, "selected_answer": "A", "time_taken": 12}],
        "difficulty": "medium"
    })
    
    assert res.status_code == 200
    assert res.json['success'] is True
    assert res.json['score'] == 80
