"""Shared types and manifest helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.data.market_info import MarketInfo

DATA_LOCAL = Path(__file__).resolve().parents[2] / "data_local"

__all__ = ["MarketInfo", "DATA_LOCAL", "write_manifest", "utc_now_iso"]


def write_manifest(dataset_id: str, payload: dict[str, Any]) -> Path:
    out_dir = DATA_LOCAL / dataset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset_id": dataset_id,
        "written_utc": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
