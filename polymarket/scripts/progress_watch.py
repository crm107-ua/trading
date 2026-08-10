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
                "bankrolls": "live/USD100/USD200 (detalle falló)",
            },
        )

def _maybe_refresh_scan(st: dict) -> None:
    """Lightweight pointer refresh; heavy scan lives in ladder-research-improve."""
    last = float(st.get("last_scan_ts") or 0)
    now = time.time()
    if now - last < 900:
        return
    st["last_scan_ts"] = now
    try:
        import subprocess

        subprocess.run(
            [sys.executable, str(ROOT / "polymarket/scripts/research_improvement_scanner.py")],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            timeout=120,
            check=False,
            capture_output=True,
        )
    except Exception as exc:
        print(f"scan_fail {type(exc).__name__}: {exc}", flush=True)


def _close_call_alert(d: dict, st: dict) -> None:
    """Telegram when books get within ~5¢ of DNA (research signal, no post)."""
    gap = d.get("min_gap_basket")
    if gap is None:
        return
    try:
        gap_f = float(gap)
    except Exception:
        return
    prev = st.get("best_gap")
    improved = prev is None or gap_f < float(prev) - 0.004
    if gap_f <= 0.05 + 1e-12:
        st["best_gap"] = gap_f if prev is None else min(float(prev), gap_f)
        if improved or not st.get("close_call_sent"):
            st["close_call_sent"] = True
            alert(
                f"CASI EDGE gap={gap_f:.3f} round={d.get('round')} near={d.get('near_miss_n')} (WATCH ONLY, no post)",
                title="AVANCE · CASI EDGE DNA",
                fields={
                    "gap_basket": round(gap_f, 4),
                    "round": d.get("round"),
                    "near_miss_n": d.get("near_miss_n"),
                    "gates": d.get("best_gates_passed"),
                    "interval_s": d.get("interval_next_s"),
                    "acción": "Vigilando; DNA intacta; NO se postea",
                },
            )
    elif gap_f > 0.08:
        # allow re-alert if we drift away then come back
        st["close_call_sent"] = False


def _gates_scoreboard_alert(d: dict, st: dict) -> None:
    """Telegram when any live book hits 2/3 DNA gates (still missing one — no post)."""
    gates = d.get("best_gates_passed")
    try:
        g = int(gates) if gates is not None else 0
    except Exception:
        g = 0
    # Also read GATE_SCOREBOARD.json for detail
    detail = ""
    waiting = ""
    city = ""
    try:
        sb_path = RUN / "GATE_SCOREBOARD.json"
        if not sb_path.exists():
            sb_path = RUN / "telemetry" / "GATE_SCOREBOARD.json"
        if sb_path.exists():
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
            rows = sb.get("gates_2_of_3") or sb.get("all") or []
            top = None
            for r in rows:
                gl = r.get("gates_live") or r
                if int(gl.get("gates_passed") or 0) >= 2:
                    top = r
                    break
            if top:
                gl = top.get("gates_live") or top
                city = f"{top.get('city')} {top.get('day')}"
                waiting = ",".join(gl.get("waiting") or [])
                detail = (
                    f"{gl.get('gates_passed')}/3 basket={gl.get('basket')} "
                    f"leg={gl.get('max_leg')} ud={gl.get('ud_ratio')}"
                )
                g = max(g, int(gl.get("gates_passed") or 0))
    except Exception as exc:
        print(f"gates_sb_fail {type(exc).__name__}: {exc}", flush=True)

    if g < 2:
        st["gates2_sent"] = False
        return
    prev_best = int(st.get("best_gates") or 0)
    improved = g > prev_best
    st["best_gates"] = max(prev_best, g)
    key = f"{city}|{waiting}|{g}"
    if improved or (not st.get("gates2_sent")) or st.get("gates2_key") != key:
        st["gates2_sent"] = True
        st["gates2_key"] = key
        alert(
            f"GATES {g}/3 {city or d.get('best_gates_slug') or ''} waiting={waiting or '?'} {detail} "
            f"round={d.get('round')} (WATCH ONLY, DNA intacta, no post)",
            title=f"AVANCE · DNA gates {g}/3",
            fields={
                "gates": g,
                "city": city or None,
                "waiting": waiting or None,
                "detalle": detail or None,
                "gap_basket": d.get("min_gap_basket"),
                "round": d.get("round"),
                "acción": "Falta 1 gate; vigilando; NO se postea",
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
            "bankrolls": "live + USD100 + USD200",
            "aviso": "EDGE o gates 2/3 → Telegram (sin post)",
        },
    )
    st = load_state()
    while True:
        rows = latest_rounds()
        if rows:
            d = rows[-1]
            r = int(d.get("round") or 0)
            acc = int(d.get("accepted_n") or 0)
            if r > int(st.get("last_round") or 0) or d.get("ts_utc") != st.get("last_ts"):
                st["last_round"] = max(r, int(st.get("last_round") or 0))
                st["last_ts"] = d.get("ts_utc")
                _close_call_alert(d, st)
                _gates_scoreboard_alert(d, st)
                if acc >= 1:
                    # New edge or still open: alert once per edge open cycle
                    if not st.get("had_edge"):
                        st["had_edge"] = True
                        _edge_alert(d)
                    elif r % 15 == 0:
                        alert(
                            f"EDGE sigue abierto round={r} accepted_n={acc} (x3 bankrolls)",
                            title="AVANCE · EDGE sigue (WATCH ONLY x3)",
                            fields={"round": r, "accepted_n": acc, "bankrolls": "live/USD100/USD200"},
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
        _maybe_refresh_scan(st)
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
