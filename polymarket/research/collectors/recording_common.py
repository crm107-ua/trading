"""Shared recording utilities for phase A long-running collectors."""

from __future__ import annotations

import gzip
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, TextIO

DEFAULT_DATASET_ID = "phase_a_16"
SMOKE_DATASET_ID = "smoke_test"


def resolve_dataset_id(cfg: dict[str, Any]) -> str:
    """POLY_DATASET env overrides config (smoke_test vs phase_a_16)."""
    return os.environ.get("POLY_DATASET") or cfg.get("dataset_id", DEFAULT_DATASET_ID)


def resolve_data_root(cfg: dict[str, Any]) -> Path:
    base = Path(__file__).resolve().parents[2] / "data_local"
    return base / resolve_dataset_id(cfg)


def is_smoke_dataset(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_phase_a_config()
    return resolve_dataset_id(cfg) == SMOKE_DATASET_ID


def manifest_interval_seconds(cfg: dict[str, Any]) -> int:
    env = os.environ.get("POLY_MANIFEST_INTERVAL_S")
    if env:
        return int(env)
    return 3600 if not is_smoke_dataset(cfg) else 60


def load_phase_a_config() -> dict[str, Any]:
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "phase_a.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def now_ns() -> int:
    return time.time_ns()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hour_key(ts_ns: int | None = None) -> str:
    ts = (ts_ns or now_ns()) / 1_000_000_000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d/%H")


from polymarket.src.data.book_utils import truncate_book as _truncate_side


def truncate_book(levels: list[dict], n: int, side: str = "bid") -> list[dict]:
    return _truncate_side(levels, n, side=side)


@dataclass
class GapTracker:
    gaps: list[dict[str, int]] = field(default_factory=list)
    _open_start: int | None = None

    def mark_disconnect(self, ts_ns: int | None = None) -> None:
        if self._open_start is None:
            self._open_start = ts_ns or now_ns()

    def mark_reconnect(self, ts_ns: int | None = None) -> None:
        if self._open_start is not None:
            end = ts_ns or now_ns()
            self.gaps.append({"start_ns": self._open_start, "end_ns": end})
            self._open_start = None


@dataclass
class HourlyJsonlWriter:
    root: Path
    feed_name: str
    compress: bool = True
    _hour: str | None = None
    _fh: BinaryIO | TextIO | None = None
    rows_written: int = 0
    files: list[str] = field(default_factory=list)

    def _path_for_hour(self, hour: str) -> Path:
        ext = "jsonl.gz" if self.compress else "jsonl"
        return self.root / self.feed_name / f"{hour}.{ext}"

    def write(self, record: dict[str, Any]) -> None:
        h = hour_key(record.get("recv_ts_ns") or record.get("ts_ns"))
        if h != self._hour:
            self._rotate(h)
        line = json.dumps(record, separators=(",", ":")) + "\n"
        if self.compress:
            assert isinstance(self._fh, gzip.GzipFile)
            self._fh.write(line.encode("utf-8"))
        else:
            assert isinstance(self._fh, TextIO)
            self._fh.write(line)
        self.rows_written += 1

    def flush_to_disk(self) -> None:
        """Push gzip buffer to OS (required for live size checks on Windows)."""
        if self._fh is None:
            return
        if self.compress:
            assert isinstance(self._fh, gzip.GzipFile)
            self._fh.flush()
            raw = getattr(self._fh, "fileobj", None)
            if raw is not None and hasattr(raw, "flush"):
                raw.flush()
        else:
            assert isinstance(self._fh, TextIO)
            self._fh.flush()

    def _rotate(self, hour: str) -> None:
        self.close()
        path = self._path_for_hour(hour)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.compress:
            self._fh = gzip.open(path, "ab", compresslevel=1)
        else:
            self._fh = open(path, "a", encoding="utf-8")
        rel = str(path.relative_to(self.root))
        if rel not in self.files:
            self.files.append(rel)
        self._hour = hour

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


@dataclass
class PhaseAManifest:
    root: Path
    feed_name: str
    cfg: dict[str, Any]

    def load(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        if not path.exists():
            return self._bootstrap()
        return json.loads(path.read_text(encoding="utf-8"))

    def _bootstrap(self) -> dict[str, Any]:
        ds = resolve_dataset_id(self.cfg)
        start = datetime.now(timezone.utc)
        min_days = float(self.cfg.get("phase_a_min_wall_clock_days", 30))
        warmup_s = int(self.cfg.get("phase_a_warmup_seconds", 1800))
        end = start + timedelta(days=min_days)
        return {
            "phase": "A",
            "hypothesis": self.cfg.get("hypothesis", 16),
            "dataset_id": ds,
            "official_phase_a": ds == DEFAULT_DATASET_ID and not is_smoke_dataset(self.cfg),
            "smoke_test": ds == SMOKE_DATASET_ID,
            "scope": self.cfg.get("scope"),
            "top_book_levels": self.cfg.get("top_book_levels"),
            "started_utc": start.isoformat(),
            "updated_utc": start.isoformat(),
            # Anchors for infalsificable validation (silent death penalizes).
            "phase_start_utc": start.isoformat(),
            "phase_end_utc": end.isoformat(),
            "warmup_seconds": warmup_s,
            "feeds": {},
            "gap_semantics": {
                "feeds_gaps": "WS disconnect/reconnect only — penalizes uptime",
                "market_inactive_periods": "Gamma inter-window listing gap — does NOT penalize uptime",
            },
        }

    def update_feed(
        self,
        *,
        last_ts_ns: int,
        rows_total: int,
        files: list[str],
        gaps: list[dict[str, int]],
        extra: dict[str, Any] | None = None,
    ) -> None:
        data = self.load()
        feed = data.setdefault("feeds", {}).setdefault(self.feed_name, {})
        feed["last_ts_ns"] = last_ts_ns
        feed["last_utc"] = utc_iso()
        feed["rows_total"] = rows_total
        feed["files"] = files
        feed["gaps"] = gaps
        if extra:
            feed.update(extra)
        stale_min = (now_ns() - last_ts_ns) / 1_000_000_000 / 60
        data.setdefault("health", {})[f"{self.feed_name}_stale_minutes"] = round(stale_min, 2)
        data["updated_utc"] = utc_iso()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "manifest.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
