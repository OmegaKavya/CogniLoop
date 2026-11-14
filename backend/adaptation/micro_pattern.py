import json
import os
from datetime import datetime

from backend import config
from backend.storage import JsonStore
import warnings
import pandas as pd
try:
    from sklearn.cluster import KMeans
    from sklearn import __version__ as sklearn_version
    from sklearn.exceptions import InconsistentVersionWarning
    import pickle
except ImportError:
    KMeans = None
    sklearn_version = None
    InconsistentVersionWarning = Warning

class MicroPatternManager:
    FEATURE_COLUMNS = ['pause_count', 'rewatch_count', 'skip_ratio', 'watch_percentage']

    def __init__(self, storage_path=None, model_path=None):
        storage_path = storage_path or config.MICRO_PATTERNS_PATH
        model_path = model_path or config.CLUSTERING_MODEL_PATH
        self.storage_path = storage_path
        self.model_path = model_path
        self._store_cache = None
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        self._ensure_storage()

    @property
    def _store(self):
        """Resolved from `storage_path` on each access, not captured at init."""
        if self._store_cache is None or self._store_cache.path != self.storage_path:
            self._store_cache = JsonStore(self.storage_path, default=list)
        return self._store_cache

    def _ensure_storage(self):
        self._store.ensure_exists()

    def log_interaction(self, user_id, video_id, interaction_data):
        """Append one interaction event.

        This is the highest-frequency write in the application: the player
        reports on pause, seek and progress. The previous implementation did an
        unlocked read-modify-write over the whole file, which under concurrency
        corrupted it -- and once corrupted, every later append failed too, so
        tracking and the clustering that depends on it stayed broken until
        someone deleted the file by hand.
        """
        log_entry = {
            "user_id": user_id,
            "video_id": video_id,
            "timestamp": datetime.now().isoformat(),
            **interaction_data
        }
        try:
            def mutate(events):
                events.append(log_entry)
                return events
            self._store.update_replacing(mutate, default=list)
            return True
        except Exception as e:
            print(f"Error logging micro-pattern: {e}")
            return False

    def latest_interaction(self, user_id, video_id):
        """Most recent recorded interaction for one learner and video, or {}."""
        try:
            events = self._store.read()
        except Exception:
            return {}
        if not isinstance(events, list):
            return {}
        for event in reversed(events):
            if event.get("user_id") == user_id and event.get("video_id") == video_id:
                return event
        return {}

    def train_model(self):
        if not KMeans or not os.path.exists(self.storage_path):
            return False
        data = self._store.read()
        if len(data) < 5:
            return False
        
        df = pd.DataFrame(data)
        X = df[self.FEATURE_COLUMNS]
        
        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        kmeans.fit(X)
        with open(self.model_path, 'wb') as f:
            pickle.dump({
                "model": kmeans,
                "sklearn_version": sklearn_version,
                "feature_columns": self.FEATURE_COLUMNS
            }, f)
        return True

    def _load_model(self):
        if not os.path.exists(self.model_path):
            return None

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", InconsistentVersionWarning)
            with open(self.model_path, 'rb') as f:
                loaded = pickle.load(f)

        has_version_warning = any(
            issubclass(w.category, InconsistentVersionWarning) for w in caught
        )

        model = loaded.get("model") if isinstance(loaded, dict) else loaded

        if has_version_warning:
            if self.train_model():
                with open(self.model_path, 'rb') as f:
                    refreshed = pickle.load(f)
                return refreshed.get("model") if isinstance(refreshed, dict) else refreshed
            return None

        return model

    def predict_cluster(self, interaction_data):
        if not os.path.exists(self.model_path):
            return "General Learner"
        
        try:
            model = self._load_model()
            if model is None:
                return "General Learner"

            vec_df = pd.DataFrame([{
                'pause_count': interaction_data.get('pause_count', 0),
                'rewatch_count': interaction_data.get('rewatch_count', 0),
                'skip_ratio': interaction_data.get('skip_ratio', 0),
                'watch_percentage': interaction_data.get('watch_percentage', 0)
            }], columns=self.FEATURE_COLUMNS)

            prediction = model.predict(vec_df)[0]
            labels = {
                0: "Steady Learner",
                1: "Detail-Oriented",
                2: "Fast-Paced"
            }
            return labels.get(prediction, "General Learner")
        except Exception as e:
            print(f"Clustering prediction error: {e}")
            return "General Learner"

mp_manager = MicroPatternManager()
