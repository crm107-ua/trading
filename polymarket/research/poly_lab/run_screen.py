#!/usr/bin/env python3
"""Single screen run for #15 — delegates to sim_stale_quote."""

from polymarket.research.poly_lab.sim_stale_quote import run_screen


def main() -> None:
    report = run_screen("20260713_screen")
    print(f"Verdict: {report['verdict']} | binding: {report.get('verdict_binding')}")


if __name__ == "__main__":
    main()
