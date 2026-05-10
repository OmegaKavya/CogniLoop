from backend.repositories.base_repository import BaseJsonRepository

class UserRepository(BaseJsonRepository):
    def __init__(self, file_path="data/users.json"):
        super().__init__(file_path)
        
    def find_by_email(self, email):
        users = self.get_all()
        if not isinstance(users, list):
            users = []
        for user in users:
            if user.get("email") == email:
                return user
        return None
        
    def save(self, user_id, user_data):
        users = self.get_all()
        if not isinstance(users, list):
            users = []
        # Update if exists
        for i, u in enumerate(users):
            if u.get('id') == user_id:
                users[i] = user_data
                self._write_data(users)
                return
        users.append(user_data)
        self._write_data(users)

class UserProgressRepository(BaseJsonRepository):
    def __init__(self, file_path="data/user_progress.json"):
        super().__init__(file_path)
        
    def get_progress(self, user_id, topic_id):
        data = self.get_all()
        user_data = data.get(str(user_id), {})
        return user_data.get(topic_id, {})
        
    def save_progress(self, user_id, topic_id, progress_data):
        data = self.get_all()
        if str(user_id) not in data:
            data[str(user_id)] = {}
        data[str(user_id)][topic_id] = progress_data
        self._write_data(data)

class QuizAttemptRepository(BaseJsonRepository):
    def __init__(self, file_path="data/quiz_attempts.json"):
        super().__init__(file_path)
        
    def get_user_attempts(self, user_id):
        attempts = self.get_all()
        if not isinstance(attempts, list):
            attempts = []
        return [a for a in attempts if str(a.get('user_id')) == str(user_id)]
        
    def add_attempt(self, attempt_data):
        attempts = self.get_all()
        if not isinstance(attempts, list):
            attempts = []
        attempts.append(attempt_data)
        self._write_data(attempts)

class VideoRepository(BaseJsonRepository):
    def __init__(self, file_path="data/videos.json"):
        super().__init__(file_path)
        
    def get_all_videos(self):
        # videos.json is a list, not a dict in current schema
        data = self._read_data()
        return data if isinstance(data, list) else []
        
    def get_by_id(self, video_id):
        videos = self.get_all_videos()
        for v in videos:
            if v.get('id') == video_id:
                return v
        return None

# Singleton instances for DI
user_repo = UserRepository()
progress_repo = UserProgressRepository()
quiz_repo = QuizAttemptRepository()
video_repo = VideoRepository()
