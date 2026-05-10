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
