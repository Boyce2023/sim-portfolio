import os
import json
import gzip
import tempfile

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_fundamentals_30y_permanent"
RAW_CACHE_DIR = os.path.join(BASE_DIR, "raw_sec_cache")
SUB_CACHE = os.path.join(RAW_CACHE_DIR, "submissions")
FACTS_CACHE = os.path.join(RAW_CACHE_DIR, "companyfacts")
DOCS_CACHE = os.path.join(RAW_CACHE_DIR, "docs")

for d in [SUB_CACHE, FACTS_CACHE, DOCS_CACHE]:
    os.makedirs(d, exist_ok=True)

def atomic_write_gz(target_path, data_bytes):
    """
    Atomically writes data_bytes compressed with gzip to target_path using temp-rename.
    """
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".tmp_", suffix=".gz")
    try:
        with os.fdopen(fd, "wb") as f_out:
            with gzip.GzipFile(fileobj=f_out, mode="wb") as gz_out:
                gz_out.write(data_bytes)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def save_json_gz(target_path, data_obj):
    raw_bytes = json.dumps(data_obj).encode("utf-8")
    atomic_write_gz(target_path, raw_bytes)

def load_json_gz(target_path):
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        return None
    try:
        with gzip.open(target_path, "rt", encoding="utf-8") as f:
            content = f.read()
            if content == "__404__":
                return "__404__"
            return json.loads(content)
    except Exception:
        return None

def save_text_gz(target_path, text_content):
    raw_bytes = text_content.encode("utf-8", errors="ignore")
    atomic_write_gz(target_path, raw_bytes)

def load_text_gz(target_path):
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        return None
    try:
        with gzip.open(target_path, "rt", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None
