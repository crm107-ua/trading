#!/usr/bin/env python3
"""
Daily research digest — Temperature Ladder WATCH_ONLY.

  python3 -m polymarket.research.local_lab.research_daily_digest
  python3 -m polymarket.research.local_lab.research_daily_digest --hours 24 --telegram
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.research_telemetry import digest_last_hours, write_evidence_progress

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "vps_runs"


def render_plain(d: dict) -> str:
    ev = d.get("evidence") or {}
    hist = ev.get("historical") or {}
    lines = [
        "DIGEST RESEARCH LADDER (WATCH ONLY)",
        f"ventana {d.get('window_hours')}h",
        f"rounds={d.get('rounds')} edges={d.get('rounds_with_edge')} dna_hits={d.get('dna_hits_logged')}",
        f"near_miss={d.get('near_miss_events')} reasons={d.get('near_miss_reasons')}",
        f"gap_basket avg={d.get('gap_basket_avg')} min={d.get('gap_basket_min')}",
        f"evidence n={hist.get('n')} Wilson={hist.get('wilson95_lower')} "
        f"faltan_deposit={ev.get('n_to_deposit_talk')} faltan_GO={ev.get('n_to_go_micro')}",
        "NO auto-execute · NO depositar por este digest",
    ]
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    import urllib.parse
    import urllib.request

    env: dict[str, str] = {}
    for line in (POLY.parent / ".env").read_text().splitlines() if (POLY.parent / ".env").exists() else []:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    # also try trader root .env via cwd
    for root in (Path("/var/www/html/trader"), POLY.parent):
        p = root / ".env"
        if p.exists():
            for line in p.read_text().splitlines():
                if not line.strip() or line.strip().startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    token = env.get("MANAGER_TELEGRAM_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat = env.get("MANAGER_TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("telegram_skip: missing creds", flush=True)
        return
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        out = json.load(resp)
    print("tg", out.get("ok"), (out.get("result") or {}).get("message_id"), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()

    write_evidence_progress()
    d = digest_last_hours(hours=float(args.hours))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "DAILY_DIGEST.json"
    path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    plain = render_plain(d)
    (OUT / "DAILY_DIGEST.md").write_text(f"# Digest\n\n```\n{plain}\n```\n", encoding="utf-8")
    print(plain, flush=True)
    if args.telegram:
        send_telegram(plain + f"\n{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
