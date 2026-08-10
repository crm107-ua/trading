#!/usr/bin/env python3
"""Watch ladder manager progress and write human alerts on advances.

Tracks 3 bankrolls on EDGE: live wallet + $100 + $200 (sim what-if, no posts).
"""
from __future__ import annotations
import json, time, os, sys
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
    return {"last_round": 0, "posted": False, "had_edge": False, "last_edge_slugs": []}

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

def _edge_alert(d: dict) -> None:
    """Build multi-bankroll what-if and Telegram on DNA edge."""
    live_bal = float(d.get("balance_pusd") or 3.4482)
    r = d.get("round")
    acc = d.get("accepted_n")
    slugs = d.get("accepted_slugs") or []
    try:
        sys.path.insert(0, str(ROOT))
        from polymarket.research.local_lab.watch_multi_bankroll import (
            multi_bankroll_what_if,
            telegram_fields,
            format_plain,
        )
        report = multi_bankroll_what_if(live_balance=live_bal, extra=[100.0, 200.0])
        fields = telegram_fields(report, round_id=r, accepted_n=acc)
        if slugs:
            fields["slugs"] = ",".join(str(s) for s in slugs[:3])
        plain = format_plain(report)
        (RUN / "MULTI_BANKROLL_EDGE.md").write_text(
            f"# EDGE multi-bankroll\n\n`{ts()}`\n\n```\n{plain}\n```\n",
            encoding="utf-8",
        )
        alert(
            plain.replace("\n", " | "),
            title="EDGE DNA · 3 bankrolls (WATCH ONLY)",
            fields=fields,
        )
    except Exception as exc:
        alert(
            f"EDGE round={r} (multi-bankroll failed: {type(exc).__name__}: {exc})",
            title="AVANCE · EDGE DNA (WATCH ONLY)",
            fields={
                "round": r,
                "accepted_n": acc,
                "balance_live": live_bal,
                "acción": "NO se postea",
                "bankrolls": "live/$100/$200 (detalle falló)",
            },
        )

def main():
    os.chdir(ROOT)
    os.environ.setdefault("PYTHONPATH", str(ROOT))
    alert(
        "WATCHER Telegram activo (WATCH_ONLY x3)",
        title="SISTEMA · Watcher ON x3",
        fields={
            "canal": "@waxochitobot",
            "modo": "WATCH_ONLY",
            "bankrolls": "live + $100 + $200",
            "aviso": "EDGE en cualquiera → Telegram con what-if x3 (sin post)",
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
                if acc >= 1:
                    # New edge or still open: alert once per edge open cycle
                    if not st.get("had_edge"):
                        st["had_edge"] = True
                        _edge_alert(d)
                    elif r % 15 == 0:
                        alert(
                            f"EDGE sigue abierto round={r} accepted_n={acc} (x3 bankrolls)",
                            title="AVANCE · EDGE sigue (WATCH ONLY x3)",
                            fields={"round": r, "accepted_n": acc, "bankrolls": "live/$100/$200"},
                        )
                else:
                    # edge closed — allow fresh alert next time
                    if st.get("had_edge"):
                        st["had_edge"] = False
                        alert(
                            f"EDGE cerrado round={r} — vuelve WAIT",
                            title="ESTADO · WAIT",
                            fields={"round": r, "accepted_n": 0},
                        )
                save_state(st)
        # posted? (should not happen in watch-only; still detect)
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
