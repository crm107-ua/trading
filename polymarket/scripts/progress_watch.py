#!/usr/bin/env python3
"""Watch ladder manager progress and write human alerts on advances."""
from __future__ import annotations
import json, time, os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/var/www/html/trader")
RUN = ROOT / "polymarket/data_local/local_lab/vps_runs"
ALERTS = RUN / "ALERTS.log"
PROGRESS = RUN / "PROGRESS.md"
STATE = RUN / "progress_watch_state.json"

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def alert(msg: str, title: str = "AVISO", fields: dict | None = None):
    RUN.mkdir(parents=True, exist_ok=True)
    line = f"[{ts()}] {msg}"
    with ALERTS.open("a") as f:
        f.write(line + "\n")
    PROGRESS.write_text(
        f"# Progreso Ladder\n\n**{ts()}**\n\n{msg}\n\n"
        f"Archivo vivo: `{ALERTS}`\n",
        encoding="utf-8",
    )
    print(line, flush=True)
    try:
        import sys
        sys.path.insert(0, str(ROOT / "polymarket/scripts"))
        from tg_notify import send
        send(title, fields or {"detalle": msg})
    except Exception as exc:
        print(f"tg_fail {type(exc).__name__}: {exc}", flush=True)

def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"last_round": 0, "posted": False, "had_edge": False}

def save_state(st):
    STATE.write_text(json.dumps(st), encoding="utf-8")

def latest_rounds():
    logs = sorted(RUN.glob("private_manager_*.log"))
    if not logs:
        return []
    text = logs[-1].read_text(errors="ignore")
    rows = []
    buf = []
    depth = 0
    inobj = False
    for ch in text:
        if ch == "{":
            depth += 1
            inobj = True
        if inobj:
            buf.append(ch)
        if ch == "}":
            depth -= 1
            if inobj and depth == 0:
                s = "".join(buf)
                buf = []
                inobj = False
                if '"round"' in s and '"accepted_n"' in s:
                    try:
                        d = json.loads(s)
                        if "round" in d:
                            rows.append(d)
                    except Exception:
                        pass
    return rows

def main():
    os.chdir(ROOT)
    alert(
        "WATCHER Telegram activo (WATCH_ONLY)",
        title="SISTEMA · Watcher ON",
        fields={
            "canal": "@waxochitobot",
            "modo": "WATCH_ONLY",
            "aviso": "EDGE = alerta sin post · rearm gate antes de dinero real",
        },
    )
    st = load_state()
    while True:
        rows = latest_rounds()
        if rows:
            d = rows[-1]
            r = int(d.get("round") or 0)
            acc = int(d.get("accepted_n") or 0)
            if r > int(st.get("last_round") or 0):
                st["last_round"] = r
                if acc >= 1 and not st.get("had_edge"):
                    st["had_edge"] = True
                    alert(
                        f"EDGE round={r}",
                        title="AVANCE · EDGE DNA (WATCH ONLY)",
                        fields={
                            "round": r,
                            "accepted_n": acc,
                            "balance": d.get("balance_pusd"),
                            "acción": "NO se postea — decide manual / espera rearm gate",
                        },
                    )
                elif acc >= 1 and r % 10 == 0:
                    # throttle repeat edge spam
                    alert(
                        f"EDGE sigue abierto round={r} accepted_n={acc}",
                        title="AVANCE · EDGE sigue (WATCH ONLY)",
                        fields={"round": r, "accepted_n": acc},
                    )
                save_state(st)
        # posted?
        for path in sorted((ROOT / "polymarket/data_local/local_lab/ladder_income").glob("loop_*/report.json")) if (ROOT / "polymarket/data_local/local_lab/ladder_income").exists() else []:
            try:
                rep = json.loads(path.read_text())
            except Exception:
                continue
            if rep.get("verdict") == "INCOME_POSTED" and not st.get("posted"):
                st["posted"] = True
                alert("INCOME_POSTED", title="EJECUCIÓN · DINERO REAL", fields={"veredicto": "INCOME_POSTED", "report": str(path)})
                save_state(st)
        for path in sorted((ROOT / "polymarket/data_local/local_lab/weather_ladder_real").glob("session_*/report.json")):
            try:
                rep = json.loads(path.read_text())
            except Exception:
                continue
            res = rep.get("result") or {}
            if res.get("executed") and not st.get("posted"):
                st["posted"] = True
                alert("REAL_POSTED", title="EJECUCIÓN · ORDEN REAL", fields={"slug": res.get("slug"), "notional": res.get("notional_usdc"), "report": str(path)})
                save_state(st)
        time.sleep(60)

if __name__ == "__main__":
    main()
