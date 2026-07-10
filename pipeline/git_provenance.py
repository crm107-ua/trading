"""Provenance de git por paso del pipeline de validación."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def current_git_hash() -> str:
  try:
    out = subprocess.check_output(
      ["git", "rev-parse", "HEAD"],
      cwd=ROOT,
      text=True,
      stderr=subprocess.DEVNULL,
    )
    return out.strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return "unknown"


def record_step_git(report: dict, step_name: str) -> str:
  """Registra hash de git y timestamp para un paso del pipeline."""
  prov = report.setdefault(
    "pipeline_provenance",
    {"repo_git_hash_at_start": report.get("git_hash", current_git_hash())},
  )
  steps = prov.setdefault("steps", {})
  git_hash = current_git_hash()
  steps[step_name] = {
    "git_hash": git_hash,
    "recorded_at": datetime.now(timezone.utc).isoformat(),
  }
  return git_hash
