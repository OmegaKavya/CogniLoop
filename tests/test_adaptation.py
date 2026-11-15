import os
import tempfile
import pandas as pd
from backend.adaptation.speed_adaptation import SpeedAdaptation
from backend.adaptation.micro_pattern import MicroPatternManager

def test_speed_label_boundaries():
    adapter = SpeedAdaptation(fast_threshold=10, slow_threshold=25)
    assert adapter.speed_label(8) == "Fast"
    assert adapter.speed_label(15) == "Steady"
    assert adapter.speed_label(30) == "Slow"
    # Thresholds themselves are "Steady": strictly below is Fast, strictly
    # above is Slow.
    assert adapter.speed_label(10) == "Steady"
    assert adapter.speed_label(25) == "Steady"


def test_speed_adaptation_does_not_touch_difficulty():
    """Difficulty has one owner, the bandit.

    This class used to adjust the tier as well, which would have put a second
    policy on the same variable - the defect that let the arm selected, the arm
    served and the arm credited all differ.
    """
    adapter = SpeedAdaptation()
    assert not hasattr(adapter, "adapt")
    assert not hasattr(adapter, "_increase_difficulty")
    assert not hasattr(adapter, "_decrease_difficulty")


def test_app_uses_the_shared_thresholds():
    """The submit handler duplicated these thresholds inline; a change here
    then left the two disagreeing."""
    import app
    from backend import config
    assert app.speed_adapter.fast_threshold == config.SPEED_FAST_SECONDS
    assert app.speed_adapter.slow_threshold == config.SPEED_SLOW_SECONDS

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
