import json
import os
import fcntl

class BaseJsonRepository:
    """Base repository for JSON file-based persistence. 
    Implements basic file locking to prevent corruption during concurrent local usage."""
    
    def __init__(self, file_path):
        self.file_path = file_path
        self._ensure_exists()
        
    def _ensure_exists(self):
        if not os.path.exists(self.file_path):
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w') as f:
                json.dump({}, f)
                
    def _read_data(self):
        try:
            with open(self.file_path, 'r') as f:
                # Use fcntl for advisory locking (Unix only, sufficient for local prototype)
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_data(self, data):
        with open(self.file_path, 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=4)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def get_all(self):
        return self._read_data()
        
    def get_by_id(self, item_id):
        return self._read_data().get(str(item_id))
        
    def save(self, item_id, item_data):
        data = self._read_data()
        data[str(item_id)] = item_data
        self._write_data(data)
        
    def delete(self, item_id):
        data = self._read_data()
        if str(item_id) in data:
            del data[str(item_id)]
            self._write_data(data)
