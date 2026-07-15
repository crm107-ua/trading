from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_repo_dotenv(*, override: bool = False) -> bool:
    """
    Load KEY=VALUE from trading/.env (repo root). Never logs values.
    Returns True if a file was found and parsed.
    """
    env_path = repo_root() / ".env"
    if not env_path.is_file():
        return False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        if "=" not in t:
            continue
        k, v = t.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = val
    return True


def require_nvidia_api_key() -> str:
    load_repo_dotenv()
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "NVIDIA_API_KEY missing. Set it in trading/.env (Public API endpoints scope)."
        )
    return key
