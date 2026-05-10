import os
import tempfile
import pandas as pd
from backend.adaptation.speed_adaptation import SpeedAdaptation
from backend.adaptation.micro_pattern import MicroPatternManager

def test_speed_adaptation_fast_increase():
    adapter = SpeedAdaptation(fast_threshold=10, slow_threshold=25)
    
    # Fast and high score -> increase difficulty
    result = adapter.adapt(score=85, avg_time=8, current_difficulty="easy")
    assert result["new_difficulty"] == "medium"
    assert result["speed_label"] == "Fast"

    # Fast but low score -> no increase
    result2 = adapter.adapt(score=70, avg_time=8, current_difficulty="easy")
    assert result2["new_difficulty"] == "easy"
    
def test_speed_adaptation_slow_decrease():
    adapter = SpeedAdaptation(fast_threshold=10, slow_threshold=25)
    
    # Slow and low score -> decrease difficulty
    result = adapter.adapt(score=40, avg_time=30, current_difficulty="hard")
    assert result["new_difficulty"] == "medium"
    assert result["speed_label"] == "Slow"

def test_micro_pattern_log_interaction():
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_json, \
         tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as tmp_pkl:
        tmp_json.write(b'[]')
        tmp_json.flush()
        tmp_json_path = tmp_json.name
        tmp_pkl_path = tmp_pkl.name
        
    try:
        manager = MicroPatternManager(storage_path=tmp_json_path, model_path=tmp_pkl_path)
        
        # Log an interaction
        success = manager.log_interaction("user_1", "video_1", {
            "pause_count": 2,
            "rewatch_count": 1,
            "skip_ratio": 0.1,
            "watch_percentage": 90
        })
        assert success is True
        
        # Without a trained model, it should fallback to General Learner
        cluster = manager.predict_cluster({})
        assert cluster == "General Learner"
        
    finally:
        if os.path.exists(tmp_json_path):
            os.remove(tmp_json_path)
        if os.path.exists(tmp_pkl_path):
            os.remove(tmp_pkl_path)
