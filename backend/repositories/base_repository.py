from backend.storage import open_store


class BaseJsonRepository:
    """JSON file-backed persistence.

    Mutations run through JsonStore.update, which holds an exclusive lock across
    the whole read-modify-write and swaps the file in atomically. Doing the read
    and the write under separate locks loses concurrent updates.
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self._store_cache = None
        self._store.ensure_exists()

    @property
    def _store(self):
        """Resolved from `file_path` on each access, not captured at init.

        `file_path` is the single source of truth for where this repository
        reads and writes. Binding a store at construction time would silently
        ignore later reassignment, which is how tests redirect persistence to a
        temporary directory.
        """
        if self._store_cache is None or self._store_cache.path != self.file_path:
            self._store_cache = open_store(self.file_path)
        return self._store_cache

    def _read_data(self):
        return self._store.read()

    def _write_data(self, data):
        self._store.write(data)

    def get_all(self):
        return self._store.read()

    def get_by_id(self, item_id):
        return self._store.read().get(str(item_id))

    def save(self, item_id, item_data):
        def mutate(data):
            data[str(item_id)] = item_data
        self._store.update(mutate)

    def delete(self, item_id):
        def mutate(data):
            data.pop(str(item_id), None)
        self._store.update(mutate)
