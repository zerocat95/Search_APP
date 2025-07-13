
import threading

class IndexerState:
    """A simple singleton class to hold the live state of the indexer."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IndexerState, cls).__new__(cls)
            cls._instance.active_threads = 0
            # A set to keep track of all active DynamicThreadPoolExecutor instances
            cls._instance.active_executors = set()
            cls._instance.lock = threading.Lock()
        return cls._instance

# Global instance
indexer_state = IndexerState()
