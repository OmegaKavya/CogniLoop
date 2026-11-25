import json
import os
import tempfile
from datetime import datetime

from backend import config
from backend.storage import open_store, StorageCorrupted
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


def _write_atomically(path, payload):
    """Write bytes so a reader sees the old file or the new one, never half.

    The model is read on every quiz submission; writing it in place let a
    submission unpickle a partly written file.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".pkl")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

class MicroPatternManager:
    FEATURE_COLUMNS = ['pause_count', 'rewatch_count', 'skip_ratio', 'watch_percentage']

    def __init__(self, storage_path=None, model_path=None):
        storage_path = storage_path or config.MICRO_PATTERNS_PATH
        model_path = model_path or config.CLUSTERING_MODEL_PATH
        self.storage_path = storage_path
        self.model_path = model_path
        self._store_cache = None
        # The fitted model, held against the (mtime, size) it was read from.
        self._cached_model = None
        self._cached_signature = None
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        self._ensure_storage()

    @property
    def _store(self):
        """Resolved from `storage_path` on each access, not captured at init."""
        if self._store_cache is None or self._store_cache.path != self.storage_path:
            self._store_cache = open_store(self.storage_path, default=list)
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
        except StorageCorrupted as exc:
            # Degrade rather than fail: this feeds behaviour clustering, which
            # already falls back to "General Learner", and a learner's
            # submission must not be blocked because telemetry is unreadable.
            # But say so - silence here is how a corrupt document goes
            # unnoticed until something else trips over it.
            print(f"[MicroPattern] behaviour log unreadable, clustering "
                  f"degraded: {exc}")
            return {}
        except Exception:
            return {}
        if not isinstance(events, list):
            return {}
        for event in reversed(events):
            if event.get("user_id") == user_id and event.get("video_id") == video_id:
                return event
        return {}

    def train_model(self):
        """Fit the clustering model on the behaviour log and save it.

        Reads through the store, so against Postgres it trains on production
        data. It used to require the log to exist as a local file first, which
        it never does when the data lives in Postgres, so it silently trained
        nothing there.
        """
        if not KMeans:
            return False
        data = self._store.read()
        if not isinstance(data, list):
            return False
        data = [row for row in data if isinstance(row, dict)]
        if len(data) < 5:
            return False

        df = pd.DataFrame(data)
        if any(column not in df.columns for column in self.FEATURE_COLUMNS):
            return False
        X = df[self.FEATURE_COLUMNS].fillna(0)
        
        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        kmeans.fit(X)
        # Invalidate, so a refit is visible to this process immediately rather
        # than only once the file signature happens to differ.
        self._cached_model = None
        self._cached_signature = None
        _write_atomically(self.model_path, pickle.dumps({
            "model": kmeans,
            "sklearn_version": sklearn_version,
            "feature_columns": self.FEATURE_COLUMNS
        }))
        return True

    def _model_signature(self):
        """Identity of the file on disk, so a changed model is picked up."""
        try:
            stat = os.stat(self.model_path)
        except OSError:
            return None
        # The inode too: a model replaced atomically within one timestamp tick
        # and at the same size is otherwise indistinguishable from the old one.
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _load_model(self):
        """The fitted model, unpickled at most once per version of the file.

        Two problems lived here, and both were in the request path.

        The model was unpickled from disk on every single call, and
        `predict_cluster` is called on every quiz submission. Deserialising a
        scikit-learn estimator is not free, and nothing about it changes
        between requests.

        Worse, a version warning triggered `train_model()` *inline* - a full
        KMeans fit over every behaviour row ever recorded, inside a learner's
        submission, on a single synchronous worker. The one condition under
        which the model is least trustworthy was also the condition that made
        the slowest possible thing happen while someone waited.

        Now: cached against the file's mtime and size, so a retrained model is
        picked up without a restart, and a version mismatch refuses the model
        rather than refitting it. Callers already fall back to "General
        Learner", which is the correct behaviour for a model that cannot be
        trusted. Refitting is an offline job - run `train_model()` from a
        script, not from a request.
        """
        signature = self._model_signature()
        if signature is None:
            return None
        if self._cached_signature == signature:
            return self._cached_model

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", InconsistentVersionWarning)
            with open(self.model_path, 'rb') as f:
                loaded = pickle.load(f)

        has_version_warning = any(
            issubclass(w.category, InconsistentVersionWarning) for w in caught
        )

        model = loaded.get("model") if isinstance(loaded, dict) else loaded

        if has_version_warning:
            print(f"[MicroPattern] {self.model_path} was fitted by a different "
                  f"scikit-learn version and will not be used. Behaviour "
                  f"clustering falls back to 'General Learner' until it is "
                  f"refitted offline with train_model().")
            model = None

        # Cached either way: a model that cannot be used must not be re-read
        # and re-rejected on every subsequent request.
        self._cached_signature = signature
        self._cached_model = model
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
