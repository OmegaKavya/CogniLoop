import os
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

def init_data():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    files_to_init = {
        'users.json': [],
        'user_progress.json': {},
        'quiz_attempts.json': [],
        'micro_patterns.json': [],
        'bkt_states.json': {}
    }

    for filename, initial_content in files_to_init.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump(initial_content, f, indent=4)
            print(f"Created {filename}")
        else:
            print(f"Skipped {filename} (already exists)")

if __name__ == "__main__":
    print("Initializing data directory...")
    init_data()
    print("Done.")
