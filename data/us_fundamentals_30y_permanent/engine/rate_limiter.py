import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .cache_manager import load_json_gz, save_json_gz, load_text_gz, save_text_gz

USER_AGENT = "OHIM Research buwen@ohim.com"
MAX_REQ_PER_SEC = 1.8  # Strictly <= 2.0 req/sec

class RateLimiter:
    def __init__(self, max_per_sec=1.8):
        self.interval = 1.0 / max_per_sec
        self.last_req_time = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_req_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_req_time = time.time()

rate_limiter = RateLimiter(max_per_sec=MAX_REQ_PER_SEC)

session = requests.Session()
adapter = HTTPAdapter(
    max_retries=Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({"User-Agent": USER_AGENT})

def fetch_sec_json(url, cache_path=None):
    if cache_path:
        cached = load_json_gz(cache_path)
        if cached == "__404__":
            return None
        if cached is not None:
            return cached

    rate_limiter.wait()
    try:
        r = session.get(url, timeout=25)
        if r.status_code == 404:
            if cache_path:
                save_json_gz(cache_path, "__404__")
            return None
        r.raise_for_status()
        data = r.json()
        if cache_path:
            save_json_gz(cache_path, data)
        return data
    except requests.exceptions.HTTPError as e:
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
            print("[RateLimit 429] Sleeping 15s...")
            time.sleep(15)
            return fetch_sec_json(url, cache_path)
        return None
    except Exception as e:
        return None

def fetch_sec_text(url, cache_path=None):
    if cache_path:
        cached = load_text_gz(cache_path)
        if cached is not None:
            return cached

    rate_limiter.wait()
    try:
        r = session.get(url, timeout=25)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        text = r.text
        if cache_path:
            save_text_gz(cache_path, text)
        return text
    except requests.exceptions.HTTPError as e:
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
            print("[RateLimit 429] Sleeping 15s...")
            time.sleep(15)
            return fetch_sec_text(url, cache_path)
        return None
    except Exception as e:
        return None
