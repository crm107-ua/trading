#!/usr/bin/env python3
"""
Overnight paper autotune — planner inteligente (lab only, no on-chain).

No combina params al azar. Cada trial es una hipótesis etiquetada:
  1) Evalúa familias DNA conocidas (lock / hito / cut_tail / selectivo).
  2) Diagnostica el resultado (fills, cola, WR, €).
  3) Elige el siguiente ajuste de UN eje (o cambia de familia) con reglas.
  4) Categoriza mejor→peor y acumula Top 10.

PM2: scripts/ecosystem.poly_overnight.config.cjs
Stop: touch polymarket/data_local/local_lab/STOP_OVERNIGHT
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
HIT_WR = float(os.getenv("OVERNIGHT_HIT_WR", "0.5"))
HIT_AVG = float(os.getenv("OVERNIGHT_HIT_AVG", "8.0"))
HIT_TOTAL = float(os.getenv("OVERNIGHT_HIT_TOTAL", "40.0"))
HIT_MAX_LOSSES = int(os.getenv("OVERNIGHT_HIT_MAX_LOSSES", "3"))
HIT_MIN_TRADED = int(os.getenv("OVERNIGHT_HIT_MIN_TRADED", "4"))
SIZE_HARD_CAP = int(os.getenv("OVERNIGHT_SIZE_CAP", "48"))
SIZE_SOFT_CAP = int(os.getenv("OVERNIGHT_SIZE_SOFT", "42"))  # hito histórico; no forzar 55


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Familias DNA — metodologías coherentes (no combos random)
# ---------------------------------------------------------------------------

FAMILY_SPECS: list[dict[str, Any]] = [
    {
        "family": "lock_green",
        "file": "maker_demo_100_usd_margin_v7_lock.json",
        "sessions": 6,
        "minutes": 10.0,
        "hypothesis": (
            "Lock +1.5€ sin pyramid. Edge/mid calibrados para poder cotizar "
            "(evita wait_edge eterno): edge 0.032, mid 0.28–0.72, min_z 1.0."
        ),
        # v7 crudo (edge 0.038 + mid 0.35–0.65) se queda en 0 fills en mercados calmados.
        "overlays": {
            "min_edge": 0.032,
            "soft_edge": 0.045,
            "hard_edge": 0.07,
            "min_z": 1.0,
            "min_expected_pnl_usdc": 0.40,
            "min_quote_mid": 0.28,
            "max_quote_mid": 0.72,
        },
    },
    {
        "family": "hito_margin_safe",
        "file": "maker_demo_100_usd_margin_best.json",
        "sessions": 6,
        "minutes": 8.0,
        "hypothesis": (
            "DNA hito margin_max_v3 (WR~75% histórico) con guardrails: "
            "no_pyramid, lock 2€, mid band, entries≤6, size soft-cap 42."
        ),
        "overlays": {
            "no_pyramid_entries": True,
            "fair_fade_exit": True,
            "lock_profit_usdc": 2.0,
            "min_edge": 0.030,
            "min_z": 1.0,
            "min_expected_pnl_usdc": 0.35,
            "min_quote_mid": 0.28,
            "max_quote_mid": 0.72,
            "max_entry_fills": 6,
            "quote_size_shares": 42,
            "max_size_mult": 2.2,
            "max_quote_size_shares": 48,
            "max_loss_usdc": 4.0,
            "session_kill_net_usdc": 6.0,
            "pause_after_consecutive_losses": 1,
            "pause_entries_s": 360,
            "currency_label": "EUR",
        },
    },
    {
        "family": "cut_tail",
        "file": "maker_demo_100_usd_margin_v4_cut_tail.json",
        "sessions": 6,
        "minutes": 8.0,
        "hypothesis": (
            "Cortar cola: size 32, max_loss 3.5, kill sesión, pause tras 1 loss. "
            "Prioriza WR y peores acotados frente a size máximo."
        ),
        "overlays": {
            "no_pyramid_entries": True,
            "lock_profit_usdc": 1.2,
            "min_z": 1.0,
            "min_expected_pnl_usdc": 0.35,
        },
    },
    {
        "family": "selective_edge",
        "file": "maker_demo_100_usd_margin_v7_lock.json",
        "sessions": 6,
        "minutes": 10.0,
        "hypothesis": (
            "Calidad > cantidad: edge 0.036 (no 0.042), mid 0.32–0.68, size 34, lock 2€. "
            "Solo tras haber demostrado fills en familias más abiertas."
        ),
        "overlays": {
            "min_edge": 0.036,
            "soft_edge": 0.05,
            "hard_edge": 0.078,
            "min_z": 1.05,
            "min_quote_mid": 0.32,
            "max_quote_mid": 0.68,
            "quote_size_shares": 34,
            "max_quote_size_shares": 40,
            "max_size_mult": 1.8,
            "lock_profit_usdc": 2.0,
            "max_loss_usdc": 2.2,
            "max_entry_fills": 3,
            "min_expected_pnl_usdc": 0.50,
        },
    },
]


def _apply_lab_invariants(cfg: dict) -> dict:
    """Reglas duras del lab: sin pyramid, sin fills sintéticos, capital 100€."""
    c = cfg
    c["paper_touch_fill_every_n"] = 0
    c["paper_pnl_mode"] = ""
    c["flatten_after_fill"] = False
    c["mean_reversion_exit"] = False
    c["exit_hazard_per_s"] = 0
    c["fair_fade_exit"] = True
    c["no_pyramid_entries"] = True
    c["pause_after_consecutive_losses"] = int(c.get("pause_after_consecutive_losses") or 1)
    c["initial_capital_usdc"] = 100.0
    c["currency_label"] = "EUR"
    size = int(c.get("quote_size_shares") or 30)
    size = max(20, min(SIZE_HARD_CAP, size))
    c["quote_size_shares"] = size
    cap = max(size, int(c.get("max_quote_size_shares") or size))
    cap = min(SIZE_HARD_CAP, cap)
    c["max_quote_size_shares"] = cap
    c["max_inventory_shares"] = cap
    c["max_inventory_usdc"] = float(cap)
    c["max_notional_per_side_usdc"] = round(min(55.0, size * 1.15), 1)
    edge = float(c.get("min_edge") or 0.03)
    c["min_edge"] = round(edge, 3)
    c["soft_edge"] = round(float(c.get("soft_edge") or edge * 1.4), 3)
    c["hard_edge"] = round(float(c.get("hard_edge") or edge * 2.2), 3)
    # Caps de sentido €: no reabrir "let winners run" / pyramid
    if int(c.get("max_entry_fills") or 0) > 8:
        c["max_entry_fills"] = 8
    if float(c.get("max_size_mult") or 1) > 2.6:
        c["max_size_mult"] = 2.6
    return c


def _build_family_cfg(spec: dict[str, Any]) -> dict:
    path = CFG_DIR / spec["file"]
    if not path.exists():
        raise FileNotFoundError(path)
    cfg = _load_json(path)
    cfg.update(spec.get("overlays") or {})
    cfg = _apply_lab_invariants(cfg)
    family = spec["family"]
    cfg["_family"] = family
    cfg["_method"] = family
    cfg["_sessions"] = int(spec["sessions"])
    cfg["_minutes"] = float(spec["minutes"])
    cfg["_hypothesis"] = spec["hypothesis"]
    cfg["_rationale"] = f"Evaluar familia DNA «{family}» con batch fijo."
    cfg["_diagnosis_prev"] = None
    cfg["demo_label"] = f"fam_{family}"
    return cfg


def _seed_queue() -> list[dict]:
    out: list[dict] = []
    for spec in FAMILY_SPECS:
        p = CFG_DIR / spec["file"]
        if not p.exists():
            print(f"WARN skip family {spec['family']}: missing {p}", flush=True)
            continue
        out.append(_build_family_cfg(spec))
    if not out:
        raise RuntimeError("No strategy families available under polymarket/config/")
    return out


# ---------------------------------------------------------------------------
# Diagnóstico + categoría (mejor / peor)
# ---------------------------------------------------------------------------

def diagnose(row: dict) -> dict[str, str]:
    """Clasifica el resultado para decidir el siguiente eje a mover."""
    sessions = max(1, int(row.get("sessions") or 1))
    traded = int(row.get("traded") or 0)
    fill_rate = traded / sessions
    wr = float(row.get("wr") or 0)
    avg = float(row.get("avg") or 0)
    total = float(row.get("total") or 0)
    losses = int(row.get("losses") or 0)
    worst = row.get("worst")
    worst_f = float(worst) if worst is not None else 0.0

    if traded == 0:
        code = "STARVED"
        detail = "0 fills: edge/mid demasiado restrictivos o ventana corta."
    elif fill_rate < 0.35:
        code = "LOW_FILLS"
        detail = f"Fill rate {fill_rate:.0%}: poco sample; hay que abrir calidad o tiempo."
    elif losses >= 3 or wr < 0.35:
        code = "TOXIC_TAIL"
        detail = f"Cola tóxica: WR={wr:.0%} losses={losses}. Recortar size/riesgo."
    elif worst_f <= -8.0:
        code = "FAT_TAIL"
        detail = f"Peor sesión {worst_f:+.2f}€: max_loss/kill demasiado flojos."
    elif wr >= 0.5 and avg < 4.0:
        code = "WR_OK_EUR_LOW"
        detail = "WR usable pero avg bajo: escalar € con cuidado (size/lock/TP)."
    elif total > 0 and wr < 0.45:
        code = "EUR_OK_WR_FRAGILE"
        detail = "Verde frágil (WR bajo): priorizar selectividad sobre size."
    elif total >= 20 and wr >= 0.45:
        code = "GREEN_STRONG"
        detail = "Régimen fuerte: confirmar con más sesiones, sin abrir riesgo."
    elif total > 0:
        code = "GREEN_SOFT"
        detail = "Verde suave: afinar un eje hacia HIT."
    else:
        code = "DEAD_RED"
        detail = "Rojo: cambiar familia o cortar cola fuerte."

    return {"code": code, "detail": detail}


def categorize(row: dict) -> str:
    """Etiqueta estable para ranking mejor→peor."""
    if row.get("hit"):
        return "ELITE"
    total = float(row.get("total") or 0)
    wr = float(row.get("wr") or 0)
    losses = int(row.get("losses") or 0)
    traded = int(row.get("traded") or 0)
    if traded == 0:
        return "STARVED"
    if total >= 15 and wr >= 0.5 and losses <= 3:
        return "ELITE"
    if total > 5 and wr >= 0.4:
        return "PROMISING"
    if total > 0:
        return "MARGINAL"
    if wr < 0.35 or losses >= 3:
        return "REJECT"
    return "WEAK"


CATEGORY_RANK = {
    "ELITE": 5,
    "PROMISING": 4,
    "MARGINAL": 3,
    "WEAK": 2,
    "STARVED": 1,
    "REJECT": 0,
}


def _hit(row: dict) -> bool:
    return (
        float(row.get("wr") or 0) >= HIT_WR
        and float(row.get("avg") or 0) >= HIT_AVG
        and float(row.get("total") or 0) >= HIT_TOTAL
        and int(row.get("losses") or 99) <= HIT_MAX_LOSSES
        and int(row.get("traded") or 0) >= HIT_MIN_TRADED
    )


def _score(row: dict) -> tuple:
    cat = CATEGORY_RANK.get(str(row.get("category") or categorize(row)), 0)
    return (
        1 if row.get("hit") else 0,
        cat,
        float(row.get("total") or 0),
        float(row.get("wr") or 0),
        float(row.get("avg") or 0),
        -int(row.get("losses") or 0),
        -abs(float(row.get("worst") or 0)),
        int(row.get("traded") or 0),
    )


# ---------------------------------------------------------------------------
# Planner: siguiente hipótesis (1 eje / cambio de familia)
# ---------------------------------------------------------------------------

def _sync_size_caps(c: dict) -> None:
    size = max(20, min(SIZE_HARD_CAP, int(c.get("quote_size_shares") or 30)))
    c["quote_size_shares"] = size
    cap = min(SIZE_HARD_CAP, max(size, int(c.get("max_quote_size_shares") or size)))
    c["max_quote_size_shares"] = cap
    c["max_inventory_shares"] = cap
    c["max_inventory_usdc"] = float(cap)
    c["max_notional_per_side_usdc"] = round(min(55.0, size * 1.15), 1)
    edge = float(c.get("min_edge") or 0.03)
    c["soft_edge"] = round(max(float(c.get("soft_edge") or 0), edge * 1.35), 3)
    c["hard_edge"] = round(max(float(c.get("hard_edge") or 0), edge * 2.0), 3)


def _cfg_from_leaderboard_entry(entry: dict) -> dict:
    """Reconstruye cfg ejecutable desde entrada del Top (cfg guardado o params)."""
    raw = entry.get("cfg")
    if isinstance(raw, dict) and raw.get("quote_size_shares") is not None:
        c = deepcopy(raw)
    else:
        # Fallback: overlay params sobre DNA lock
        c = _load_json(CFG_DIR / "maker_demo_100_usd_margin_v7_lock.json")
        p = entry.get("params") or {}
        mapping = {
            "size": "quote_size_shares",
            "mult": "max_size_mult",
            "cap": "max_quote_size_shares",
            "edge": "min_edge",
            "soft_edge": "soft_edge",
            "hard_edge": "hard_edge",
            "max_loss": "max_loss_usdc",
            "kill": "session_kill_net_usdc",
            "lock": "lock_profit_usdc",
            "mid_lo": "min_quote_mid",
            "mid_hi": "max_quote_mid",
            "tp_min": "min_take_profit",
            "tp_max": "max_take_profit",
            "entries": "max_entry_fills",
        }
        for pk, ck in mapping.items():
            if p.get(pk) is not None:
                c[ck] = p[pk]
    c = _apply_lab_invariants(c)
    c["_family"] = str(entry.get("family") or "top")
    c["_method"] = str(entry.get("method") or "refine_top")
    c["_sessions"] = int(entry.get("sessions") or 6)
    c["_minutes"] = float(entry.get("minutes") or 10.0)
    return c


def plan_refine_top(*, top_entry: dict, gen: int, refine_round: int) -> dict:
    """
    Mejora una estrategia del Top 5: un eje por ronda para maximizar €
    sin destruir WR (lecciones del lab: no size↑ agresivo).
    """
    c = _cfg_from_leaderboard_entry(top_entry)
    family = str(top_entry.get("family") or c.get("_family") or "top")
    wr = float(top_entry.get("wr") or 0)
    avg = float(top_entry.get("avg") or 0)
    total = float(top_entry.get("total") or 0)
    axis = refine_round % 4
    minutes = float(c.get("_minutes") or 10.0)
    sessions = int(c.get("_sessions") or 6)

    if axis == 0 and wr >= 0.45:
        method = "refine_scale_eur"
        c["quote_size_shares"] = min(SIZE_SOFT_CAP, int(c.get("quote_size_shares", 30)) + 2)
        c["lock_profit_usdc"] = round(min(3.5, float(c.get("lock_profit_usdc", 1.5)) + 0.4), 2)
        c["max_take_profit"] = round(min(0.09, float(c.get("max_take_profit", 0.05)) + 0.01), 3)
        hyp = (
            f"REFINE Top «{top_entry.get('name')}»: WR={wr:.0%} total={total:+.1f} → "
            f"+2 size (≤{SIZE_SOFT_CAP}), lock↑, TP↑ para más €."
        )
    elif axis == 1:
        method = "refine_confirm"
        sessions = min(8, sessions + 2)
        minutes = min(12.0, max(minutes, 10.0))
        hyp = (
            f"REFINE Top «{top_entry.get('name')}»: confirmar con {sessions}×{minutes}m "
            f"(params congelados) para validar edge real."
        )
    elif axis == 2 and wr >= 0.5 and avg < HIT_AVG:
        method = "refine_lock_avg"
        c["lock_profit_usdc"] = round(min(3.5, float(c.get("lock_profit_usdc", 1.5)) + 0.5), 2)
        c["min_take_profit"] = round(min(0.03, float(c.get("min_take_profit", 0.02)) + 0.003), 3)
        minutes = min(12.0, minutes + 1.0)
        hyp = (
            f"REFINE Top «{top_entry.get('name')}»: WR alto pero avg {avg:+.2f} < HIT → "
            f"subir lock/TP sin tocar size."
        )
    else:
        method = "refine_protect_edge"
        # Si WR flojo o eje default: un poco más selectivo + mismo size
        c["min_edge"] = round(min(0.038, float(c.get("min_edge", 0.03)) + 0.002), 3)
        c["max_loss_usdc"] = round(max(1.5, float(c.get("max_loss_usdc", 2.5)) - 0.2), 2)
        c["lock_profit_usdc"] = round(max(1.2, float(c.get("lock_profit_usdc", 1.5))), 2)
        hyp = (
            f"REFINE Top «{top_entry.get('name')}»: proteger WR (edge+0.002, max_loss↓) "
            f"y mantener DNA ganador."
        )

    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    c = _apply_lab_invariants(c)
    _sync_size_caps(c)
    c["_family"] = family
    c["_method"] = method
    c["_sessions"] = sessions
    c["_minutes"] = round(minutes, 1)
    c["_hypothesis"] = hyp
    c["_rationale"] = (
        f"Nuevas estrategias fuera del Top 5 → mejorar #{refine_round + 1} del ranking "
        f"(tag={top_entry.get('tag')})."
    )
    c["_diagnosis_prev"] = "REFINE_TOP"
    c["demo_label"] = f"{method}_g{gen}_{stamp}"
    return c


def plan_next(
    *,
    base_cfg: dict,
    row: dict,
    diagnosis: dict[str, str],
    gen: int,
    families_tried: set[str],
    methods_tried: set[str],
    refine_top: bool = False,
    top_entry: dict | None = None,
    refine_round: int = 0,
) -> dict:
    """
    Elige la siguiente prueba con reglas (sin random).
    Preferencia:
      0) refine_top si nuevas no entran en Top 5
      1) si STARVED → open_feed (no quemar familias selectivas)
      2) familia DNA pendiente
      3) ajuste de un eje sobre el best
    """
    if refine_top and top_entry:
        return plan_refine_top(top_entry=top_entry, gen=gen, refine_round=refine_round)

    code = diagnosis["code"]

    # Starve: abrir feed YA (no pasar a selective_edge con 0 fills)
    if code == "STARVED":
        open_count = sum(1 for m in methods_tried if str(m).startswith("open_feed"))
        if open_count < 3:
            c = deepcopy(base_cfg)
            method = "open_feed"
            minutes = min(12.0, float(c.get("_minutes") or 8.0) + 2.0)
            c["min_edge"] = round(max(0.026, float(c.get("min_edge", 0.032)) - 0.006), 3)
            c["min_z"] = round(max(0.85, float(c.get("min_z", 1.0)) - 0.15), 2)
            c["min_quote_mid"] = round(max(0.18, float(c.get("min_quote_mid", 0.28)) - 0.06), 2)
            c["max_quote_mid"] = round(min(0.82, float(c.get("max_quote_mid", 0.72)) + 0.06), 2)
            c["min_expected_pnl_usdc"] = round(
                max(0.25, float(c.get("min_expected_pnl_usdc", 0.40)) - 0.12), 2
            )
            c["quote_time_min_s"] = max(15, int(float(c.get("quote_time_min_s") or 60) - 30))
            # Ventanas BTC 5m: permitir cotizar casi todo el tramo útil
            c["quote_time_max_s"] = max(int(c.get("quote_time_max_s") or 520), 280)
            hyp = (
                "STARVE: bajar edge/z/mid/EV y +2 min. Si mid~0.9 era wait_mid_hi "
                "(lotería); ampliamos banda 0.18–0.82 y esperamos ventana usable."
            )
            c = _apply_lab_invariants(c)
            _sync_size_caps(c)
            stamp = datetime.now(timezone.utc).strftime("%H%M%S")
            c["_family"] = str(c.get("_family") or "lock_green")
            c["_method"] = method
            c["_sessions"] = min(6, int(c.get("_sessions") or 6))
            c["_minutes"] = round(minutes, 1)
            c["_hypothesis"] = hyp
            c["_rationale"] = f"Diagnóstico STARVED: {diagnosis['detail']}"
            c["_diagnosis_prev"] = code
            c["demo_label"] = f"{method}_g{gen}_{stamp}"
            return c

    # Familias pendientes (skip selective si venimos de starve reciente)
    for spec in FAMILY_SPECS:
        fam = spec["family"]
        if fam not in families_tried and (CFG_DIR / spec["file"]).exists():
            if code == "STARVED" and fam == "selective_edge":
                continue
            cfg = _build_family_cfg(spec)
            cfg["_rationale"] = (
                f"Tras diagnóstico {code}: aún falta evaluar familia «{fam}»."
            )
            cfg["_diagnosis_prev"] = code
            return cfg

    c = deepcopy(base_cfg)
    minutes = float(c.get("_minutes") or 8.0)
    sessions = int(c.get("_sessions") or 6)
    family = str(c.get("_family") or c.get("_method") or "adapt")
    method = "adapt"
    hyp = ""
    rationale = diagnosis["detail"]

    if code == "STARVED":
        method = "open_feed"
        minutes = min(12.0, minutes + 2.0)
        c["min_edge"] = round(max(0.026, float(c.get("min_edge", 0.032)) - 0.004), 3)
        c["min_z"] = round(max(0.85, float(c.get("min_z", 1.0)) - 0.1), 2)
        c["min_quote_mid"] = round(max(0.22, float(c.get("min_quote_mid", 0.28)) - 0.03), 2)
        c["max_quote_mid"] = round(min(0.78, float(c.get("max_quote_mid", 0.72)) + 0.03), 2)
        c["min_expected_pnl_usdc"] = round(max(0.25, float(c.get("min_expected_pnl_usdc", 0.4)) - 0.1), 2)
        hyp = "Bajar barreras de entrada (edge/mid/z/EV) y +2 min para obtener fills reales."
    elif code == "LOW_FILLS":
        method = "more_time"
        minutes = min(12.0, max(10.0, minutes + 2.0))
        sessions = min(8, sessions + 1) if minutes >= 10 else sessions
        c["min_edge"] = round(max(0.028, float(c.get("min_edge", 0.032)) - 0.002), 3)
        c["min_z"] = round(max(0.9, float(c.get("min_z", 1.0)) - 0.05), 2)
        hyp = "Más tiempo de mercado; edge/z ↓ para sample usable sin tirar calidad."
    elif code in ("TOXIC_TAIL", "FAT_TAIL", "DEAD_RED"):
        method = "cut_tail_hard"
        c["quote_size_shares"] = max(22, int(c.get("quote_size_shares", 30)) - 4)
        c["max_size_mult"] = round(max(1.4, float(c.get("max_size_mult", 1.6)) - 0.2), 2)
        c["max_loss_usdc"] = round(max(1.5, float(c.get("max_loss_usdc", 2.5)) - 0.5), 2)
        c["session_kill_net_usdc"] = round(max(2.5, float(c.get("session_kill_net_usdc", 4)) - 0.5), 1)
        c["lock_profit_usdc"] = round(max(0.8, min(2.0, float(c.get("lock_profit_usdc", 1.5)))), 2)
        c["min_edge"] = round(min(0.045, float(c.get("min_edge", 0.03)) + 0.003), 3)
        c["max_entry_fills"] = min(3, int(c.get("max_entry_fills") or 3))
        c["no_pyramid_entries"] = True
        minutes = max(6.0, minutes - 1.0) if code == "TOXIC_TAIL" else minutes
        hyp = "Cortar cola: −size, −max_loss, edge↑, entries≤3. Sin abrir riesgo."
    elif code == "WR_OK_EUR_LOW":
        method = "scale_eur_safe"
        # Historial: size↑ agresivo → WR se hunde. Solo +2 y soft-cap 42.
        c["quote_size_shares"] = min(
            SIZE_SOFT_CAP, int(c.get("quote_size_shares", 30)) + 2
        )
        c["lock_profit_usdc"] = round(min(3.0, float(c.get("lock_profit_usdc", 1.5)) + 0.3), 2)
        c["max_take_profit"] = round(min(0.08, float(c.get("max_take_profit", 0.05)) + 0.01), 3)
        c["min_take_profit"] = round(min(0.03, float(c.get("min_take_profit", 0.02)) + 0.002), 3)
        c["max_loss_usdc"] = round(min(3.5, float(c.get("max_loss_usdc", 2.5)) + 0.2), 2)
        minutes = min(12.0, minutes + 1.0)
        hyp = "WR ok → €: +2 size (cap 42), lock↑, TP↑. No pyramid, no size salto."
    elif code == "EUR_OK_WR_FRAGILE":
        method = "protect_wr"
        c["quote_size_shares"] = max(24, int(c.get("quote_size_shares", 30)) - 2)
        c["min_edge"] = round(min(0.045, float(c.get("min_edge", 0.03)) + 0.002), 3)
        c["lock_profit_usdc"] = round(max(1.0, float(c.get("lock_profit_usdc", 1.5))), 2)
        c["max_entry_fills"] = min(4, int(c.get("max_entry_fills") or 4))
        hyp = "Hay € pero WR frágil: −size, edge↑, lock activo, menos entries."
    elif code == "GREEN_STRONG":
        method = "confirm_batch"
        sessions = min(8, sessions + 2)
        minutes = min(12.0, max(minutes, 10.0))
        # No tocar size/riesgo
        hyp = "Confirmar régimen fuerte con más sesiones; params congelados."
    elif code == "GREEN_SOFT":
        method = "nudge_hit"
        # Un solo eje hacia HIT: lock un poco más alto para avg
        c["lock_profit_usdc"] = round(min(2.5, float(c.get("lock_profit_usdc", 1.5)) + 0.4), 2)
        minutes = min(12.0, max(minutes, 10.0))
        hyp = "Verde suave → subir lock para avg € sin tocar size."
    else:
        method = "reanchor_lock"
        # Fallback: volver a DNA lock_green overlays
        lock = _build_family_cfg(FAMILY_SPECS[0])
        for k, v in lock.items():
            if not str(k).startswith("_"):
                c[k] = v
        family = "lock_green"
        minutes = 10.0
        sessions = 6
        hyp = "Fallback: reanclar a familia lock_green (DNA estable)."

    # Evitar repetir exactamente el mismo método+size+edge
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    label = f"{method}_g{gen}_{stamp}"
    if method in methods_tried and code not in ("GREEN_STRONG", "confirm_batch"):
        # Si ya probamos este método, variar el eje secundario de forma determinista
        if code in ("TOXIC_TAIL", "FAT_TAIL", "DEAD_RED"):
            c["min_quote_mid"] = round(min(0.40, float(c.get("min_quote_mid", 0.35)) + 0.02), 2)
            c["max_quote_mid"] = round(max(0.60, float(c.get("max_quote_mid", 0.65)) - 0.02), 2)
            hyp += " (mid más estrecho: método ya visto)."
        elif code == "WR_OK_EUR_LOW":
            c["min_expected_pnl_usdc"] = round(
                min(1.0, float(c.get("min_expected_pnl_usdc", 0.55)) + 0.1), 2
            )
            hyp += " (min_expected_pnl↑: método ya visto)."

    c = _apply_lab_invariants(c)
    _sync_size_caps(c)
    c["_family"] = family
    c["_method"] = method
    c["_sessions"] = sessions
    c["_minutes"] = round(minutes, 1)
    c["_hypothesis"] = hyp
    c["_rationale"] = f"Diagnóstico {code}: {rationale}"
    c["_diagnosis_prev"] = code
    c["demo_label"] = label
    return c


# ---------------------------------------------------------------------------
# Persistencia / email
# ---------------------------------------------------------------------------

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
        f"- family: `{row.get('family')}`",
        f"- method: `{row.get('method')}`",
        f"- category: `{row.get('category')}`",
        f"- diagnosis: `{row.get('diagnosis')}` — {row.get('diagnosis_detail')}",
        f"- hypothesis: {row.get('hypothesis')}",
        f"- rationale: {row.get('rationale')}",
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
    label = str(row.get("label") or "unnamed")
    method = str(row.get("method") or "unknown")
    family = str(row.get("family") or method)
    trial = int(row.get("trial") or 0)
    tag = f"{run_id}::T{trial:02d}::{family}::{method}::{label}"
    cat = str(row.get("category") or categorize(row))
    name = f"[{cat}] {family} · {method}"
    return {
        "tag": tag,
        "name": name,
        "label": label,
        "family": family,
        "method": method,
        "category": cat,
        "diagnosis": row.get("diagnosis"),
        "diagnosis_detail": row.get("diagnosis_detail"),
        "hypothesis": row.get("hypothesis"),
        "rationale": row.get("rationale"),
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
            "min_z": cfg.get("min_z"),
            "min_ev": cfg.get("min_expected_pnl_usdc"),
        },
        # Snapshot para poder REFINE el Top sin perder la DNA exacta
        "cfg": {k: v for k, v in cfg.items() if not str(k).startswith("_")},
    }


def _leaderboard_path() -> Path:
    return OVERNIGHT / "leaderboard.json"


def _upsert_leaderboard(entry: dict) -> list[dict]:
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
            CATEGORY_RANK.get(str(x.get("category") or ""), 0),
            float(x.get("total") or 0),
            float(x.get("wr") or 0),
            float(x.get("avg") or 0),
            -int(x.get("losses") or 0),
            -abs(float(x.get("worst") or 0)),
            int(x.get("traded") or 0),
        )

    ranked = sorted(by_tag.values(), key=sort_key, reverse=True)
    # Bottom 5 for "peor" visibility
    bottom = list(reversed(ranked[-5:])) if ranked else []
    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "count": len(ranked),
        "strategies": ranked,
        "top10": ranked[:10],
        "bottom5": bottom,
        "by_category": {
            cat: [x for x in ranked if x.get("category") == cat]
            for cat in CATEGORY_RANK
        },
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

    meta = {
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "max_trials": MAX_TRIALS,
        "planner": "intelligent_families_v1",
        "random_mutations": False,
        "families": [s["family"] for s in FAMILY_SPECS],
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
        f"Overnight INTELIGENTE started (sin mutaciones random).\n"
        f"run_dir={run_dir}\n"
        f"Familias DNA: {', '.join(meta['families'])}\n"
        f"Luego: diagnóstico → 1 eje / cambio familia → categoría ELITE…REJECT.\n"
        f"HIT: WR>={HIT_WR} avg>={HIT_AVG}€ total>={HIT_TOTAL}€ "
        f"losses<={HIT_MAX_LOSSES} traded>={HIT_MIN_TRADED}\n"
        f"Leaderboard: {OVERNIGHT / 'leaderboard.json'}\n"
    )
    _, start_html = build_simple_banner_email(title=f"START {run_id}", body=start_body)
    send_email(
        subject=f"[poly] START overnight INTELIGENTE {run_id}",
        body_text=start_body,
        body_html=start_html,
    )

    queue = _seed_queue()
    history: list[dict] = []
    best: dict | None = None
    families_tried: set[str] = set()
    methods_tried: set[str] = set()
    cfg = queue[0]
    plans_log: list[dict] = []
    miss_top5_streak = 0
    refine_round = 0
    # Si el primer trial arranca en mercado calmado, no quemar 6×10 min a ciegas:
    # batch_paper_eval corta a las 2 sesiones sin fills (BATCH_STOP_AFTER_STARVE_STREAK).

    for i in range(1, MAX_TRIALS + 1):
        if STOP_FLAG.exists():
            print("STOP_OVERNIGHT flag — exiting", flush=True)
            break

        do_refine = False
        top_entry_for_refine: dict | None = None
        if i == 1:
            cfg = queue[0]
        elif i <= len(queue) and miss_top5_streak == 0:
            # Solo seguir cola de familias si no estamos ya en modo refine
            # y el último no fue STARVED (en ese caso plan_next abre feed)
            last = history[-1] if history else None
            if last and last.get("diagnosis") == "STARVED":
                base_cfg = last.get("_full_cfg") or cfg
                cfg = plan_next(
                    base_cfg=base_cfg,
                    row=last,
                    diagnosis={
                        "code": "STARVED",
                        "detail": str(last.get("diagnosis_detail") or ""),
                    },
                    gen=i,
                    families_tried=families_tried,
                    methods_tried=methods_tried,
                )
            else:
                cfg = queue[i - 1]
        else:
            last = history[-1]
            last_cfg = last.get("_full_cfg") or cfg
            diag = {
                "code": str(last.get("diagnosis") or "DEAD_RED"),
                "detail": str(last.get("diagnosis_detail") or ""),
            }
            best_cat = categorize(best["row"]) if best else "REJECT"
            if best and best_cat in ("ELITE", "PROMISING", "MARGINAL"):
                base_cfg = best["cfg"]
            else:
                base_cfg = last_cfg

            # Top 5 lleno + última estrategia fuera → mejorar el Top
            lb_top: list[dict] = []
            if _leaderboard_path().is_file():
                try:
                    lb_top = list(
                        json.loads(_leaderboard_path().read_text(encoding="utf-8")).get("top10")
                        or []
                    )[:5]
                except Exception:
                    lb_top = []
            if miss_top5_streak >= 1 and len(lb_top) >= 5:
                do_refine = True
                top_entry_for_refine = lb_top[refine_round % min(3, len(lb_top))]
            elif (
                diag["code"] not in ("STARVED", "LOW_FILLS")
                and len(lb_top) >= 5
                and last.get("tag_in_top5") is False
            ):
                do_refine = True
                top_entry_for_refine = lb_top[0]

            cfg = plan_next(
                base_cfg=base_cfg,
                row=last,
                diagnosis=diag,
                gen=i,
                families_tried=families_tried,
                methods_tried=methods_tried,
                refine_top=do_refine,
                top_entry=top_entry_for_refine,
                refine_round=refine_round,
            )
            if do_refine:
                refine_round += 1

        sessions = int(cfg.get("_sessions") or 6)
        minutes = float(cfg.get("_minutes") or 8.0)
        family = str(cfg.get("_family") or cfg.get("_method") or "")
        method = str(cfg.get("_method") or "")
        hypothesis = str(cfg.get("_hypothesis") or "")
        rationale = str(cfg.get("_rationale") or "")
        families_tried.add(family)
        methods_tried.add(method)

        trial_dir = run_dir / f"trial_{i:02d}_{cfg.get('demo_label', 'x')}"
        cfg_path = trial_dir / "config.json"
        trial_dir.mkdir(parents=True, exist_ok=True)
        cfg_disk = {k: v for k, v in cfg.items() if not k.startswith("_")}
        cfg_path.write_text(json.dumps(cfg_disk, indent=2), encoding="utf-8")

        plan_info = {
            "trial": i,
            "family": family,
            "method": method,
            "hypothesis": hypothesis,
            "rationale": rationale,
            "sessions": sessions,
            "minutes": minutes,
            "size": cfg_disk.get("quote_size_shares"),
            "edge": cfg_disk.get("min_edge"),
            "lock": cfg_disk.get("lock_profit_usdc"),
            "max_loss": cfg_disk.get("max_loss_usdc"),
        }
        plans_log.append(plan_info)
        (run_dir / "plans.json").write_text(json.dumps(plans_log, indent=2), encoding="utf-8")
        (trial_dir / "plan.json").write_text(json.dumps(plan_info, indent=2), encoding="utf-8")

        print(
            f"\n######## OVERNIGHT {i}/{MAX_TRIALS} [{family}/{method}] "
            f"{sessions}x{minutes}m ########\n"
            f"HYP: {hypothesis}\nWHY: {rationale}",
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
                body_text=f"Trial {i} failed: {err}\n{trial_dir}\nplan={json.dumps(plan_info)}\n",
            )
            await asyncio.sleep(10)
            continue

        nets = [r["net"] for r in summary.get("results") or []]
        total = round(sum(nets), 2) if nets else 0.0
        row: dict[str, Any] = {
            "trial": i,
            "label": cfg.get("demo_label"),
            "family": family,
            "method": method,
            "hypothesis": hypothesis,
            "rationale": rationale,
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
            "stopped_early_starve": summary.get("stopped_early_starve"),
            "hit": False,
        }
        row["hit"] = _hit(row)
        diag = diagnose(row)
        row["diagnosis"] = diag["code"]
        row["diagnosis_detail"] = diag["detail"]
        row["category"] = categorize(row)
        row["_full_cfg"] = deepcopy(cfg)

        entry = _strategy_record(row, cfg_disk, run_id)
        _write_trial_report(trial_dir, row, cfg_disk, summary)
        (trial_dir / "strategy.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")

        # history sin cfg completo gigante duplicado en JSON principal
        hist_row = {k: v for k, v in row.items() if k != "_full_cfg"}
        history.append({**hist_row, "_full_cfg": row["_full_cfg"]})
        (run_dir / "history.json").write_text(
            json.dumps([{k: v for k, v in h.items() if k != "_full_cfg"} for h in history], indent=2),
            encoding="utf-8",
        )

        print(
            f"-> cat={row['category']} diag={row['diagnosis']} "
            f"WR={100*(row['wr'] or 0):.1f}% avg={row['avg']:+.2f} total={total:+.2f} "
            f"losses={row['losses']} HIT={row['hit']}",
            flush=True,
        )

        top10 = _upsert_leaderboard(entry)
        (run_dir / "top10.json").write_text(json.dumps(top10, indent=2), encoding="utf-8")

        top5_tags = {str(x.get("tag")) for x in top10[:5]}
        in_top5 = entry["tag"] in top5_tags
        hist_row["tag_in_top5"] = in_top5
        if len(top10) >= 5 and not in_top5:
            miss_top5_streak += 1
        else:
            miss_top5_streak = 0
        print(
            f"leaderboard: in_top5={in_top5} miss_streak={miss_top5_streak} "
            f"cat={row['category']}",
            flush=True,
        )

        mail_r = _email_trial(
            hist_row, cfg_disk, run_id, trial_dir, summary=summary, top10=top10
        )
        print(f"mail: ok={mail_r.get('ok')} to={mail_r.get('to')!r}", flush=True)

        sc = _score(hist_row)
        freeze = CFG_DIR / "maker_demo_100_usd_overnight_best.json"
        if best is None or sc > best["score"]:
            best = {"score": sc, "cfg": deepcopy(cfg), "row": hist_row}
            (run_dir / "best.json").write_text(
                json.dumps({"cfg": cfg_disk, "row": hist_row, "entry": entry}, indent=2),
                encoding="utf-8",
            )
            freeze.write_text(json.dumps(cfg_disk, indent=2), encoding="utf-8")
            (LAB / "overnight_best.json").write_text(
                json.dumps(
                    {"cfg": cfg_disk, "row": hist_row, "run_id": run_id, "entry": entry},
                    indent=2,
                ),
                encoding="utf-8",
            )

        if row["hit"]:
            hit_body = (
                f"TARGET HIT en trial {i}.\n"
                f"family={family} method={method}\n"
                f"total={total:+.2f} EUR  WR={100*(row['wr'] or 0):.1f}%\n"
                f"hypothesis: {hypothesis}\n"
                f"best_cfg={freeze}\n\n{json.dumps(hist_row, indent=2)}\n"
            )
            _, _, hit_html = build_trial_email(
                row=hist_row,
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

        await asyncio.sleep(5)

    top10_final: list[dict] = []
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
        "best": {k: v for k, v in (best["row"] if best else {}).items()},
        "top10": top10_final,
        "planner": "intelligent_families_v1",
    }
    (run_dir / "final.json").write_text(json.dumps(fin, indent=2), encoding="utf-8")
    fin_lines = [
        f"FIN overnight INTELIGENTE {run_id}",
        f"trials_done={len(history)}",
        f"best={json.dumps(fin.get('best'), indent=2)}",
        "",
        "=== TOP 10 ===",
    ]
    for j, s in enumerate(top10_final[:10], 1):
        fin_lines.append(
            f"{j}. [{s.get('category')}] {s.get('name')} | "
            f"PnL={s.get('total')} WR={s.get('wr')} | {s.get('hypothesis')}"
        )
    fin_body = "\n".join(fin_lines) + "\n"
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
    print(json.dumps({k: v for k, v in fin.items() if k != "top10"}, indent=2), flush=True)
    return 0 if best and best["row"].get("hit") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
