#!/usr/bin/env python3
"""
Monitor en consola (tiempo real) del optimize_oos_t1 / paper maker.

Uso (desde repo root):
  python -u -m polymarket.research.local_lab.monitor_optimize_console
  python -u -m polymarket.research.local_lab.monitor_optimize_console --log optimize_oos_t1_wr70.log --watch 2
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

POLY = Path(__file__).resolve().parents[2]
LAB = POLY / "data_local" / "local_lab"
EDGE = LAB / "maker_edge"

NET_RE = re.compile(r"^\s+net=([+-]?\d+(?:\.\d+)?)", re.M)
WR_RE = re.compile(r"-> WR=([\d.]+)%\s+avg=([+-]?[\d.]+)\s+total=([+-]?[\d.]+)")
TRIAL_RE = re.compile(r"######## OOS-T1 OPT (\d+)/(\d+) (\S+)")
PAPER_RE = re.compile(
    r"paper ([\d.]+)% \[([\d.]+)/([\d.]+) min\] decisions=(\d+) quotes=(\d+) fills=(\d+) last=(\S+)"
)
SIZE_RE = re.compile(r"size=(\d+) mult=([\d.]+) edge=([\d.]+) max_loss=([\d.]+) kill=([\d.]+)")
SESS_HDR_RE = re.compile(r"=== session (\d+)/(\d+)")
META_WR = re.compile(r'"wr_target":\s*([\d.]+)')
META_AVG = re.compile(r'"avg_target":\s*([\d.]+)')
META_SESS = re.compile(r'"sessions":\s*(\d+)')
META_MIN = re.compile(r'"minutes":\s*([\d.]+)')
ENTRIES_RE = re.compile(r"entries=(\d+)")


def _bar(pct: float, width: int = 28) -> str:
    p = max(0.0, min(100.0, pct))
    n = int(round(width * p / 100.0))
    return "#" * n + "-" * (width - n)


def _spark(vals: list[float], height: int = 5) -> list[str]:
    if not vals:
        return ["(sin nets aun)"]
    lo, hi = min(vals), max(vals)
    span = hi - lo if hi != lo else 1.0
    rows = [[" "] * len(vals) for _ in range(height)]
    zero_row = height - 1 - int(round((0 - lo) / span * (height - 1))) if lo <= 0 <= hi else None
    for i, v in enumerate(vals):
        r = height - 1 - int(round((v - lo) / span * (height - 1)))
        r = max(0, min(height - 1, r))
        rows[r][i] = "+" if v > 0 else ("v" if v < 0 else ".")
    if zero_row is not None:
        for i in range(len(vals)):
            if rows[zero_row][i] == " ":
                rows[zero_row][i] = "-"
    return ["".join(row) for row in rows]


def _read_text(path: Path) -> str:
    """Tee-Object de PowerShell escribe UTF-16 LE y a veces bloquea el archivo."""
    if not path.is_file():
        return ""
    raw = b""
    for _ in range(5):
        try:
            with open(path, "rb", buffering=0) as f:
                raw = f.read()
            break
        except OSError:
            time.sleep(0.15)
    if not raw:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if len(raw) >= 4 and raw[1] == 0 and raw[3] == 0:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _proc_alive() -> bool:
    try:
        import subprocess

        # Una sola comilla evita que PowerShell rompa el -match con |
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$n=0; Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "ForEach-Object { $c=$_.CommandLine; if (-not $c) { return }; "
                    "if ($c -like '*monitor_optimize*') { return }; "
                    "if ($c -like '*batch_paper_eval*' -or $c -like '*optimize_oos_t1*') { $n++ } }; "
                    "$n"
                ),
            ],
            text=True,
            timeout=10,
        )
        return int((out or "0").strip().splitlines()[-1]) > 0
    except Exception:
        # Fallback: log tocandose hace <45s
        try:
            logs = list(LAB.glob("hito_exact*.log")) + list(LAB.glob("optimize_oos_t1*.log"))
            if not logs:
                return False
            newest = max(logs, key=lambda p: p.stat().st_mtime)
            return (time.time() - newest.stat().st_mtime) < 45
        except Exception:
            return False


def _pick_log(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = LAB / p
        return p
    preferred = [
        LAB / "hito_exact_oos.log",
        LAB / "optimize_oos_t1_profit.log",
    ]
    for p in preferred:
        if p.is_file() and p.stat().st_size > 0:
            # prefer most recently written among known
            pass
    cands = sorted(
        list(LAB.glob("optimize_oos_t1*.log")) + list(LAB.glob("hito_exact*.log")),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not cands:
        return LAB / "hito_exact_oos.log"
    return cands[0]


def _live_session_fallback(minutes: float = 4.5) -> tuple[str, float] | None:
    """Si el log va atrasado (buffer Tee), estima progreso por carpeta de sesion."""
    if not EDGE.is_dir():
        return None
    dirs = sorted(
        (d for d in EDGE.iterdir() if d.is_dir() and d.name.startswith("session_")),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for d in dirs[:12]:
        report = d / "report.json"
        decisions = d / "decisions.jsonl"
        fills = d / "fills.jsonl"
        if report.is_file():
            continue
        if not decisions.is_file() and not fills.is_file():
            continue
        age_min = max(0.0, (time.time() - decisions.stat().st_mtime) / 60.0) if decisions.is_file() else 0.0
        # mejor: edad desde creacion de la carpeta
        started = d.stat().st_ctime
        elapsed = max(0.0, (time.time() - started) / 60.0)
        frac = min(0.99, elapsed / max(minutes, 1e-9))
        n_dec = 0
        n_fills = 0
        if decisions.is_file():
            n_dec = sum(1 for _ in decisions.open("r", encoding="utf-8", errors="replace"))
        if fills.is_file():
            n_fills = sum(1 for _ in fills.open("r", encoding="utf-8", errors="replace"))
        detail = (
            f"~{100*frac:.0f}% [{elapsed:.1f}/{minutes:.1f} min] "
            f"dec={n_dec} fills={n_fills} dir={d.name} (disco)"
        )
        return detail, frac
    return None


def render(log: Path, *, capital: float = 100.0) -> str:
    text = _read_text(log)
    lines: list[str] = []
    alive = _proc_alive()
    base = float(capital)
    trials = list(TRIAL_RE.finditer(text))
    trial_n, trial_max, label = 1, 1, "hito_exact"
    if trials:
        trial_n = int(trials[-1].group(1))
        trial_max = int(trials[-1].group(2))
        label = trials[-1].group(3)
    last_trial_pos = trials[-1].start() if trials else 0
    chunk = text[last_trial_pos:]
    nets = [float(m.group(1)) for m in NET_RE.finditer(chunk)]
    papers = list(PAPER_RE.finditer(chunk))
    size_m = SIZE_RE.search(chunk) or SIZE_RE.search(text)
    wr_hits = list(WR_RE.finditer(text))
    sess_hdrs = list(SESS_HDR_RE.finditer(chunk))

    sess_total = 8
    if sess_hdrs:
        sess_total = max(sess_total, int(sess_hdrs[-1].group(2)))
    meta_s = META_SESS.search(text)
    if meta_s:
        sess_total = int(meta_s.group(1))
    minutes_each = 5.0
    meta_m = META_MIN.search(text)
    if meta_m:
        minutes_each = float(meta_m.group(1))
    elif papers:
        minutes_each = float(papers[-1].group(3))

    # Detect config from log name / path mentions
    log_name = log.name.lower()
    cfg_tag = "unknown"
    if "v7" in log_name or "lock" in log_name or "margin_v7" in text:
        label = "margin_v7_lock"
        cfg_tag = "v7_lock"
    elif "v6" in log_name or "10m" in log_name or "margin_v6" in text:
        label = "margin_v6_10m"
        cfg_tag = "v6_10m"
    elif "v5" in log_name or "asymmetric" in log_name or "margin_v5" in text:
        label = "margin_v5_asymmetric"
        cfg_tag = "v5_asymmetric"
    elif "v4" in log_name or "cut_tail" in log_name or "margin_v4" in text:
        label = "margin_v4_cut_tail"
        cfg_tag = "v4_cut_tail"
    elif "maker_demo_100_usd_margin_best" in text or "margin_max_v3" in text or "hito_exact" in log_name:
        label = "margin_max_v3_exact"
        cfg_tag = "hito_exact"
    elif "profit" in log_name:
        label = "profit_dna"
        cfg_tag = "profit"

    sess_done = len(nets)
    sess_frac = 0.0
    paper_detail = "-"
    if papers:
        p = papers[-1]
        sess_frac = float(p.group(2)) / max(float(p.group(3)), 1e-9)
        paper_detail = (
            f"{p.group(1)}% [{p.group(2)}/{p.group(3)} min] "
            f"dec={p.group(4)} q={p.group(5)} fills={p.group(6)} last={p.group(7)}"
        )
    elif sess_done < sess_total:
        fb = _live_session_fallback(minutes_each)
        if fb:
            paper_detail, sess_frac = fb

    units = (trial_n - 1) * sess_total + sess_done + (0.0 if sess_done >= sess_total else sess_frac)
    total_units = max(1, trial_max * sess_total)
    g_pct = 100.0 * units / total_units
    t_pct = 100.0 * (sess_done + (0 if sess_done >= sess_total else sess_frac)) / sess_total
    rem_sess = sess_total - sess_done - (0 if sess_done >= sess_total else sess_frac)
    eta_t = max(0.0, rem_sess * minutes_each)
    eta_g = max(0.0, (total_units - units) * minutes_each)

    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    total = sum(nets)
    saldo = base + total
    avg = total / len(nets) if nets else 0.0
    traded = wins + losses
    wr = wins / traded if traded else 0.0

    enc = "utf-16" if log.is_file() and log.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    mtime = time.strftime("%H:%M:%S", time.localtime(log.stat().st_mtime)) if log.is_file() else "?"
    size_kb = (log.stat().st_size / 1024.0) if log.is_file() else 0.0

    lines.append("=" * 58)
    lines.append(f"  MONITOR paper | base {base:.0f} EUR | tiempo real")
    lines.append("=" * 58)
    lines.append(f"log: {log.name}   proceso: {'VIVO' if alive else 'PARADO'}")
    lines.append(f"log_enc={enc}  size={size_kb:.1f}KB  mtime={mtime}")
    lines.append(f"trial: {trial_n}/{trial_max}  label: {label}")
    lines.append(f"batch: {sess_total} x {minutes_each:g} min | config {cfg_tag}")
    if size_m:
        lines.append(
            f"params: size={size_m.group(1)} mult={size_m.group(2)} edge={size_m.group(3)} "
            f"max_loss={size_m.group(4)} kill={size_m.group(5)}"
        )
    elif cfg_tag == "v7_lock":
        lines.append(
            "params: size=30 cap=36 | lock +1.5EUR | no pyramid | max_loss=2.5 | "
            "mid 0.35-0.65 | 10min | streak_stop=2"
        )
    elif cfg_tag == "v6_10m":
        lines.append(
            "params: size=42 mult=2.2 cap=55 | max_loss=3.5 kill=7 | "
            "10min | mid 0.28-0.72 | streak_stop=2 | NIM"
        )
    elif cfg_tag == "v5_asymmetric":
        lines.append(
            "params: size=48 mult=2.6 cap=70 TP alto | max_loss=5 kill=9 | "
            "let winners run | streak_stop=2 | NIM"
        )
    elif cfg_tag == "v4_cut_tail":
        lines.append(
            "params: size=32 mult=2.0 edge=0.032 max_loss=3.5 kill=6.0 | "
            "streak_stop=2 | NIM exit | mid 0.24-0.76"
        )
    elif cfg_tag == "hito_exact":
        lines.append("params: size=42 mult=3.0 edge=0.03 max_loss=6.0 (hito exact)")
    else:
        lines.append("params: (ver config del log)")
    lines.append("")
    lines.append(
        f"SALDO  {saldo:.2f} EUR   = base {base:.0f}  +  PnL {total:+.2f}"
    )
    lines.append("")
    lines.append(f"GLOBAL  [{_bar(g_pct)}] {g_pct:5.1f}%   ETA ~{eta_g:.0f} min")
    lines.append(f"BATCH   [{_bar(t_pct)}] {t_pct:5.1f}%   ETA ~{eta_t:.0f} min")
    lines.append(f"sesion  {sess_done}/{sess_total} cerradas   actual: {paper_detail}")
    lines.append("")
    lines.append("-- Ganancias (batch) --")
    if nets:
        running = base
        for i, n in enumerate(nets, 1):
            running += n
            tag = "WIN " if n > 0 else ("LOSS" if n < 0 else "FLAT")
            lines.append(f"  S{i}: {tag}  {n:+.2f} EUR  -> saldo {running:.2f}")
        lines.append(
            f"  PnL {total:+.2f} EUR   avg {avg:+.2f} EUR   WR {100*wr:.0f}%  ({wins}W/{losses}L)"
        )
        lines.append(f"  SALDO TOTAL  {saldo:.2f} EUR  ({base:.0f} base + ganado/perdido)")
        lines.append("  grafico nets:")
        for row in _spark(nets):
            lines.append(f"    {row}")
    else:
        lines.append(f"  (sin sesiones cerradas aun)  SALDO = {base:.2f} EUR")
    if wr_hits:
        last = wr_hits[-1]
        lines.append("")
        lines.append(
            f"ultimo trial cerrado: WR={last.group(1)}% avg={last.group(2)} total={last.group(3)}"
        )
    lines.append("")
    if cfg_tag == "v7_lock":
        lines.append(
            "targets: LOCK wins early | no pyramid losers | WR>=50% | stop 2 losses"
        )
    elif cfg_tag == "v6_10m":
        lines.append(
            "targets: 10min fills | mas EUR | WR>=50% | max_loss 3.5 | stop 2 losses"
        )
    elif cfg_tag == "v5_asymmetric":
        lines.append(
            "targets: mas EUR/win | WR>=50% | winners run | stop 2 losses | riesgo↑"
        )
    elif cfg_tag == "v4_cut_tail":
        lines.append(
            "targets: WR>=50% | cola corta | stop tras 2 losses seguidas | NIM assist"
        )
    else:
        lines.append(
            "targets: replay hito/OOS-T1 | WR ref 50-75% | avg ref +15"
        )
    lines.append(f"actualizado: {time.strftime('%H:%M:%S')}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None, help="nombre o path del log (default: mas reciente)")
    ap.add_argument("--watch", type=float, default=2.0, help="segundos entre refrescos (0=una vez)")
    ap.add_argument(
        "--capital",
        type=float,
        default=100.0,
        help="capital base paper en EUR (default 100); SALDO = capital + suma nets",
    )
    args = ap.parse_args()
    log = _pick_log(args.log)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    os.system("")
    if args.watch <= 0:
        print(render(log, capital=args.capital))
        return 0
    prev = ""
    try:
        # Sin borrar pantalla: no parpadea. Solo imprime cuando cambia algo.
        print(render(log, capital=args.capital))
        print("\n--- sin parpadeo; Ctrl+C para salir ---\n")
        while True:
            time.sleep(max(args.watch, 3.0))
            cur = render(log, capital=args.capital)
            if cur == prev:
                continue
            prev = cur
            print("\n" + "=" * 20 + f" update {time.strftime('%H:%M:%S')} " + "=" * 20)
            print(cur)
    except KeyboardInterrupt:
        print("\nmonitor detenido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
