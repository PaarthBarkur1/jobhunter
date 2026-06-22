"""Simple file‑based cache for the job hunter agent.

The cache lives in a top‑level `.cache` directory. Each entry is stored as a JSON file whose
filename is a safe SHA‑256 hash of the cache key (e.g., a URL or a search query). The value is the raw
string that the tool would have returned.

This implementation adds a small in-memory layer to avoid repeated filesystem reads during a
single execution, and keeps the file-backed store for persistence across processes if needed.
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

CACHE_ROOT = Path('.cache')
CACHE_ROOT.mkdir(exist_ok=True)

# In-memory layer to avoid frequent filesystem I/O during a single run
_mem_cache: dict = {}


def _hash_key(key: str) -> str:
    """Return a deterministic filename for *key* using SHA‑256."""
    return hashlib.sha256(key.encode('utf-8')).hexdigest() + '.json'


def get_cached(key: str) -> Optional[str]:
    """Return cached value for *key* if present, otherwise ``None``."""
    try:
        # Fast in-memory check
        if key in _mem_cache:
            return _mem_cache[key]

        cache_path = CACHE_ROOT / _hash_key(key)
        if not cache_path.is_file():
            return None
        with cache_path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        value = data.get('value')
        # Populate in-memory cache for faster subsequent lookups
        if value is not None:
            _mem_cache[key] = value
        return value
    except Exception:
        return None


def set_cached(key: str, value: str) -> None:
    """Store *value* under *key* (overwrites existing entry)."""
    try:
        # Update in-memory layer first
        _mem_cache[key] = value

        cache_path = CACHE_ROOT / _hash_key(key)
        with cache_path.open('w', encoding='utf-8') as f:
            json.dump({'value': value}, f)
    except Exception:
        # Log silently – cache failures should not break the main flow
        pass
