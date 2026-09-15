"""What the tool layer is running: code commit, data hashes, model hash.

Benchmark runs record this next to their results so a result file says which
platform commit, which HOFINET copy and which detector artifact produced it.
Every value is read at call time; nothing here is cached across processes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from importlib import metadata

import config
import src
from src.data import db


__all__ = ["get_provenance", "platform_commit"]

_LIBRARIES = ("duckdb", "pandas", "numpy", "pyarrow", "xgboost", "scikit-learn", "networkx")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(*args) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(config.BASE_DIR), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def platform_commit() -> dict:
    """Returns the platform repository commit and whether the tree is dirty."""
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no")
    return {
        "platform_commit": commit,
        "platform_dirty": bool(status) if status is not None else None,
    }


def _file_sha256(path) -> str | None:
    try:
        return db.file_sha256(path)
    except OSError:
        return None


def _library_versions() -> dict:
    versions = {}
    for name in _LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def get_provenance() -> dict:
    """Returns the provenance record for the current tool-layer process."""
    from src.features import agent
    from src.features.detector import MODEL_PATH

    record = {
        **platform_commit(),
        "data_sha256": _file_sha256(config.PARQUET_PATH),
        "db_sha256": _file_sha256(config.DUCKDB_PATH),
        "model_file_sha256": _file_sha256(MODEL_PATH),
        "system_prompt_sha256": _sha256_text(agent.SYSTEM_PROMPT),
        "tools_sha256": _sha256_text(
            json.dumps(agent.TOOLS, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        ),
        "streamlit_stubbed": src.STREAMLIT_IS_STUBBED,
        "database": db.connection_info(),
        "library_versions": _library_versions(),
    }
    return record


if __name__ == "__main__":
    print(json.dumps(get_provenance(), indent=2, ensure_ascii=False))
