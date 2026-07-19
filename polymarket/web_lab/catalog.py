"""Catálogo de metodologías (configs top + leaderboard overnight)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

POLY = Path(__file__).resolve().parents[1]
CFG_DIR = POLY / "config"
LAB = POLY / "data_local" / "local_lab"

# Curadas a mano (mejores conocidas del lab/server)
FEATURED: list[dict[str, Any]] = [
    {
        "id": "t4_exact",
        "name": "T4 cut_tail exact (server +19.98€)",
        "badge": "ELITE",
        "file": "maker_demo_100_usd_server_t4_cut_tail_exact.json",
        "default_sessions": 6,
        "default_minutes": 8.0,
        "blurb": "Ganadora server hoy: WR 66.7%, peor −1.26€. DNA refine_protect_edge.",
        "metrics": {"total": 19.98, "wr": 0.667, "avg": 3.33},
    },
    {
        "id": "t4_risk_up",
        "name": "T4 risk-up + fast-block (local +8.61€)",
        "badge": "PROMISING",
        "file": "maker_demo_100_usd_server_t4_risk_up_fast_block.json",
        "default_sessions": 6,
        "default_minutes": 8.0,
        "blurb": "Más size/lock. En live: banda mid ampliada + lado rich vía Down.",
        "metrics": {"total": 8.61, "wr": 0.5, "avg": 1.44},
    },
    {
        "id": "fuse_v3",
        "name": "Fuse Top2 consistency v3",
        "badge": "MARGINAL",
        "file": "maker_demo_100_usd_fuse_top2_consistency.json",
        "default_sessions": 6,
        "default_minutes": 8.0,
        "blurb": "Fusión #1+#2 overnight. Verde flojo en OOS; mid abierto.",
        "metrics": {"total": 1.7, "wr": 0.333, "avg": 0.28},
    },
    {
        "id": "micro_5",
        "name": "Micro 5€ T4 (live ambos lados)",
        "badge": "MICRO",
        "file": "maker_demo_5_eur_t4_micro_live.json",
        "default_sessions": 4,
        "default_minutes": 5.0,
        "blurb": "T4 micro: mid 0.18–0.84, BUY Up barato + BUY Down si rich. Ideal live corto.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 5.0,
    },
    {
        "id": "micro_strict",
        "name": "Micro live STRICT (Fase D)",
        "badge": "STRICT",
        "file": "maker_demo_micro_live_strict.json",
        "default_sessions": 1,
        "default_minutes": 8.0,
        "blurb": "1 entrada, rich OFF, kill 0.40€/sesión. Solo tras checklist dry + ≥5 pUSD.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 1.2,
    },
    {
        "id": "grind_nim_best",
        "name": "Grind NIM BEST (WR≥75%)",
        "badge": "CHAMP",
        "file": "maker_demo_grind_nim_best.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Campeón selective v2 @10€ feeds reales: WR 100% (5W/0L, +0.86€). min_edge 0.031 / min_z 1.0.",
        "metrics": {"total": 0.86, "wr": 1.0, "avg": 0.172},
        "base_capital": 10.0,
    },
    {
        "id": "grind_nim_selective",
        "name": "Grind NIM Selective (entry bar↑)",
        "badge": "CHAMP",
        "file": "maker_demo_grind_nim_selective.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "DNA del campeón (alias). WR 100% @10€ 6×5 (+0.86). v1 mid-estrecho WR25% rechazada.",
        "metrics": {"total": 0.86, "wr": 1.0, "avg": 0.172},
        "base_capital": 10.0,
    },
    {
        "id": "grind_nim_wr_lock",
        "name": "Grind NIM WR-LOCK (prep inversión)",
        "badge": "LOCK",
        "file": "maker_demo_grind_nim_wr_lock.json",
        "default_sessions": 4,
        "default_minutes": 3.0,
        "blurb": "Fusión entry+stops duros. Objetivo WR≥70% @5/10€ antes de capital real.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "pulse_gate",
        "name": "PulseGate (latencia+régimen)",
        "badge": "PIONEER",
        "file": "maker_demo_pulse_gate.json",
        "default_sessions": 4,
        "default_minutes": 3.0,
        "blurb": "Nuevo DNA: strike fresco + momentum BTC + blackout settlement + imbalance. No fade mid informado.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "fusion_router",
        "name": "Fusion Router (pulse+follow+edge)",
        "badge": "ROUTER",
        "file": "maker_demo_fusion_router.json",
        "default_sessions": 4,
        "default_minutes": 4.0,
        "blurb": "RegimeRouter: latencia → follow mid+spot → edge selectivo. Caza WR≥70%.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "fusion_follow_heavy",
        "name": "Fusion Follow-Heavy (champ candidate)",
        "badge": "CHAMP",
        "file": "maker_demo_fusion_follow_heavy.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Follow-only (pulse OFF), fair-edge + soft-cut duro. @5 PASS; @10 retighten.",
        "metrics": {"total": 0.34, "wr": 1.0, "avg": 0.17},
        "base_capital": 10.0,
    },
    {
        "id": "fusion_follow_flow",
        "name": "Fusion Follow-Flow (anti-starve)",
        "badge": "HUNT",
        "file": "maker_demo_fusion_follow_flow.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Follow-only. v5 @5 WR100% (+0.40). @10 en hunt v6.",
        "metrics": {"total": 0.40, "wr": 1.0, "avg": 0.057},
        "base_capital": 10.0,
    },
    {
        "id": "promo_flow_c5",
        "name": "Promo Flow @5 (locked champ)",
        "badge": "CHAMP",
        "file": "maker_demo_promo_flow_c5.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "DNA v5 locked: WR100% 7W +0.40 @5€. Paralelo multi-línea.",
        "metrics": {"total": 0.40, "wr": 1.0, "avg": 0.057},
        "base_capital": 5.0,
    },
    {
        "id": "selective_mom",
        "name": "Selective + Momentum align",
        "badge": "CHAMP",
        "file": "maker_demo_selective_mom.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Edge selectivo solo con roll BTC. Scout @10€ WR 75% (3W/1L +0.37, traded=4).",
        "metrics": {"total": 0.37, "wr": 0.75, "avg": 0.0925},
        "base_capital": 10.0,
    },
    {
        "id": "follow_gate",
        "name": "FollowGate (anti-fade)",
        "badge": "PIONEER",
        "file": "maker_demo_follow_gate.json",
        "default_sessions": 4,
        "default_minutes": 4.0,
        "blurb": "Unirse al mid informado solo si BTC confirma. Opuesto al fade tóxico.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "grind_nim_best_c5",
        "name": "Grind NIM BEST @5€ (reval)",
        "badge": "CHAMP",
        "file": "maker_demo_grind_nim_best_c5.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Snapshot escalado reval 2026-07-18: WR 100% paper (5W/0L, +1.25€).",
        "metrics": {"total": 1.25, "wr": 1.0, "avg": 0.25},
        "base_capital": 5.0,
    },
    {
        "id": "grind_nim_best_c15",
        "name": "Grind NIM BEST @15€ (reval)",
        "badge": "CHAMP",
        "file": "maker_demo_grind_nim_best_c15.json",
        "default_sessions": 6,
        "default_minutes": 5.0,
        "blurb": "Snapshot escalado reval 2026-07-18: WR 100% paper (5W/0L, +2.04€).",
        "metrics": {"total": 2.04, "wr": 1.0, "avg": 0.408},
        "base_capital": 15.0,
    },
    {
        "id": "grind_nim_flow",
        "name": "Grind NIM flow (tradeable)",
        "badge": "GRIND",
        "file": "maker_demo_grind_nim_flow.json",
        "default_sessions": 6,
        "default_minutes": 6.0,
        "blurb": "Entrada abierta (mid/time) + lock temprano NIM. Diseñado para fills reales a 5/10/15€.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "grind_nim_v1",
        "name": "Grind NIM v1 (wins pequeños)",
        "badge": "GRIND",
        "file": "maker_demo_grind_nim_v1.json",
        "default_sessions": 6,
        "default_minutes": 6.0,
        "blurb": "WR-first + NVIDIA hybrid: mid 0.28–0.72, lock temprano, 1 entrada. 5/10/15€.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "grind_nim_v2",
        "name": "Grind NIM v2 selectivo",
        "badge": "GRIND",
        "file": "maker_demo_grind_nim_v2.json",
        "default_sessions": 6,
        "default_minutes": 6.0,
        "blurb": "Más filtro (mid 0.30–0.70). Prioriza no perder / acumular céntimos.",
        "metrics": {"total": None, "wr": None, "avg": None},
        "base_capital": 10.0,
    },
    {
        "id": "lock_v7",
        "name": "Lock green v7",
        "badge": "SEED",
        "file": "maker_demo_100_usd_margin_v7_lock.json",
        "default_sessions": 6,
        "default_minutes": 10.0,
        "blurb": "Lock +1.5€, no pyramid, mid band. Semilla overnight.",
        "metrics": {"total": 15.66, "wr": 1.0, "avg": 2.61},
    },
    {
        "id": "hito_margin",
        "name": "Hito margin_max_v3",
        "badge": "HITO",
        "file": "maker_demo_100_usd_margin_best.json",
        "default_sessions": 6,
        "default_minutes": 8.0,
        "blurb": "Hito histórico WR~75% lab (con guardrails en overnight).",
        "metrics": {"total": None, "wr": 0.75, "avg": 15.0},
    },
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _leaderboard_paths() -> list[Path]:
    return [
        LAB / "overnight" / "leaderboard.json",
        LAB / "overnight_leaderboard_server.json",
    ]


def scale_cfg_to_capital(cfg: dict, capital: float, *, base_capital: float = 100.0) -> dict:
    """Escala size / notional / stops al capital elegido; edge/mid se mantienen."""
    c = deepcopy(cfg)
    capital = max(0.05, float(capital))
    base = max(0.05, float(base_capital))
    scale = capital / base
    c["initial_capital_usdc"] = round(capital, 4)
    c["currency_label"] = "EUR"

    def sc_int(key: str, lo: int = 1, hi: int = 80) -> None:
        if key in c and c[key] is not None:
            c[key] = int(max(lo, min(hi, round(float(c[key]) * scale))))

    def sc_float(key: str, lo: float = 0.05, hi: float = 55.0) -> None:
        if key in c and c[key] is not None:
            c[key] = round(max(lo, min(hi, float(c[key]) * scale)), 2)

    sc_int("quote_size_shares", 1, 80)
    sc_int("max_quote_size_shares", 1, 80)
    sc_int("max_inventory_shares", 1, 80)
    sc_float("max_notional_per_side_usdc", 0.3, 80.0)
    sc_float("max_inventory_usdc", 0.5, 80.0)
    sc_float("max_loss_usdc", 0.1, 20.0)
    sc_float("session_kill_net_usdc", 0.2, 30.0)
    sc_float("lock_profit_usdc", 0.05, 10.0)
    sc_float("min_expected_pnl_usdc", 0.05, 5.0)
    # Caps coherentes
    size = int(c.get("quote_size_shares") or 1)
    cap = max(size, int(c.get("max_quote_size_shares") or size))
    c["max_quote_size_shares"] = cap
    c["max_inventory_shares"] = max(cap, int(c.get("max_inventory_shares") or cap))
    c["max_inventory_usdc"] = float(max(c.get("max_inventory_usdc") or 0, cap))
    c["paper_touch_fill_every_n"] = 0
    c["paper_pnl_mode"] = ""
    c["no_pyramid_entries"] = True
    c["fair_fade_exit"] = True
    return c


def apply_live_clob_floors(cfg: dict) -> dict:
    """CLOB floors + boost de oportunidad (más fills sin abrir lotería extrema)."""
    c = deepcopy(cfg)
    min_shares = 5
    size = max(min_shares, int(c.get("quote_size_shares") or min_shares))
    c["quote_size_shares"] = size
    c["max_quote_size_shares"] = max(size, int(c.get("max_quote_size_shares") or size))
    c["max_inventory_shares"] = max(size, int(c.get("max_inventory_shares") or size))
    # Notional ≤ capital de sesión (antes forzaba ≥5€ y petaba con ~2 pUSD)
    capital = max(1.05, float(c.get("initial_capital_usdc") or 2.0))
    c["max_notional_per_side_usdc"] = round(min(capital * 0.98, 5.0), 2)
    c["max_inventory_usdc"] = round(min(max(capital, c["max_notional_per_side_usdc"]), 5.0), 2)
    # Con size 5 el hurdle EV antiguo bloqueaba casi todo
    c["min_expected_pnl_usdc"] = min(float(c.get("min_expected_pnl_usdc") or 0.05), 0.05)
    label = str(c.get("demo_label") or "")
    preserve = bool(c.get("preserve_selectivity")) or label.startswith("grind")
    if not preserve:
        # Más oportunidades vs paper-100: banda mid más ancha, edge/z algo más bajos
        c["min_quote_mid"] = min(float(c.get("min_quote_mid") or 0.24), 0.18)
        c["max_quote_mid"] = max(float(c.get("max_quote_mid") or 0.76), 0.84)
        c["min_edge"] = min(float(c.get("min_edge") or 0.034), 0.026)
        c["soft_edge"] = min(float(c.get("soft_edge") or 0.048), 0.038)
        c["min_z"] = min(float(c.get("min_z") or 1.0), 0.8)
        c["quote_time_min_s"] = min(float(c.get("quote_time_min_s") or 40), 25)
        c["quote_time_max_s"] = max(float(c.get("quote_time_max_s") or 280), 310)
        c["cooldown_after_fill_s"] = min(float(c.get("cooldown_after_fill_s") or 5), 3)
    # No forzar +entradas en configs strict/grind (max_entry_fills=1)
    if int(c.get("max_entry_fills") or 2) >= 2:
        c["max_entry_fills"] = max(int(c.get("max_entry_fills") or 2), 3)
    # Live micro: TP/SL. Fusion/follow WR-first: NUNCA subir suelos (anula soft-cut).
    wr_first = any(
        x in label.lower()
        for x in ("fusion", "follow", "flow", "pulse", "promo_flow")
    )
    if preserve and wr_first:
        c["lock_profit_usdc"] = min(float(c.get("lock_profit_usdc") or 0.08), 0.25)
        c["max_loss_usdc"] = min(float(c.get("max_loss_usdc") or 0.08), 0.28)
        c["flatten_before_window_s"] = max(
            float(c.get("flatten_before_window_s") or 45), 70
        )
    elif preserve:
        c["lock_profit_usdc"] = max(
            0.06, min(float(c.get("lock_profit_usdc") or 0.12), 0.25)
        )
        c["max_loss_usdc"] = max(
            0.06, min(float(c.get("max_loss_usdc") or 0.12), 0.28)
        )
        c["flatten_before_window_s"] = max(
            float(c.get("flatten_before_window_s") or 45), 70
        )
    else:
        c["lock_profit_usdc"] = max(
            0.15, min(float(c.get("lock_profit_usdc") or 0.2), 0.35)
        )
        c["max_loss_usdc"] = max(
            0.30, min(float(c.get("max_loss_usdc") or 0.5), 0.55)
        )
        c["flatten_before_window_s"] = max(
            float(c.get("flatten_before_window_s") or 45), 55
        )
    # Strict configs set allow_rich_side_live=false; default True for legacy micros
    if "allow_rich_side_live" not in c:
        c["allow_rich_side_live"] = True
    c["session_kill_net_usdc"] = min(
        float(c.get("session_kill_net_usdc") or 0.40), 0.40
    )
    return c


def list_strategies() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for f in FEATURED:
        path = CFG_DIR / f["file"]
        if not path.exists():
            continue
        cfg = _load_json(path)
        items.append(
            {
                **f,
                "source": "featured",
                "base_capital": float(f.get("base_capital") or cfg.get("initial_capital_usdc") or 100),
                "params_preview": {
                    "size": cfg.get("quote_size_shares"),
                    "edge": cfg.get("min_edge"),
                    "lock": cfg.get("lock_profit_usdc"),
                    "max_loss": cfg.get("max_loss_usdc"),
                    "mid": f"{cfg.get('min_quote_mid')}-{cfg.get('max_quote_mid')}",
                },
            }
        )

    # Leaderboard overnight (top 8) si existe
    seen_files = {x["file"] for x in items}
    for lb_path in _leaderboard_paths():
        if not lb_path.is_file():
            continue
        try:
            raw = json.loads(lb_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for i, s in enumerate((raw.get("top10") or raw.get("strategies") or [])[:8], 1):
            cfg = s.get("cfg")
            if not isinstance(cfg, dict) or not cfg.get("quote_size_shares"):
                continue
            sid = f"lb_{i}_{s.get('method') or 'x'}"
            # Persist cfg snapshot under web_lab cache
            cache = LAB / "web_lab_cfg_cache"
            cache.mkdir(parents=True, exist_ok=True)
            fname = f"{sid}.json"
            fpath = cache / fname
            if not fpath.exists():
                fpath.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            rel = f"../data_local/local_lab/web_lab_cfg_cache/{fname}"
            # Use absolute via special marker
            items.append(
                {
                    "id": sid,
                    "name": f"LB#{i} {s.get('name') or s.get('label')}",
                    "badge": s.get("category") or "LB",
                    "file": str(fpath),  # absolute path ok
                    "default_sessions": int(s.get("sessions") or 6),
                    "default_minutes": float(s.get("minutes") or 8),
                    "blurb": (s.get("hypothesis") or "")[:180],
                    "metrics": {
                        "total": s.get("total"),
                        "wr": s.get("wr"),
                        "avg": s.get("avg"),
                    },
                    "source": "leaderboard",
                    "base_capital": float(cfg.get("initial_capital_usdc") or 100),
                    "params_preview": s.get("params") or {},
                    "_abs_cfg": str(fpath),
                }
            )
        break  # first leaderboard found

    # Dedup by id
    by_id: dict[str, dict] = {}
    for it in items:
        by_id[it["id"]] = it
    return list(by_id.values())


def resolve_strategy(strategy_id: str) -> dict[str, Any]:
    for s in list_strategies():
        if s["id"] == strategy_id:
            return s
    raise KeyError(f"strategy not found: {strategy_id}")


def load_scaled_config(strategy_id: str, capital: float) -> tuple[dict, dict]:
    meta = resolve_strategy(strategy_id)
    path = Path(meta.get("_abs_cfg") or (CFG_DIR / meta["file"]))
    if not path.is_file():
        # try relative from POLY
        alt = POLY / meta["file"]
        path = alt if alt.is_file() else path
    cfg = _load_json(path)
    base = float(meta.get("base_capital") or cfg.get("initial_capital_usdc") or 100)
    scaled = scale_cfg_to_capital(cfg, capital, base_capital=base)
    scaled["demo_label"] = f"web_{strategy_id}_{int(capital)}"
    return scaled, meta
