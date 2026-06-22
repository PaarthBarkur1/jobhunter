"""Shared HTTP client with connection pooling and retries.

Provide a simple `get` wrapper around a single `requests.Session` configured
with a retry policy to improve performance and reliability across modules.
This keeps the implementation generic and non-hardcoded.
"""
from typing import Any, Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure a global session with sensible defaults and retries
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

DEFAULT_TIMEOUT = 10

def get(url: str, **kwargs: Any) -> requests.Response:
    """Perform a GET request using the shared session.

    Keyword args are passed through to `requests.Session.get`. A default
    timeout is applied if none is provided.
    """
    if 'timeout' not in kwargs:
        kwargs['timeout'] = DEFAULT_TIMEOUT
    return session.get(url, **kwargs)

def post(url: str, data=None, json=None, **kwargs: Any) -> requests.Response:
    if 'timeout' not in kwargs:
        kwargs['timeout'] = DEFAULT_TIMEOUT
    return session.post(url, data=data, json=json, **kwargs)
