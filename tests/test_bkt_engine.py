import os
import tempfile
from backend.bkt.bkt_engine import BKTEngine

def test_bkt_engine_initialization():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        engine = BKTEngine(storage_path=tmp_path)
        assert os.path.exists(tmp_path)
        
        # Test initial mastery
        mastery = engine.get_mastery("user_1", "concept_1")
        assert mastery == engine.p_init # 0.3
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_bkt_engine_update_correct():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        engine = BKTEngine(storage_path=tmp_path)
        initial = engine.get_mastery("user_1", "concept_1")
        
        # Answer correctly
        new_mastery = engine.update_mastery("user_1", "concept_1", is_correct=True)
        assert new_mastery > initial
        
        # Ensure it was saved
        saved_mastery = engine.get_mastery("user_1", "concept_1")
        assert abs(saved_mastery - new_mastery) < 0.001
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_bkt_engine_update_incorrect():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        engine = BKTEngine(storage_path=tmp_path)
        
        # Answer incorrectly
        new_mastery = engine.update_mastery("user_1", "concept_2", is_correct=False)
        assert new_mastery < engine.p_init
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_bkt_engine_difficulty_aware_update():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        engine = BKTEngine(storage_path=tmp_path)
        
        # Test that an easy correct answer updates mastery differently than a hard correct answer
        # For easy: Guess = 0.30, Slip = 0.05
        # For hard: Guess = 0.10, Slip = 0.15
        
        # Correct answer on easy:
        mastery_easy = engine.update_mastery("user_easy", "concept_1", is_correct=True, difficulty="easy")
        
        # Reset storage to ensure isolated baseline state
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        engine_hard = BKTEngine(storage_path=tmp_path)
        mastery_hard = engine_hard.update_mastery("user_hard", "concept_1", is_correct=True, difficulty="hard")
        
        # A correct answer on a hard question should increase mastery MORE than on an easy question
        # because the probability of guessing is much lower (0.10 vs 0.30).
        assert mastery_hard > mastery_easy
        
        # Incorrect answer on easy vs hard:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        engine_err = BKTEngine(storage_path=tmp_path)
        mastery_easy_err = engine_err.update_mastery("user_easy", "concept_1", is_correct=False, difficulty="easy")
        
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        engine_err_hard = BKTEngine(storage_path=tmp_path)
        mastery_hard_err = engine_err_hard.update_mastery("user_hard", "concept_1", is_correct=False, difficulty="hard")
        
        # An incorrect answer on an easy question should decrease mastery MORE (lower value)
        # than on a hard question, because failing an easy question is a stronger indicator of concept gap.
        assert mastery_easy_err < mastery_hard_err
        
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
