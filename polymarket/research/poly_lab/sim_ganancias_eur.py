#!/usr/bin/env python3
"""
CUARENTENA — proyecciones EUR prohibidas antes del screen fase C.

Mismo patrón que sim_stale_quote.run_screen() / sim_maker_quote.run_screen():
sin report.json de fase C con veredicto PASA vinculante, este módulo no produce
cifras de ganancia.

La única simulación de PnL válida es research/output/poly_16/<run_id>/report.json
tras 30d fase A + 14d paper + replay honesto (pre-reg #16).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_GLOB = ROOT / "research" / "output" / "poly_16"
QUARANTINE_NOTE = ROOT / "research" / "output" / "_cuarentena" / "README.md"


def _find_phase_c_pasa_report() -> Path | None:
    if not PHASE_C_GLOB.exists():
        return None
    for report_path in sorted(PHASE_C_GLOB.glob("*/report.json"), reverse=True):
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            data.get("hypothesis") == 16
            and data.get("verdict") == "PASA"
            and data.get("verdict_binding") is True
        ):
            return report_path
    return None


def run_simulation(
    *,
    phase_c_report: Path | None = None,
    allow_without_pasa: bool = False,
) -> dict[str, Any]:
    """
    Refuse to emit profit projections unless phase C screen PASA exists.

    allow_without_pasa: solo tests internos — nunca para registry ni informes.
    """
    if allow_without_pasa:
        return {
            "verdict": "DEV_ONLY",
            "verdict_binding": False,
            "reason": "allow_without_pasa=True — no usar",
        }

    report_path = phase_c_report or _find_phase_c_pasa_report()
    if report_path is None:
        out = {
            "verdict": "PROHIBIDO",
            "verdict_binding": False,
            "hypothesis": 16,
            "reason": (
                "Sin screen fase C PASA vinculante. "
                "Prohibido proyectar ganancias antes del replay honesto (30d + paper 14d)."
            ),
            "required_input": "research/output/poly_16/<run_id>/report.json con verdict=PASA",
            "quarantine": str(QUARANTINE_NOTE.parent),
            "protocol": "polymarket/docs/PREREG_16_POLY_MAKER_STALE.md",
            "answer_to_cuanto_gano": "No se sabe; el protocolo existe para averiguarlo sin autoengaño.",
        }
        return out

    data = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "verdict": "DELEGATE_TO_PHASE_C",
        "verdict_binding": True,
        "source_report": str(report_path),
        "pnl": data.get("account_return") or data.get("pnl"),
        "note": "Leer report.json completo — única fuente de cifras vinculantes",
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Guard — ganancias EUR solo tras screen fase C PASA",
    )
    p.add_argument(
        "--phase-c-report",
        type=Path,
        default=None,
        help="Ruta explícita a report.json PASA (opcional)",
    )
    args = p.parse_args()
    result = run_simulation(phase_c_report=args.phase_c_report)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("verdict") in ("PROHIBIDO", "DEV_ONLY"):
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
