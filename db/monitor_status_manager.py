# status_manager.py - Production-ready status management
import time


class StatusManager:
    """
    Manages monitor status with file-based SQLite + simple in-memory cache.
    
    This design:
    - Uses file DB as source of truth (crash-safe)
    - Caches status for fast reads (no repeated DB queries)
    - Automatically handles crash recovery
    - No sync complexity
    """
    
    def __init__(self, db_handler, poll_interval: int = 5):
        self.db = db_handler
        self.poll_interval = poll_interval
        self._status_cache = {}
        self._cache_timestamps = {}
        self._cache_ttl = 2  # seconds before cache refresh
    
    def get_status(self, monitor_id: int) -> str:
        """Get status with TTL-based caching."""
        # Return cached status if fresh
        now = time.time()
        if monitor_id in self._cache_timestamps:
            if now - self._cache_timestamps[monitor_id] < self._cache_ttl:
                return self._status_cache[monitor_id]
        
        # Cache expired or missing - read from DB
        monitor = self.db.get_monitor(monitor_id)
        if monitor:
            self._status_cache[monitor_id] = monitor['status']
            self._cache_timestamps[monitor_id] = now
            return monitor['status']
        
        return 'unknown'
    
    def update_status(self, monitor_id: int, new_status: str) -> bool:
        """Update status in database and update cache."""
        # Write to database (source of truth)
        success = self.db.update_monitor_status(monitor_id, new_status)
        
        if success:
            # Update cache immediately
            self._status_cache[monitor_id] = new_status
            self._cache_timestamps[monitor_id] = time.time()
        
        return success
    
    def get_status_for_all_monitors(self) -> dict[int, str]:
        """Batch read all statuses (most efficient)."""
        # Force cache refresh
        monitors = self.db.get_monitors()
        self._status_cache = {m['id']: m['status'] for m in monitors}
        now = time.time()
        self._cache_timestamps = {m['id']: now for m in monitors}
        
        return self._status_cache.copy()
    