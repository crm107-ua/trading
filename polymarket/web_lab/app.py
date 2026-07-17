#!/usr/bin/env python3
"""Poly Desk — http://127.0.0.1:4000 (paper + live gated)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from polymarket.src.ai.env_loader import load_repo_dotenv, repo_root
from polymarket.src.execution.clob_live import live_health, read_gates
from polymarket.web_lab.catalog import list_strategies
from polymarket.web_lab.run_manager import MANAGER

load_repo_dotenv()

STATIC = Path(__file__).resolve().parent / "static"
ENV_PATH = repo_root() / ".env"
app = FastAPI(title="Poly Desk", version="2.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# safe | dry | real
LIVE_LEVELS = {
    "safe": {"armed": False, "dry_run": True},
    "dry": {"armed": True, "dry_run": True},
    "real": {"armed": True, "dry_run": False},
}


class StartBody(BaseModel):
    strategy_id: str
    capital: float = Field(ge=0.05, le=500)
    sessions: int = Field(default=4, ge=1, le=12)
    minutes: float = Field(default=5.0, ge=1.0, le=20.0)
    # paper | live_dry | live_real
    run_mode: str = Field(default="paper")
    accept_real: bool = False


class LiveLevelBody(BaseModel):
    level: str = Field(description="safe | dry | real")
    max_capital: float = Field(default=5.0, ge=0.5, le=20.0)


def _upsert_env(key: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    pat = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    line = f"{key}={value}"
    if pat.search(text):
        text = pat.sub(line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    os.environ[key] = value


def _current_level() -> str:
    g = read_gates()
    if not g.armed:
        return "safe"
    if g.dry_run:
        return "dry"
    return "real"


def _apply_level(level: str, max_capital: float) -> dict:
    if level not in LIVE_LEVELS:
        raise HTTPException(400, "level debe ser safe | dry | real")
    cfg = LIVE_LEVELS[level]
    _upsert_env("POLY_LIVE_ARMED", "1" if cfg["armed"] else "0")
    _upsert_env("POLY_LIVE_DRY_RUN", "1" if cfg["dry_run"] else "0")
    _upsert_env("POLY_LIVE_MAX_CAPITAL_USDC", str(round(float(max_capital), 2)))
    g = read_gates()
    if g.funder:
        _upsert_env("POLY_FUNDER_ADDRESS", g.funder)
    _upsert_env("POLY_SIGNATURE_TYPE", str(g.signature_type or 3))
    return {"ok": True, "level": level, "live": live_health()}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict:
    live = live_health()
    g = read_gates()
    level = _current_level()
    return {
        "ok": True,
        "level": level,
        "live": live,
        "live_armed": g.armed,
        "live_dry_run": g.dry_run,
        "relayer": bool((os.getenv("RELAYER_API_KEY") or "").strip()),
        "max_capital_usdc": g.max_capital_usdc,
        "signature_type": g.signature_type,
        "funder": g.funder,
        "eoa": g.eoa,
        "levels": {
            "safe": "Bloqueado: no se puede lanzar live.",
            "dry": "Ensayo: misma lógica live, sin enviar órdenes (WOULD_POST).",
            "real": "Dinero real: GTC post-only con tu pUSD.",
        },
        "note": "Elige el modo en el selector. Paper no usa el nivel live.",
    }


@app.post("/api/live/level")
async def set_live_level(body: LiveLevelBody) -> dict:
    return _apply_level(body.level.strip().lower(), body.max_capital)


@app.get("/api/strategies")
async def strategies() -> dict:
    return {"strategies": list_strategies()}


@app.get("/api/runs")
async def runs() -> dict:
    return {"runs": MANAGER.list_runs()}


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict:
    run = MANAGER.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run.snapshot()


@app.post("/api/runs")
async def start_run(body: StartBody) -> dict:
    run_mode = (body.run_mode or "paper").strip().lower()
    if run_mode not in ("paper", "live_dry", "live_real"):
        raise HTTPException(400, "run_mode debe ser paper | live_dry | live_real")

    if run_mode == "paper":
        mode = "paper"
    elif run_mode == "live_dry":
        _apply_level("dry", min(body.capital, float(os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or 5)))
        mode = "live"
    else:
        if not body.accept_real:
            raise HTTPException(
                400,
                "Para live real marca la casilla de aceptar riesgo (dinero real).",
            )
        max_cap = float(os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or 5)
        _apply_level("real", max_cap)
        mode = "live"
        if body.capital > max_cap:
            raise HTTPException(400, f"Capital supera tope live {max_cap}")

    try:
        run = await MANAGER.start(
            strategy_id=body.strategy_id,
            capital=body.capital,
            sessions=body.sessions,
            minutes=body.minutes,
            mode=mode,
        )
    except KeyError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return run.snapshot()


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict:
    run = MANAGER.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    await MANAGER.stop(run_id)
    return run.snapshot()


@app.post("/api/runs/stop-active")
async def stop_active() -> dict:
    """Para el run running (si la UI perdió el id)."""
    stopped: list[str] = []
    for r in list(MANAGER.runs.values()):
        if r.status == "running":
            await MANAGER.stop(r.run_id)
            stopped.append(r.run_id)
    return {"ok": True, "stopped": stopped}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    run = MANAGER.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")

    async def gen():
        q = await MANAGER.subscribe(run_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    break
                snap = event.get("data") or {}
                if snap.get("status") in ("done", "error", "stopped"):
                    break
        finally:
            MANAGER.unsubscribe(run_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import uvicorn

    port = int(os.getenv("POLY_WEB_PORT", "4000"))
    uvicorn.run(
        "polymarket.web_lab.app:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
