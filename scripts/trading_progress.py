#!/usr/bin/env python3
"""
Progreso total del monorepo trading (Polymarket + ingest + validación Binance).

Cada workstream se sondea en paralelo; pct_total es media ponderada de streams activos.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "llm-forecast-lab"
POLY = ROOT / "polymarket"
LAB_DB = LAB / "data" / "lab.sqlite"
PAPER_BASE = POLY / "data_local" / "local_lab" / "maker_16"

SESSION_ID_RE = re.compile(r"session_(\d{8})_(\d{6})")

WORKSTREAM_WEIGHTS: dict[str, float] = {
    "polymarket_ingest": 0.35,
    "polymarket_eval": 0.25,
    "polymarket_nim_paper": 0.25,
    "trading_validation": 0.15,
}


@dataclass(frozen=True)
class StreamProgress:
    id: str
    label: str
    pct: float
    active: bool
    detail: str
    raw: dict[str, Any]


def _bar(pct: float, width: int = 24) -> str:
    filled = int(round(width * max(0.0, min(100.0, pct)) / 100.0))
    return "█" * filled + "░" * (width - filled)


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("select v from meta where k = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def probe_polymarket_ingest() -> StreamProgress:
    """Gamma keyset ingest (llm-forecast-lab SQLite meta)."""
    if not LAB_DB.is_file():
        return StreamProgress(
            id="polymarket_ingest",
            label="Polymarket ingest (keyset)",
            pct=0.0,
            active=False,
            detail="lab.sqlite no encontrado",
            raw={},
        )
    try:
        proc = subprocess.run(
            ["node", "dist/cli.js", "ingest-progress"],
            cwd=str(LAB),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
        data = json.loads(proc.stdout)
        pct = float(data.get("keysetPct", 0))
        chunks = f"{data.get('chunks', '?')}"
        chunk = data.get("activeChunk") or "—"
        pages = data.get("activeChunkPages")
        est = data.get("activeChunkPagesEst")
        intra = f" {pages}/{est}p" if pages is not None and est else ""
        detail = f"keyset {pct}% [{chunks} meses, chunk {chunk}{intra}] unique={data.get('unique', '?')}"
        return StreamProgress(
            id="polymarket_ingest",
            label="Polymarket ingest (keyset)",
            pct=pct,
            active=not bool(data.get("complete")),
            detail=detail,
            raw=data,
        )
    except Exception as exc:  # noqa: BLE001
        return StreamProgress(
            id="polymarket_ingest",
            label="Polymarket ingest (keyset)",
            pct=0.0,
            active=False,
            detail=f"error: {exc}",
            raw={},
        )


def probe_polymarket_eval() -> StreamProgress:
    """Checklist eval: ingest → gate → forecast → report (7 pasos)."""
    steps = [
        ("gamma_keyset_complete", "keyset 100%"),
        ("dedup_ok", "dedupSanity"),
        ("composition_ok", "composition"),
        ("run_questions_ok", "run_questions=500"),
        ("clob_ok", "CLOB muestra"),
        ("forecast_ok", "forecast+score"),
        ("report_ok", "report+heldout≥100"),
    ]
    done = 0
    notes: list[str] = []

    if not LAB_DB.is_file():
        return StreamProgress(
            id="polymarket_eval",
            label="Polymarket eval pipeline",
            pct=0.0,
            active=False,
            detail="sin lab.sqlite",
            raw={"steps_done": 0, "steps_total": len(steps)},
        )

    conn = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True)
    try:
        complete = _meta_get(conn, "gamma_keyset_complete") == "true"
        if complete:
            done += 1
            notes.append("keyset✓")
        else:
            notes.append("keyset…")

        raw_n = conn.execute("select count(*) from gamma_markets_raw").fetchone()[0]
        d_slug = conn.execute("select count(distinct slug) from gamma_markets_raw").fetchone()[0]
        dedup_ok = raw_n > 0 and raw_n == d_slug
        if dedup_ok:
            done += 1
            notes.append("dedup✓")

        comp = _meta_get(conn, "composition_annotations")
        if comp:
            done += 1
            notes.append("composition✓")

        rq = conn.execute("select count(*) from run_questions").fetchone()[0]
        if rq >= 500:
            done += 1
            notes.append(f"sample={rq}")

        clob_dir = LAB / "data" / "clob"
        clob_n = len(list(clob_dir.glob("*.json"))) if clob_dir.is_dir() else 0
        if clob_n >= 50:
            done += 1
            notes.append(f"clob={clob_n}")

        fc = conn.execute(
            "select count(*) from forecasts where pipeline = 'naive'"
        ).fetchone()[0]
        sc = conn.execute("select count(*) from scores").fetchone()[0]
        if fc > 0 and sc > 0:
            done += 1
            notes.append(f"forecast={fc}")

        reports = sorted((LAB / "output").glob("*/report.json"), reverse=True) if (LAB / "output").is_dir() else []
        heldout_ok = False
        if reports:
            try:
                rep = json.loads(reports[0].read_text(encoding="utf-8"))
                heldout_ok = int(rep.get("metrics", {}).get("heldoutQuestionsN", 0)) >= 100
            except Exception:
                heldout_ok = False
        if heldout_ok:
            done += 1
            notes.append("heldout✓")
    finally:
        conn.close()

    total = len(steps)
    pct = round(100.0 * done / total, 1)
    return StreamProgress(
        id="polymarket_eval",
        label="Polymarket eval pipeline",
        pct=pct,
        active=done < total,
        detail=f"{done}/{total} — " + ", ".join(notes),
        raw={"steps_done": done, "steps_total": total},
    )


def _session_start_utc(session_dir: Path) -> datetime | None:
    m = SESSION_ID_RE.search(session_dir.name)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    return datetime(
        int(d[0:4]), int(d[4:6]), int(d[6:8]),
        int(t[0:2]), int(t[2:4]), int(t[4:6]),
        tzinfo=timezone.utc,
    )


def probe_polymarket_nim_paper(*, default_minutes: float = 30.0) -> StreamProgress:
    """Paper maker NIM — sesión activa por tiempo o report.json."""
    if not PAPER_BASE.is_dir():
        return StreamProgress(
            id="polymarket_nim_paper",
            label="Polymarket NIM paper",
            pct=0.0,
            active=False,
            detail="sin sesiones paper",
            raw={},
        )

    sessions = sorted(PAPER_BASE.glob("session_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sessions:
        return StreamProgress(
            id="polymarket_nim_paper",
            label="Polymarket NIM paper",
            pct=0.0,
            active=False,
            detail="sin sesiones",
            raw={},
        )

    latest = sessions[0]
    report_path = latest / "report.json"
    if report_path.is_file():
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        return StreamProgress(
            id="polymarket_nim_paper",
            label="Polymarket NIM paper",
            pct=100.0,
            active=False,
            detail=f"completada {latest.name} fills={rep.get('fills', 0)}",
            raw=rep,
        )

    started = _session_start_utc(latest)
    decisions = latest / "decisions.jsonl"
    n_decisions = 0
    if decisions.is_file():
        n_decisions = sum(1 for _ in decisions.open(encoding="utf-8"))

    if started is None:
        pct = min(99.0, n_decisions * 0.5)  # fallback
        detail = f"{latest.name} decisions={n_decisions}"
    else:
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
        pct = min(99.9, round(100.0 * elapsed_min / default_minutes, 1))
        detail = f"{latest.name} {elapsed_min:.1f}/{default_minutes:.0f} min decisions={n_decisions}"

    active = pct < 100 and (decisions.is_file() and time.time() - decisions.stat().st_mtime < 120)
    return StreamProgress(
        id="polymarket_nim_paper",
        label="Polymarket NIM paper",
        pct=pct,
        active=active,
        detail=detail,
        raw={"session": latest.name, "decisions": n_decisions},
    )


def probe_trading_validation(*, strategy: str = "MeanRevBB", run_id: str = "") -> StreamProgress:
    """Validación Binance (Freqtrade) si hay run activo."""
    reports = ROOT / "user_data" / "validation_reports" / strategy
    if not reports.is_dir():
        return StreamProgress(
            id="trading_validation",
            label="Trading validación",
            pct=0.0,
            active=False,
            detail="sin validation_reports",
            raw={},
        )

    if run_id:
        rid = run_id
    else:
        runs = sorted(reports.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        rid = runs[0].name if runs else ""

    if not rid or not (reports / rid).is_dir():
        return StreamProgress(
            id="trading_validation",
            label="Trading validación",
            pct=0.0,
            active=False,
            detail="sin runs",
            raw={},
        )

    report_json = reports / rid / "report.json"
    if report_json.is_file():
        return StreamProgress(
            id="trading_validation",
            label="Trading validación",
            pct=100.0,
            active=False,
            detail=f"completado run={rid}",
            raw={"run_id": rid},
        )

    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from validation_progress import compute_progress  # type: ignore

        data = compute_progress(strategy=strategy, run_id=rid)
        pct = float(data.get("pct_total", 0))
        return StreamProgress(
            id="trading_validation",
            label="Trading validación",
            pct=pct,
            active=pct < 100,
            detail=str(data.get("phase", rid)),
            raw=data,
        )
    except Exception as exc:  # noqa: BLE001
        return StreamProgress(
            id="trading_validation",
            label="Trading validación",
            pct=0.0,
            active=False,
            detail=f"idle ({exc})",
            raw={"run_id": rid},
        )


ProbeFn = Callable[[], StreamProgress]

PROBES: dict[str, ProbeFn] = {
    "polymarket_ingest": probe_polymarket_ingest,
    "polymarket_eval": probe_polymarket_eval,
    "polymarket_nim_paper": probe_polymarket_nim_paper,
    "trading_validation": probe_trading_validation,
}


def collect_progress_parallel(
    *,
    streams: list[str] | None = None,
    max_workers: int = 4,
    validation_strategy: str = "MeanRevBB",
    validation_run_id: str = "",
    paper_minutes: float = 30.0,
) -> dict[str, Any]:
    ids = streams or list(PROBES.keys())
    results: dict[str, StreamProgress] = {}

    def _run(sid: str) -> StreamProgress:
        if sid == "trading_validation":
            return probe_trading_validation(strategy=validation_strategy, run_id=validation_run_id)
        if sid == "polymarket_nim_paper":
            return probe_polymarket_nim_paper(default_minutes=paper_minutes)
        fn = PROBES.get(sid)
        if fn is None:
            raise KeyError(sid)
        return fn()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_run, sid): sid for sid in ids}
        for fut in as_completed(futs):
            sid = futs[fut]
            results[sid] = fut.result()

    weighted = 0.0
    weight_sum = 0.0
    stream_rows: list[dict[str, Any]] = []
    for sid in ids:
        sp = results[sid]
        w = WORKSTREAM_WEIGHTS.get(sid, 1.0)
        include = sp.active or sp.pct > 0 or sid in ("polymarket_ingest", "polymarket_eval")
        if include:
            weighted += w * sp.pct
            weight_sum += w
        stream_rows.append(
            {
                "id": sp.id,
                "label": sp.label,
                "pct": sp.pct,
                "weight": w,
                "active": sp.active,
                "detail": sp.detail,
                "included_in_total": include,
            }
        )

    pct_total = round(weighted / weight_sum, 1) if weight_sum else 0.0
    return {
        "pct_total": pct_total,
        "streams": stream_rows,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def format_output(data: dict[str, Any], *, style: str = "compact") -> str:
    total = float(data["pct_total"])
    if style == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)

    lines = [f"PROGRESO TOTAL {total:5.1f}%  {_bar(total)}"]
    for s in data["streams"]:
        if not s.get("included_in_total"):
            continue
        lines.append(
            f"  {s['label']:28} {s['pct']:5.1f}%  {_bar(s['pct'], 16)}  {s['detail']}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Progreso total trading (paralelo)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--format", choices=("compact", "json"), default="compact")
    parser.add_argument("--watch", type=float, default=0, help="Refrescar cada N segundos")
    parser.add_argument("--streams", default="", help="Comma-separated stream ids")
    parser.add_argument("--validation-strategy", default="MeanRevBB")
    parser.add_argument("--validation-run-id", default="")
    parser.add_argument("--paper-minutes", type=float, default=30.0)
    args = parser.parse_args()

    streams = [s.strip() for s in args.streams.split(",") if s.strip()] or None

    def _once() -> dict[str, Any]:
        return collect_progress_parallel(
            streams=streams,
            validation_strategy=args.validation_strategy,
            validation_run_id=args.validation_run_id,
            paper_minutes=args.paper_minutes,
        )

    if args.watch > 0:
        while True:
            data = _once()
            out = format_output(data, style="json" if args.json else "compact")
            print(out)
            print()
            time.sleep(args.watch)
    else:
        data = _once()
        if args.json or args.format == "json":
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(format_output(data))


if __name__ == "__main__":
    main()
