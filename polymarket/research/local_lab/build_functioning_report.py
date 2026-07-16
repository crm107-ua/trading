#!/usr/bin/env python3
"""Agrega sesiones paper reales del día + probe → informe JSON/MD."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

POLY = Path(__file__).resolve().parents[2]
LAB = POLY / "data_local" / "local_lab"
EDGE = LAB / "maker_edge"
OUT_MD = POLY / "docs" / "INFORME_FUNCIONAMIENTO_TEORIA_MAKER_EDGE.md"
OUT_JSON = LAB / "informe_funcionamiento_latest.json"

# Familias relevantes para la teoría (excluye runs rotos/sintéticos viejos)
FAMILIES = {
    "margin_max_v3": "Hito margen (referencia)",
    "real_sim_oos_v1": "OOS real-sim trial 1",
    "real_sim_g0_140332": "OOS real-sim trial 2/3 (size↑)",
    "risk_pack_v1": "Risk pack (cola↓)",
    "cal_g1_161519": "Calibración mini best",
    "probe_selective": "Probe selectivo",
    "probe_balance": "Probe balance",
    "probe_margin_ref": "Probe margen ref",
}


def _load_sessions() -> list[dict]:
    rows: list[dict] = []
    if not EDGE.exists():
        return rows
    for d in EDGE.iterdir():
        if not d.is_dir():
            continue
        rep = d / "report.json"
        if not rep.exists():
            continue
        try:
            j = json.loads(rep.read_text(encoding="utf-8"))
        except Exception:
            continue
        label = str(j.get("demo_label") or "")
        # normalize probe / cal labels
        key = label
        for fam in FAMILIES:
            if fam in label or label == fam:
                key = fam
                break
        if key not in FAMILIES and not label.startswith("probe_"):
            continue
        rows.append(
            {
                "session_id": d.name,
                "label": label,
                "family": key if key in FAMILIES else label,
                "net": float(j.get("net_session_usdc") or 0),
                "fills": int(j.get("fills") or 0),
                "mtime": rep.stat().st_mtime,
            }
        )
    return rows


def _stats(rows: list[dict]) -> dict:
    traded = [r for r in rows if r["fills"] > 0]
    wins = [r for r in traded if r["net"] > 0]
    losses = [r for r in traded if r["net"] < 0]
    nets = [r["net"] for r in traded]
    return {
        "n_sessions": len(rows),
        "n_traded": len(traded),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins) / len(traded), 4) if traded else None,
        "avg_net": round(sum(nets) / len(nets), 4) if nets else None,
        "total": round(sum(r["net"] for r in rows), 2),
        "worst": min(nets) if nets else None,
        "best": max(nets) if nets else None,
        "sessions": [
            {"id": r["session_id"], "net": r["net"], "fills": r["fills"]} for r in rows
        ],
    }


def main() -> int:
    rows = _load_sessions()
    by_fam: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_fam[r["family"]].append(r)

    probe = {}
    pp = LAB / "multi_real_probe_latest.json"
    if pp.exists():
        probe = json.loads(pp.read_text(encoding="utf-8"))

    cal_hist = []
    ch = LAB / "calibrate_history.json"
    if ch.exists():
        cal_hist = json.loads(ch.read_text(encoding="utf-8"))

    families = {}
    for fam, title in FAMILIES.items():
        if fam in by_fam:
            families[fam] = {"title": title, **_stats(by_fam[fam])}

    # Cross-cutting theory metrics
    all_traded = [r for r in rows if r["fills"] > 0]
    big_loss = [r for r in all_traded if r["net"] <= -8]
    fat_win = [r for r in all_traded if r["net"] >= 20]

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "binding": False,
        "live_onchain": False,
        "families": families,
        "probe": probe,
        "calibrate_history": cal_hist,
        "theory_signals": {
            "fat_tail_losses_n": len(big_loss),
            "fat_tail_losses": big_loss[:12],
            "fat_wins_n": len(fat_win),
            "wr_not_equal_avg": True,
            "note": "WR alto con size bajo ≠ avg alto; size alto sube avg y rompe WR",
        },
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Markdown informe
    lines = [
        "# Informe — Funcionamiento y teoría (maker_edge, paper real-feed)",
        "",
        f"**Fecha:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        "**Ámbito:** Polymarket BTC Up/Down 5m · capital lab 100 USD · **no** on-chain  ",
        "**Binding:** false (lab / simulación; no screen PREREG_16)",
        "",
        "---",
        "",
        "## 1. Teoría del mecanismo",
        "",
        "### 1.1 Edge de maker selectivo",
        "",
        "El bot no “predice” el evento con LLM. Cotiza como **maker** solo cuando el fair value",
        "binomial (log-moneyness + σ) se separa del mid del CLOB por encima de `min_edge`:",
        "",
        "- Mercado **barato** vs fair → bid al touch (comprar Up).",
        "- Mercado **rico** vs fair → ask al touch (vender Up / short).",
        "- Size escala con soft/hard edge (más edge → más size, acotado).",
        "",
        "El PnL paper viene de **fills reales del book** (Binance spot + CLOB WS) y salidas a mid",
        "(TP/stop / fair-fade / flatten de ventana). Sin `paper_touch_fill` ni hazard sintético.",
        "",
        "### 1.2 Por qué WR y avg pelean",
        "",
        "| Palanca | Efecto en WR | Efecto en avg |",
        "|---------|--------------|---------------|",
        "| Subir `min_edge` / bajar entries | ↑ (menos trades tóxicos) | ↓ o flat (menos oportunidad) |",
        "| Subir `quote_size` / `max_size_mult` | ↓ (cola de pérdidas) | ↑ en wins, ↓↓ en losses |",
        "| `max_loss_usdc` + kill sesión | ↑ (corta cola) | tope el downside |",
        "| Anti-racha (size×0.5, pausa) | ↑ estabilidad | reduce recuperación agresiva |",
        "",
        "Evidencia dura del día: OOS trial 1 (size~42) WR **50%** avg **+$15.7**; trial 2 (size↑)",
        "WR **37.5%** avg **−$7.5**. El hito lab margin_max_v3 logró WR **75%** avg **+$15.3**",
        "en 6×3.5 min — reproducible como referencia, no como garantía OOS.",
        "",
        "### 1.3 Hipótesis de trabajo",
        "",
        "1. El edge existe en ventanas cortas cuando fair≠mid y el book no es tóxico.",
        "2. La **cola izquierda** (losses −20…−40) destruye WR al subir size.",
        "3. Confirmar WR≥75% OOS exige selectividad + caps, aceptando avg más bajo que el hito.",
        "4. Sesiones de 1.5–2 min con edge alto pueden dar **0 fills** → no miden WR (ruido).",
        "",
        "---",
        "",
        "## 2. Funcionamiento del sistema (pipeline)",
        "",
        "```",
        "Binance spot WS ──┐",
        "                  ├─→ fair_value(Φ(ln S/K)/(σ√T))",
        "CLOB book/trades ─┘         │",
        "                            ▼",
        "                     maker_edge filter",
        "                            │",
        "                     paper fills + inventory",
        "                            │",
        "              TP/stop/fair-fade/session-kill",
        "                            │",
        "                     report.json / batch WR",
        "```",
        "",
        "- **Daemons:** `daemon_btc_feed` + `daemon_clob_recorder` → `data_local/local_lab/`.",
        "- **Estrategia:** `research/local_lab/strategies.py` → `maker_edge`.",
        "- **Motor paper:** `paper_maker.py` (riesgo: kill, anti-racha, fair_fade).",
        "- **Loops:** calibrate / confirm_wr_fast / multi_real_probe (lab only).",
        "",
        "---",
        "",
        "## 3. Resultados agregados (sesiones con report)",
        "",
    ]

    for fam, block in families.items():
        wr = block.get("wr")
        wr_s = f"{100*wr:.1f}%" if wr is not None else "n/a"
        lines += [
            f"### {block['title']} (`{fam}`)",
            "",
            f"- Sesiones: **{block['n_sessions']}** · con fills: **{block['n_traded']}**",
            f"- WR (traded): **{wr_s}** ({block['wins']}W / {block['losses']}L)",
            f"- Avg net traded: **{block.get('avg_net')}** · Total: **{block.get('total')}**",
            f"- Mejor / peor: **{block.get('best')}** / **{block.get('worst')}**",
            "",
        ]

    if probe.get("variants"):
        lines += ["### Probe multi-config (corrida dedicada)", ""]
        for v in probe["variants"]:
            lines.append(
                f"- **{v['variant']}**: WR={v.get('win_rate')} avg={v.get('avg_net')} "
                f"traded={v.get('traded')} total={v.get('total')} size={v.get('size')} edge={v.get('min_edge')}"
            )
        lines.append("")

    if cal_hist:
        lines += ["### Calibración mini (historial)", ""]
        for h in cal_hist:
            lines.append(
                f"- Round {h.get('round')} `{h.get('label')}`: WR={h.get('wr')} "
                f"avg={h.get('avg_net')} losses={h.get('losses')} fail={h.get('fail_reason')}"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 4. Veredicto de funcionamiento",
        "",
        "| Pregunta | Respuesta |",
        "|----------|-----------|",
        "| ¿El mecanismo genera PnL paper con feeds reales? | **Sí** (hito + OOS trial 1 positivo en total) |",
        "| ¿WR≥75% estable OOS? | **Aún no confirmado** fuera del batch hito; OOS 50% / calibración ~67% best |",
        "| ¿Subir size sube ingresos seguros? | **No** — rompe WR vía cola |",
        "| ¿Listo para live? | **No** — PREREG_16 + sin claves CLOB |",
        "",
        "## 5. Siguiente paso recomendado",
        "",
        "1. Congelar config con WR≥75% en batch ≥4×10 min (promote).",
        "2. Mantener size≤30 y `max_loss_usdc`≤3.5 hasta cola acotada.",
        "3. No relanzar `autonomous_oos_driver` / watchdogs que reinician Trial 1.",
        "4. Fase A WS ≥30d antes de paper firmado / screen.",
        "",
        f"_Artefacto JSON:_ `data_local/local_lab/informe_funcionamiento_latest.json`",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print(f"Wrote {OUT_JSON}")
    print(json.dumps({k: {"wr": v.get("wr"), "avg": v.get("avg_net"), "n": v.get("n_traded")} for k, v in families.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
