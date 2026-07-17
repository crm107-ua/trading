"""Ejecuta batches paper / live y emite eventos en tiempo real."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.execution.clob_live import read_gates
from polymarket.web_lab.catalog import apply_live_clob_floors, load_scaled_config

POLY = Path(__file__).resolve().parents[1]
RUNS = POLY / "data_local" / "local_lab" / "web_runs"
RUNS.mkdir(parents=True, exist_ok=True)

RE_PAPER = re.compile(
    r"paper\s+(?P<pct>[0-9.]+)%\s+\[(?P<elapsed>[0-9.]+)/(?P<total>[0-9.]+)\s+min\].*?"
    r"decisions=(?P<dec>\d+)\s+quotes=(?P<quotes>\d+)\s+fills=(?P<fills>\d+)\s+last=(?P<last>\S+)"
)
RE_NET = re.compile(r"^\s*net=(?P<net>[+\-0-9.]+)\s+fills=(?P<fills>\d+)")
RE_SESSION = re.compile(r"=== session\s+(?P<i>\d+)/(?P<n>\d+)")


@dataclass
class RunState:
    run_id: str
    strategy_id: str
    strategy_name: str
    capital: float
    sessions: int
    minutes: float
    status: str = "queued"
    created_utc: str = ""
    pnl: float = 0.0
    equity: float = 0.0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    traded: int = 0
    session_i: int = 0
    session_n: int = 0
    pct: float = 0.0
    last_line: str = ""
    nets: list[float] = field(default_factory=list)
    equity_points: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    cfg_path: str = ""
    mode: str = "paper"
    dry_run: bool = True
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    proc: asyncio.subprocess.Process | None = None

    def snapshot(self) -> dict[str, Any]:
        wr = (self.wins / self.traded) if self.traded else 0.0
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "capital": self.capital,
            "sessions": self.sessions,
            "minutes": self.minutes,
            "status": self.status,
            "created_utc": self.created_utc,
            "pnl": round(self.pnl, 2),
            "equity": round(self.equity, 2),
            "wins": self.wins,
            "losses": self.losses,
            "flats": self.flats,
            "traded": self.traded,
            "wr": round(wr, 4),
            "session_i": self.session_i,
            "session_n": self.session_n,
            "pct": self.pct,
            "last_line": self.last_line,
            "nets": self.nets,
            "equity_points": self.equity_points[-200:],
            "logs_tail": self.logs[-80:],
            "error": self.error,
            "cfg_path": self.cfg_path,
            "mode": self.mode,
            "dry_run": self.dry_run,
        }


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, RunState] = {}
        self._lock = asyncio.Lock()

    def get(self, run_id: str) -> RunState | None:
        return self.runs.get(run_id)

    def list_runs(self) -> list[dict]:
        return [r.snapshot() for r in sorted(self.runs.values(), key=lambda x: x.created_utc, reverse=True)][:30]

    async def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        run = self.runs[run_id]
        run.subscribers.append(q)
        await q.put({"type": "snapshot", "data": run.snapshot()})
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        run = self.runs.get(run_id)
        if not run:
            return
        if q in run.subscribers:
            run.subscribers.remove(q)

    async def _broadcast(self, run: RunState, event: dict) -> None:
        dead: list[asyncio.Queue] = []
        for q in run.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
        for q in dead:
            if q in run.subscribers:
                run.subscribers.remove(q)

    async def _emit_log(self, run: RunState, line: str) -> None:
        run.logs.append(line)
        if len(run.logs) > 2000:
            run.logs = run.logs[-1500:]
        run.last_line = line[:240]
        await self._broadcast(run, {"type": "log", "line": line, "data": run.snapshot()})

    def _validate_live(self, capital: float) -> tuple[bool, str]:
        g = read_gates()
        if not g.armed:
            return False, "Live bloqueado: POLY_LIVE_ARMED=0. Usa Armar live en el panel."
        if capital > g.max_capital_usdc + 1e-9:
            return False, f"Capital {capital} > tope live {g.max_capital_usdc} USDC"
        if g.missing:
            return False, f"Faltan credenciales: {', '.join(g.missing)}"
        return True, "ok"

    async def start(
        self,
        *,
        strategy_id: str,
        capital: float,
        sessions: int,
        minutes: float,
        mode: str = "paper",
    ) -> RunState:
        mode = (mode or "paper").strip().lower()
        if mode not in ("paper", "live"):
            raise RuntimeError("mode debe ser paper|live")

        async with self._lock:
            for r in self.runs.values():
                if r.status == "running":
                    raise RuntimeError(f"Ya hay un run activo: {r.run_id}")

            if mode == "live":
                ok, msg = self._validate_live(capital)
                if not ok:
                    raise RuntimeError(msg)
                sessions = 1  # una sesión por seguridad
                minutes = min(float(minutes), 12.0)

            cfg, meta = load_scaled_config(strategy_id, capital)
            if mode == "live":
                cfg = apply_live_clob_floors(cfg)
                cfg["live_onchain"] = True
                cfg["mode"] = "live"
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
            run_dir = RUNS / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = run_dir / "config.json"
            cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

            gates = read_gates()
            run = RunState(
                run_id=run_id,
                strategy_id=strategy_id,
                strategy_name=str(meta.get("name") or strategy_id),
                capital=float(capital),
                sessions=int(sessions),
                minutes=float(minutes),
                status="running",
                created_utc=datetime.now(timezone.utc).isoformat(),
                equity=float(capital),
                session_n=int(sessions),
                cfg_path=str(cfg_path),
                mode=mode,
                dry_run=gates.dry_run if mode == "live" else True,
            )
            run.equity_points.append({"t": time.time(), "equity": run.equity, "pnl": 0.0})
            self.runs[run_id] = run

        asyncio.create_task(self._execute(run, cfg_path))
        return run

    async def stop(self, run_id: str) -> None:
        run = self.runs.get(run_id)
        if not run or not run.proc:
            return
        run.status = "stopped"
        try:
            run.proc.terminate()
        except Exception:
            pass
        # Best-effort cancel live orders
        if run.mode == "live":
            try:
                from polymarket.src.execution.clob_live import ClobLiveClient

                cli = ClobLiveClient()
                if cli.gates.armed and not cli.gates.dry_run:
                    cli.connect()
                    cli.cancel_all()
            except Exception:
                pass
        await self._broadcast(run, {"type": "status", "data": run.snapshot()})

    async def _execute(self, run: RunState, cfg_path: Path) -> None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["BATCH_STOP_AFTER_LOSS_STREAK"] = env.get("BATCH_STOP_AFTER_LOSS_STREAK", "2")
        env["BATCH_STOP_AFTER_STARVE_STREAK"] = env.get("BATCH_STOP_AFTER_STARVE_STREAK", "2")
        cwd = str(POLY.parent)
        py = env.get("PYTHON", "python")
        if run.mode == "live":
            cmd = [
                py,
                "-u",
                "-m",
                "polymarket.research.local_lab.live_maker",
                "--config",
                str(cfg_path),
                "--minutes",
                str(run.minutes),
                "--session-id",
                run.run_id,
            ]
        else:
            cmd = [
                py,
                "-u",
                "-m",
                "polymarket.research.local_lab.batch_paper_eval",
                "--strategy",
                "maker_edge",
                "--config",
                str(cfg_path),
                "--sessions",
                str(run.sessions),
                "--minutes",
                str(run.minutes),
                "--target",
                "0.5",
            ]
        await self._emit_log(run, f"$ {' '.join(cmd)}")
        await self._emit_log(
            run,
            f"mode={run.mode} dry_run={run.dry_run} capital={run.capital}",
        )
        try:
            run.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=cwd,
            )
            assert run.proc.stdout is not None
            async for raw in run.proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                self._ingest_line(run, line)
                await self._emit_log(run, line)
            code = await run.proc.wait()
            if run.status != "stopped":
                run.status = "done" if code in (0, 1) else "error"
                if code not in (0, 1):
                    run.error = f"exit {code}"
        except Exception as e:
            run.status = "error"
            run.error = f"{type(e).__name__}: {e}"
            await self._emit_log(run, f"ERROR {run.error}")
        out = RUNS / run.run_id / "final.json"
        out.write_text(json.dumps(run.snapshot(), indent=2), encoding="utf-8")
        await self._broadcast(run, {"type": "done", "data": run.snapshot()})

    def _ingest_line(self, run: RunState, line: str) -> None:
        m = RE_SESSION.search(line)
        if m:
            run.session_i = int(m.group("i"))
            run.session_n = int(m.group("n"))
            return
        m = RE_PAPER.search(line)
        if m:
            run.pct = float(m.group("pct"))
            return
        m = RE_NET.match(line)
        if m:
            net = float(m.group("net"))
            fills = int(m.group("fills"))
            run.nets.append(net)
            run.pnl = round(sum(run.nets), 2)
            run.equity = round(run.capital + run.pnl, 2)
            if fills > 0:
                run.traded += 1
                if net > 0:
                    run.wins += 1
                elif net < 0:
                    run.losses += 1
                else:
                    run.flats += 1
            else:
                run.flats += 1
            run.equity_points.append(
                {"t": time.time(), "equity": run.equity, "pnl": run.pnl, "net": net}
            )
            return
        # Live FILL / bankroll lines → equity
        if line.startswith("FILL ") or line.startswith("DRY_FILL "):
            m_br = re.search(r"bankroll=(?P<br>[+\-0-9.]+)", line)
            m_rz = re.search(r"realized=(?P<rz>[+\-0-9.]+)", line)
            if m_rz:
                run.pnl = round(float(m_rz.group("rz")), 2)
                run.equity = round(run.capital + run.pnl, 2)
            elif m_br:
                run.equity = round(float(m_br.group("br")), 2)
                run.pnl = round(run.equity - run.capital, 2)
            run.equity_points.append(
                {"t": time.time(), "equity": run.equity, "pnl": run.pnl}
            )
            if "FILL BUY" in line or "DRY_FILL BUY" in line:
                run.traded = max(run.traded, 1)


MANAGER = RunManager()
