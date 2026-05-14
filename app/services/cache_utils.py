import os
import json
import time
import hashlib
from typing import Any, Optional

class FileCache:
    """Simple file-based cache for JSON-serializable data."""
    
    def __init__(self, cache_dir: str, ttl_seconds: int):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_path(self, key: str) -> str:
        # Use MD5 hash of the key to avoid filesystem issues with special characters
        hashed_key = hashlib.md5(key.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_dir, f"{hashed_key}.json")

    def get(self, key: str) -> Optional[Any]:
        path = self._get_cache_path(key)
        if not os.path.exists(path):
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                
            timestamp = cached_data.get('timestamp', 0)
            if time.time() - timestamp > self.ttl_seconds:
                # Expired
                os.remove(path)
                return None
            
            return cached_data.get('payload')
        except (json.JSONDecodeError, IOError, OSError):
            return None

    def set(self, key: str, payload: Any) -> None:
        path = self._get_cache_path(key)
        try:
            cached_data = {
                'timestamp': time.time(),
                'payload': payload,
                'key': key # Store original key for debugging
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cached_data, f, ensure_ascii=False)
        except (IOError, OSError):
            pass
