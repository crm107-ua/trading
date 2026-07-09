"""Hash del config merged que usa el pipeline (reproducibilidad entre runs)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_FILES = (
  ROOT / "user_data" / "config" / "base.json",
  ROOT / "user_data" / "config" / "backtest.json",
)


def deep_merge(base: dict, override: dict) -> dict:
  out = dict(base)
  for key, value in override.items():
    if key in out and isinstance(out[key], dict) and isinstance(value, dict):
      out[key] = deep_merge(out[key], value)
    else:
      out[key] = value
  return out


def merged_config(paths: list[Path] | None = None) -> dict:
  files = paths or list(DEFAULT_CONFIG_FILES)
  merged: dict = {}
  for path in files:
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = deep_merge(merged, data)
  return merged


def merged_config_hash(paths: list[Path] | None = None) -> str:
  """SHA-256 del JSON merged (claves ordenadas) — mismo orden que Freqtrade CLI."""
  files = paths or list(DEFAULT_CONFIG_FILES)
  payload = merged_config(files)
  canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def config_metadata(paths: list[Path] | None = None) -> dict:
  files = paths or list(DEFAULT_CONFIG_FILES)
  rel = [str(p.relative_to(ROOT)).replace("\\", "/") for p in files]
  return {
    "config_files": rel,
    "config_merged_sha256": merged_config_hash(files),
  }
