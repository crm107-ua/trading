"""Tests paralelos del agregador de progreso trading."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from trading_progress import (  # noqa: E402
    WORKSTREAM_WEIGHTS,
    collect_progress_parallel,
    probe_polymarket_eval,
    probe_polymarket_nim_paper,
    _session_start_utc,
)


class TestTradingProgress(unittest.TestCase):
    def test_session_start_parse(self) -> None:
        p = Path("session_20260715_092257")
        dt = _session_start_utc(p)
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 9)

    def test_eval_progress_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lab.sqlite"
            conn = sqlite3.connect(db_path)
            conn.execute("create table meta (k text primary key, v text)")
            conn.execute("create table gamma_markets_raw (slug text)")
            conn.execute("create table run_questions (question_id text)")
            conn.execute("create table forecasts (id text, pipeline text)")
            conn.execute("create table scores (forecast_id text)")
            conn.execute("insert into meta values ('gamma_keyset_complete','true')")
            conn.execute("insert into gamma_markets_raw values ('a')")
            conn.commit()
            conn.close()

            with mock.patch("trading_progress.LAB_DB", db_path), mock.patch(
                "trading_progress.LAB", Path(tmp)
            ):
                sp = probe_polymarket_eval()
        self.assertGreater(sp.pct, 0)
        self.assertIn("keyset✓", sp.detail)

    def test_paper_completed_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "maker_16" / "session_20260715_120000"
            base.mkdir(parents=True)
            (base / "report.json").write_text(
                json.dumps({"fills": 3, "verdict": "LOCAL_PAPER_ONLY"}), encoding="utf-8"
            )
            with mock.patch("trading_progress.PAPER_BASE", Path(tmp) / "maker_16"):
                sp = probe_polymarket_nim_paper(default_minutes=30)
        self.assertEqual(sp.pct, 100.0)
        self.assertFalse(sp.active)

    def test_collect_parallel_returns_total(self) -> None:
        fake_streams = {
            "polymarket_ingest": mock.Mock(
                return_value=mock.Mock(
                    id="polymarket_ingest",
                    label="ingest",
                    pct=80.0,
                    active=True,
                    detail="ok",
                    raw={},
                )
            ),
            "polymarket_eval": mock.Mock(
                return_value=mock.Mock(
                    id="polymarket_eval",
                    label="eval",
                    pct=20.0,
                    active=True,
                    detail="ok",
                    raw={},
                )
            ),
            "polymarket_nim_paper": mock.Mock(
                return_value=mock.Mock(
                    id="polymarket_nim_paper",
                    label="paper",
                    pct=50.0,
                    active=True,
                    detail="ok",
                    raw={},
                )
            ),
            "trading_validation": mock.Mock(
                return_value=mock.Mock(
                    id="trading_validation",
                    label="val",
                    pct=0.0,
                    active=False,
                    detail="idle",
                    raw={},
                )
            ),
        }
        with mock.patch.dict("trading_progress.PROBES", fake_streams, clear=True):
            data = collect_progress_parallel(max_workers=4)
        self.assertIn("pct_total", data)
        self.assertGreater(data["pct_total"], 0)
        self.assertEqual(len(data["streams"]), 4)

    def test_parallel_probe_cases(self) -> None:
        """Varios escenarios de % en paralelo (smoke de agregación)."""
        cases = [
            (10.0, 10.0, 10.0, 0.0),
            (50.0, 50.0, 50.0, 50.0),
            (100.0, 0.0, 0.0, 0.0),
            (83.0, 14.0, 45.0, 0.0),
        ]

        def _agg(pcts: tuple[float, float, float, float]) -> float:
            ids = list(WORKSTREAM_WEIGHTS.keys())
            weighted = sum(WORKSTREAM_WEIGHTS[i] * p for i, p in zip(ids, pcts))
            return round(weighted / sum(WORKSTREAM_WEIGHTS.values()), 1)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(_agg, c) for c in cases]
            totals = [f.result() for f in as_completed(futs)]
        self.assertEqual(len(totals), 4)
        self.assertTrue(all(0 <= t <= 100 for t in totals))


if __name__ == "__main__":
    unittest.main()
