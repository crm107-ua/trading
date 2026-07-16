#!/usr/bin/env python3
"""
Overnight autonomous paper-maker autotune (lab only, no on-chain).

- Ejecuta trials en bucle, muta params/metodología según resultados.
- Guarda informe+cfg+summary por trial bajo data_local/local_lab/overnight/<run_id>/.
- Email a MAIL_TO tras cada trial (y al HIT / fin).
- Objetivo: WR usable + PnL notable (€, no céntimos), cola de pérdidas acotada.

PM2: scripts/ecosystem.poly_overnight.config.cjs
Stop: touch polymarket/data_local/local_lab/STOP_OVERNIGHT
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key
from polymarket.src.notify.mailer import send_email
from polymarket.src.notify.trial_email import (
    build_simple_banner_email,
    build_trial_email,
    strategy_card_html,
)

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
CFG_DIR = POLY / "config"
LAB = POLY / "data_local" / "local_lab"
OVERNIGHT = LAB / "overnight"
STOP_FLAG = LAB / "STOP_OVERNIGHT"

MAX_TRIALS = int(os.getenv("OVERNIGHT_MAX_TRIALS", "12"))
# Targets ambiciosos pero realistas (paper)
HIT_WR = float(os.getenv("OVERNIGHT_HIT_WR", "0.5"))
HIT_AVG = float(os.getenv("OVERNIGHT_HIT_AVG", "8.0"))
HIT_TOTAL = float(os.getenv("OVERNIGHT_HIT_TOTAL", "40.0"))
HIT_MAX_LOSSES = int(os.getenv("OVERNIGHT_HIT_MAX_LOSSES", "3"))
HIT_MIN_TRADED = int(os.getenv("OVERNIGHT_HIT_MIN_TRADED", "4"))
SIZE_HARD_CAP = int(os.getenv("OVERNIGHT_SIZE_CAP", "55"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_configs() -> list[dict]:
    """Metodologías semilla (hito / lock / cut_tail)."""
    seeds: list[dict] = []
    mapping = [
        ("maker_demo_100_usd_margin_v7_lock.json", "seed_v7_lock", 6, 10.0),
        ("maker_demo_100_usd_margin_best.json", "seed_hito_margin", 6, 8.0),
        ("maker_demo_100_usd_margin_v4_cut_tail.json", "seed_v4_cut", 6, 8.0),
        ("maker_demo_100_usd_margin_v6_10m.json", "seed_v6_10m", 6, 10.0),
    ]
    for fname, label, sess, mins in mapping:
        p = CFG_DIR / fname
        if not p.exists():
            continue
        cfg = _load_json(p)
        cfg.update(
            {
                "demo_label": label,
                "paper_touch_fill_every_n": 0,
                "paper_pnl_mode": "",
                "flatten_after_fill": False,
                "mean_reversion_exit": False,
                "exit_hazard_per_s": 0,
                "fair_fade_exit": True,
                "no_pyramid_entries": True,
                "initial_capital_usdc": 100.0,
                "currency_label": "EUR",
                "_sessions": sess,
                "_minutes": mins,
                "_method": label,
            }
        )
        seeds.append(cfg)
    if not seeds:
        raise RuntimeError("No seed configs found under polymarket/config/")
    return seeds


def _hit(row: dict) -> bool:
    return (
        float(row.get("wr") or 0) >= HIT_WR
        and float(row.get("avg") or 0) >= HIT_AVG
        and float(row.get("total") or 0) >= HIT_TOTAL
        and int(row.get("losses") or 99) <= HIT_MAX_LOSSES
        and int(row.get("traded") or 0) >= HIT_MIN_TRADED
    )


def _score(row: dict) -> tuple:
    """Ordenación: HIT primero, luego €, WR, cola corta."""
    return (
        1 if row.get("hit") else 0,
        float(row.get("total") or 0),
        float(row.get("wr") or 0),
        float(row.get("avg") or 0),
        -int(row.get("losses") or 0),
        -abs(float(row.get("worst") or 0)),
        int(row.get("traded") or 0),
    )


def mutate(cfg: dict, rng: random.Random, *, row: dict, gen: int) -> dict:
    """Autoajuste según último resultado."""
    c = deepcopy(cfg)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    wr = float(row.get("wr") or 0)
    avg = float(row.get("avg") or 0)
    total = float(row.get("total") or 0)
    losses = int(row.get("losses") or 0)
    traded = int(row.get("traded") or 0)
    fill_rate = traded / max(1, int(row.get("sessions") or 1))
    sessions = int(c.get("_sessions") or 6)
    minutes = float(c.get("_minutes") or 8.0)
    method = str(c.get("_method") or "mut")

    # Horizonte: poco fill → más minutos; fills ok pero € bajo → tamaño/TP
    if fill_rate < 0.4:
        minutes = min(12.0, minutes + 2.0)
        c["min_edge"] = round(max(0.028, float(c.get("min_edge", 0.03)) - 0.003), 3)
        c["min_quote_mid"] = round(max(0.22, float(c.get("min_quote_mid", 0.3)) - 0.02), 2)
        c["max_quote_mid"] = round(min(0.78, float(c.get("max_quote_mid", 0.7)) + 0.02), 2)
        method = "mut_more_fills"
    elif wr < 0.45 or losses >= 3:
        # Cortar cola
        c["quote_size_shares"] = max(22, int(c.get("quote_size_shares", 30)) - rng.choice([2, 4]))
        c["max_size_mult"] = round(max(1.3, float(c.get("max_size_mult", 1.6)) - 0.15), 2)
        c["max_loss_usdc"] = round(max(1.5, float(c.get("max_loss_usdc", 2.5)) - 0.3), 2)
        c["session_kill_net_usdc"] = round(max(2.5, float(c.get("session_kill_net_usdc", 4)) - 0.5), 1)
        c["lock_profit_usdc"] = round(max(0.8, float(c.get("lock_profit_usdc", 1.5)) - 0.2), 2)
        c["min_edge"] = round(min(0.045, float(c.get("min_edge", 0.03)) + 0.003), 3)
        c["pause_after_consecutive_losses"] = 1
        c["no_pyramid_entries"] = True
        minutes = max(5.0, minutes - 1.0) if fill_rate > 0.7 else minutes
        method = "mut_cut_tail"
    elif wr >= 0.5 and avg < HIT_AVG:
        # WR ok, empujar €
        cap = SIZE_HARD_CAP
        c["quote_size_shares"] = min(cap, int(c.get("quote_size_shares", 30)) + rng.choice([2, 4, 6]))
        c["max_size_mult"] = round(min(2.4, float(c.get("max_size_mult", 1.6)) + 0.15), 2)
        c["lock_profit_usdc"] = round(min(4.0, float(c.get("lock_profit_usdc", 1.5)) + 0.4), 2)
        c["max_take_profit"] = round(min(0.1, float(c.get("max_take_profit", 0.05)) + 0.01), 3)
        c["min_take_profit"] = round(min(0.035, float(c.get("min_take_profit", 0.02)) + 0.003), 3)
        c["max_loss_usdc"] = round(min(5.0, float(c.get("max_loss_usdc", 2.5)) + 0.3), 2)
        minutes = min(12.0, minutes + 1.0)
        method = "mut_scale_eur"
    elif total > 0 and wr >= 0.45:
        # Buen régimen: afinar y alargar batch
        sessions = min(8, sessions + 1)
        c["quote_size_shares"] = min(
            SIZE_HARD_CAP, int(c.get("quote_size_shares", 30)) + rng.choice([0, 2])
        )
        method = "mut_confirm"
    else:
        # Mix
        c["min_edge"] = round(
            min(0.042, max(0.028, float(c.get("min_edge", 0.03)) + rng.choice([-0.002, 0.002]))),
            3,
        )
        method = "mut_explore"

    c["max_quote_size_shares"] = min(
        SIZE_HARD_CAP, max(int(c["quote_size_shares"]), int(c.get("max_quote_size_shares") or 30))
    )
    c["max_inventory_shares"] = int(c["max_quote_size_shares"])
    c["max_inventory_usdc"] = float(c["max_quote_size_shares"])
    c["max_notional_per_side_usdc"] = round(min(55.0, c["quote_size_shares"] * 1.15), 1)
    c["soft_edge"] = round(float(c["min_edge"]) * 1.4, 3)
    c["hard_edge"] = round(float(c["min_edge"]) * 2.2, 3)
    c["fair_fade_exit"] = True
    c["no_pyramid_entries"] = True
    c["pause_after_consecutive_losses"] = 1
    c["_sessions"] = sessions
    c["_minutes"] = round(minutes, 1)
    c["_method"] = method
    c["demo_label"] = f"{method}_g{gen}_{stamp}"
    c["initial_capital_usdc"] = 100.0
    c["currency_label"] = "EUR"
    return c


def _write_trial_report(trial_dir: Path, row: dict, cfg: dict, summary: dict) -> Path:
    trial_dir.mkdir(parents=True, exist_ok=True)
    (trial_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (trial_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (trial_dir / "row.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    md = trial_dir / "INFORME.md"
    nets = row.get("nets") or []
    lines = [
        f"# Trial {row.get('trial')} — {row.get('label')}",
        "",
        f"- method: `{row.get('method')}`",
        f"- sessions×min: {row.get('sessions')}×{row.get('minutes')}",
        f"- WR: {100*float(row.get('wr') or 0):.1f}% ({row.get('wins')}W/{row.get('losses')}L)",
        f"- total PnL: {float(row.get('total') or 0):+.2f} EUR",
        f"- avg: {float(row.get('avg') or 0):+.2f} EUR",
        f"- worst/best: {row.get('worst')} / {row.get('best_sess')}",
        f"- traded: {row.get('traded')}",
        f"- HIT: {row.get('hit')}",
        f"- size/mult/edge/max_loss: {cfg.get('quote_size_shares')}/{cfg.get('max_size_mult')}/"
        f"{cfg.get('min_edge')}/{cfg.get('max_loss_usdc')}",
        f"- lock_profit_usdc: {cfg.get('lock_profit_usdc')}",
        "",
        "## Nets",
        "```",
        str(nets),
        "```",
        "",
        f"Saldo paper: {100 + float(row.get('total') or 0):.2f} EUR (base 100)",
        "",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def _strategy_record(row: dict, cfg: dict, run_id: str) -> dict:
    """Entrada etiquetada para el leaderboard persistente."""
    label = str(row.get("label") or "unnamed")
    method = str(row.get("method") or "unknown")
    trial = int(row.get("trial") or 0)
    tag = f"{run_id}::T{trial:02d}::{method}::{label}"
    name = f"{method} · {label}"
    return {
        "tag": tag,
        "name": name,
        "label": label,
        "method": method,
        "trial": trial,
        "run_id": run_id,
        "wr": row.get("wr"),
        "avg": row.get("avg"),
        "total": row.get("total"),
        "wins": row.get("wins"),
        "losses": row.get("losses"),
        "traded": row.get("traded"),
        "sessions": row.get("sessions"),
        "minutes": row.get("minutes"),
        "nets": row.get("nets"),
        "worst": row.get("worst"),
        "best_sess": row.get("best_sess"),
        "hit": row.get("hit"),
        "params": {
            "size": cfg.get("quote_size_shares"),
            "mult": cfg.get("max_size_mult"),
            "cap": cfg.get("max_quote_size_shares"),
            "edge": cfg.get("min_edge"),
            "soft_edge": cfg.get("soft_edge"),
            "hard_edge": cfg.get("hard_edge"),
            "max_loss": cfg.get("max_loss_usdc"),
            "kill": cfg.get("session_kill_net_usdc"),
            "lock": cfg.get("lock_profit_usdc"),
            "mid_lo": cfg.get("min_quote_mid"),
            "mid_hi": cfg.get("max_quote_mid"),
            "tp_min": cfg.get("min_take_profit"),
            "tp_max": cfg.get("max_take_profit"),
            "entries": cfg.get("max_entry_fills"),
            "no_pyramid": cfg.get("no_pyramid_entries"),
            "fair_fade": cfg.get("fair_fade_exit"),
        },
    }


def _leaderboard_path() -> Path:
    return OVERNIGHT / "leaderboard.json"


def _upsert_leaderboard(entry: dict) -> list[dict]:
    """Acumula estrategias entre reinicios; devuelve top 10 ordenado."""
    path = _leaderboard_path()
    items: list[dict] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = list(raw.get("strategies") or [])
        except Exception:
            items = []
    by_tag = {str(x.get("tag")): x for x in items if x.get("tag")}
    by_tag[str(entry["tag"])] = entry

    def sort_key(x: dict) -> tuple:
        return (
            1 if x.get("hit") else 0,
            float(x.get("total") or 0),
            float(x.get("wr") or 0),
            float(x.get("avg") or 0),
            -int(x.get("losses") or 0),
            -abs(float(x.get("worst") or 0)),
            int(x.get("traded") or 0),
        )

    ranked = sorted(by_tag.values(), key=sort_key, reverse=True)
    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(ranked),
        "strategies": ranked,
        "top10": ranked[:10],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ranked[:10]


def _email_trial(
    row: dict,
    cfg: dict,
    run_id: str,
    trial_dir: Path,
    summary: dict | None = None,
    top10: list[dict] | None = None,
) -> dict:
    subject, body, html = build_trial_email(
        row=row,
        cfg=cfg,
        run_id=run_id,
        trial_dir=str(trial_dir),
        summary=summary,
        top10=top10 or [],
    )
    return send_email(subject=subject, body_text=body, body_html=html)


async def main() -> int:
    require_nvidia_api_key()
    LAB.mkdir(parents=True, exist_ok=True)
    OVERNIGHT.mkdir(parents=True, exist_ok=True)
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()

    run_id = f"run_{_now()}"
    run_dir = OVERNIGHT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(datetime.now(timezone.utc).timestamp()) % 10_000_000)

    meta = {
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "max_trials": MAX_TRIALS,
        "hit": {
            "wr": HIT_WR,
            "avg": HIT_AVG,
            "total": HIT_TOTAL,
            "max_losses": HIT_MAX_LOSSES,
            "min_traded": HIT_MIN_TRADED,
        },
        "live_onchain": False,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    start_body = (
        f"Overnight autotune started.\n"
        f"run_dir={run_dir}\n"
        f"max_trials={MAX_TRIALS}\n"
        f"HIT targets: WR>={HIT_WR} avg>={HIT_AVG}€ total>={HIT_TOTAL}€ "
        f"losses<={HIT_MAX_LOSSES} traded>={HIT_MIN_TRADED}\n"
        f"Cada trial: email con análisis + Top 10 estrategias acumulado "
        f"(nombre, método, params, métricas).\n"
        f"Leaderboard persistente: {OVERNIGHT / 'leaderboard.json'}\n"
    )
    _, start_html = build_simple_banner_email(
        title=f"START {run_id}",
        body=start_body,
    )
    send_email(
        subject=f"[poly] START overnight {run_id}",
        body_text=start_body,
        body_html=start_html,
    )

    seeds = _seed_configs()
    history: list[dict] = []
    best: dict | None = None
    cfg = seeds[0]

    for i in range(1, MAX_TRIALS + 1):
        if STOP_FLAG.exists():
            print("STOP_OVERNIGHT flag — exiting", flush=True)
            break

        if i == 1:
            cfg = seeds[0]
        elif i <= len(seeds):
            # Alterna semillas temprano
            cfg = seeds[i - 1]
        else:
            base_cfg = best["cfg"] if best else cfg
            base_row = best["row"] if best else history[-1]
            cfg = mutate(base_cfg, rng, row=base_row, gen=i)

        sessions = int(cfg.get("_sessions") or 6)
        minutes = float(cfg.get("_minutes") or 8.0)
        trial_dir = run_dir / f"trial_{i:02d}_{cfg.get('demo_label', 'x')}"
        cfg_path = trial_dir / "config.json"
        trial_dir.mkdir(parents=True, exist_ok=True)
        # strip runtime keys for paper_maker file (keep copies in meta)
        cfg_disk = {k: v for k, v in cfg.items() if not k.startswith("_")}
        cfg_path.write_text(json.dumps(cfg_disk, indent=2), encoding="utf-8")

        print(
            f"\n######## OVERNIGHT {i}/{MAX_TRIALS} {cfg.get('demo_label')} "
            f"{sessions}x{minutes}m method={cfg.get('_method')} ########",
            flush=True,
        )
        try:
            summary = await run_batch(
                strategy="maker_edge",
                config=str(cfg_path),
                sessions=sessions,
                minutes=minutes,
            )
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()
            (trial_dir / "error.txt").write_text(tb, encoding="utf-8")
            print(f"WARN trial failed: {err}", flush=True)
            send_email(
                subject=f"[poly-overnight] T{i} ERROR",
                body_text=f"Trial {i} failed: {err}\n{trial_dir}\n",
            )
            await asyncio.sleep(10)
            continue

        nets = [r["net"] for r in summary.get("results") or []]
        total = round(sum(nets), 2) if nets else 0.0
        row = {
            "trial": i,
            "label": cfg.get("demo_label"),
            "method": cfg.get("_method"),
            "sessions": sessions,
            "minutes": minutes,
            "wr": summary.get("win_rate"),
            "avg": summary.get("avg_net_usdc"),
            "total": total,
            "wins": summary.get("wins"),
            "losses": summary.get("losses"),
            "traded": summary.get("sessions_with_fills"),
            "worst": min(nets) if nets else None,
            "best_sess": max(nets) if nets else None,
            "nets": nets,
            "size": cfg_disk.get("quote_size_shares"),
            "max_loss": cfg_disk.get("max_loss_usdc"),
            "edge": cfg_disk.get("min_edge"),
            "lock": cfg_disk.get("lock_profit_usdc"),
            "stopped_early_streak": summary.get("stopped_early_streak"),
            "hit": False,
        }
        row["hit"] = _hit(row)
        entry = _strategy_record(row, cfg_disk, run_id)
        _write_trial_report(trial_dir, row, cfg_disk, summary)
        (trial_dir / "strategy.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
        history.append(row)
        (run_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

        print(
            f"-> WR={100*(row['wr'] or 0):.1f}% avg={row['avg']:+.2f} total={total:+.2f} "
            f"losses={row['losses']} HIT={row['hit']}",
            flush=True,
        )

        top10 = _upsert_leaderboard(entry)
        (run_dir / "top10.json").write_text(json.dumps(top10, indent=2), encoding="utf-8")

        mail_r = _email_trial(
            row, cfg_disk, run_id, trial_dir, summary=summary, top10=top10
        )
        print(f"mail: ok={mail_r.get('ok')} to={mail_r.get('to')!r}", flush=True)

        sc = _score(row)
        freeze = CFG_DIR / "maker_demo_100_usd_overnight_best.json"
        if best is None or sc > best["score"]:
            best = {"score": sc, "cfg": deepcopy(cfg), "row": row}
            (run_dir / "best.json").write_text(
                json.dumps({"cfg": cfg_disk, "row": row, "entry": entry}, indent=2),
                encoding="utf-8",
            )
            freeze.write_text(json.dumps(cfg_disk, indent=2), encoding="utf-8")
            (LAB / "overnight_best.json").write_text(
                json.dumps(
                    {"cfg": cfg_disk, "row": row, "run_id": run_id, "entry": entry},
                    indent=2,
                ),
                encoding="utf-8",
            )

        if row["hit"]:
            hit_body = (
                f"TARGET HIT en trial {i}.\n"
                f"total={total:+.2f} EUR  WR={100*(row['wr'] or 0):.1f}%\n"
                f"best_cfg={freeze}\n\n{json.dumps(row, indent=2)}\n\n"
                f"TOP 10:\n{json.dumps(top10, indent=2)}\n"
            )
            # Reusa plantilla trial (incluye Top 10 visual)
            _, _, hit_html = build_trial_email(
                row=row,
                cfg=cfg_disk,
                run_id=run_id,
                trial_dir=str(trial_dir),
                summary=summary,
                top10=top10,
            )
            send_email(
                subject=f"[poly] *** HIT *** T{i} total={total:+.1f}€",
                body_text=hit_body,
                body_html=hit_html,
            )
            print("\n*** OVERNIGHT TARGET HIT ***", flush=True)
            return 0

        # Pequeña pausa entre trials (feeds)
        await asyncio.sleep(5)

    # Fin
    top10_final = []
    lb_path = _leaderboard_path()
    if lb_path.is_file():
        try:
            top10_final = list(json.loads(lb_path.read_text(encoding="utf-8")).get("top10") or [])
        except Exception:
            top10_final = []
    fin = {
        "run_id": run_id,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "trials_done": len(history),
        "best": best["row"] if best else None,
        "top10": top10_final,
    }
    (run_dir / "final.json").write_text(json.dumps(fin, indent=2), encoding="utf-8")
    fin_lines = [
        f"FIN overnight {run_id}",
        f"trials_done={len(history)}",
        f"best={json.dumps(best['row'] if best else None, indent=2)}",
        "",
        "=== TOP 10 ESTRATEGIAS (acumulado) ===",
    ]
    for j, s in enumerate(top10_final[:10], 1):
        p = s.get("params") or {}
        fin_lines.append(
            f"{j}. [{s.get('tag')}] {s.get('name')} | method={s.get('method')} | "
            f"PnL={s.get('total')} WR={s.get('wr')} avg={s.get('avg')} | "
            f"size={p.get('size')} edge={p.get('edge')} lock={p.get('lock')}"
        )
    fin_body = "\n".join(fin_lines) + "\n"
    # HTML FIN: banner + cards Top 10
    cards = "".join(strategy_card_html(j, s) for j, s in enumerate(top10_final[:10], 1))
    if not cards:
        cards = "<div style='padding:12px;color:#78716c;'>Sin ranking aún.</div>"
    _, fin_banner = build_simple_banner_email(title=f"FIN {run_id}", body=fin_body)
    fin_html = fin_banner.replace(
        "</body>",
        f"""<div style="max-width:560px;margin:0 auto;padding:0 16px 24px;">
          <div style="background:#fff;border-radius:16px;padding:16px;">
            <div style="font-size:16px;font-weight:800;margin-bottom:10px;">Top 10 estrategias</div>
            {cards}
          </div>
        </div></body>""",
    )
    send_email(
        subject=f"[poly] FIN overnight {run_id} trials={len(history)}",
        body_text=fin_body,
        body_html=fin_html,
    )
    print(json.dumps(fin, indent=2), flush=True)
    return 0 if best and best["row"].get("hit") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
