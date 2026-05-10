from unittest.mock import patch, MagicMock
from backend.quiz.quiz_generator import QuizGenerator

def test_get_question_count():
    gen = QuizGenerator()
    
    # Low mastery -> higher question count
    count_low = gen._get_question_count(mastery=0.2, speed_label="Steady")
    assert 9 <= count_low <= 13 # base max (12) + 1
    
    # High mastery -> lower question count
    count_high = gen._get_question_count(mastery=0.9, speed_label="Steady")
    assert 8 <= count_high <= 12 # base min (9) - 1
    
def test_ensure_unique_questions():
    gen = QuizGenerator()
    questions = [
        {"text": "What is OS?"},
        {"text": "What is OS? "}, # Duplicate
        {"text": "Define kernel."}
    ]
    
    unique = gen._ensure_unique_questions(questions, num_questions=5, avoid_questions=["Define kernel."])
    
    # Should avoid the duplicate and the one in avoid_questions
    assert len(unique) == 1
    assert unique[0]["text"] == "What is OS?"
    assert unique[0]["id"] == 1

@patch('requests.post')
def test_generate_quiz_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'response': '{"questions": [{"text": "Q1", "options": ["A", "B"], "answer": "A", "hint": "H1"}]}'
    }
    mock_post.return_value = mock_response

    gen = QuizGenerator()
    quiz = gen.generate_quiz("topic_1", "Test Topic", youtube_id=None)
    
    assert quiz['num_questions'] == 1
    assert quiz['questions'][0]['text'] == "Q1"

@patch('requests.post')
def test_generate_quiz_fallback(mock_post):
    mock_post.side_effect = Exception("Connection refused")
    
    gen = QuizGenerator()
    quiz = gen.generate_quiz("topic_1", "Test Topic", youtube_id=None)
    
    # Should fallback to static questions
    assert quiz['num_questions'] > 0
    assert "Test Topic" in quiz['questions'][0]['text'] or "Test Topic" in quiz['questions'][1]['text']
