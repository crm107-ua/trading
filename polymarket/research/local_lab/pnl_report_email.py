#!/usr/bin/env python3
"""Informe HTML de PnL live → email (SMTP .env).

    python -m polymarket.research.local_lab.pnl_report_email
    python -m polymarket.research.local_lab.pnl_report_email --force
"""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.notify.mailer import send_email

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
LAB = POLY / "data_local" / "local_lab"
DAY_PNL = LAB / "live_day_pnl.json"
REAL_DIR = LAB / "real_micro25"
HEARTBEAT = LAB / "desk_forever_heartbeat.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _snap_balance() -> float | None:
    try:
        from polymarket.src.execution.clob_live import ClobLiveClient

        cli = ClobLiveClient()
        cli.connect()
        return float(cli.balance_collateral_usdc())
    except Exception:
        return None


def collect_snapshot() -> dict[str, Any]:
    day = _load_json(DAY_PNL)
    latest = _load_json(REAL_DIR / "real_latest.json")
    hb = _load_json(HEARTBEAT)
    bal = _snap_balance()
    sessions = []
    if REAL_DIR.is_dir():
        files = sorted(REAL_DIR.glob("real_*.json"), key=lambda p: p.stat().st_mtime)
        for p in files[-12:]:
            if p.name == "real_latest.json":
                continue
            d = _load_json(p)
            if not d:
                continue
            rep = d.get("report") or {}
            sessions.append(
                {
                    "sid": d.get("sid") or p.stem,
                    "net": rep.get("net_session_usdc"),
                    "fills": rep.get("fills"),
                    "ok": d.get("ok"),
                    "delta": d.get("balance_delta"),
                    "cfg": d.get("config"),
                }
            )
    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "balance_pusd": bal,
        "day_pnl": day,
        "latest": latest,
        "heartbeat": hb,
        "recent_sessions": sessions,
        "armed": os.getenv("POLY_LIVE_ARMED"),
        "dry_run": os.getenv("POLY_LIVE_DRY_RUN"),
        "config": os.getenv("POLY_LIVE_CONFIG")
        or "maker_demo_promo_pulse_micro5_scalp.json",
    }


def build_html(snap: dict[str, Any]) -> tuple[str, str, str]:
    bal = snap.get("balance_pusd")
    day = snap.get("day_pnl") or {}
    day_pnl = float(day.get("pnl") or 0)
    day_n = int(day.get("sessions") or 0)
    day_date = str(day.get("date") or "—")
    latest = snap.get("latest") or {}
    rep = latest.get("report") or {}
    last_net = rep.get("net_session_usdc")
    last_fills = rep.get("fills")
    hb = snap.get("heartbeat") or {}
    loops = hb.get("loops")
    status = str(hb.get("status") or "unknown")
    pnl_color = "#0f766e" if day_pnl >= 0 else "#b91c1c"
    bal_s = f"{bal:.4f}" if isinstance(bal, (int, float)) else "n/d"
    rows = ""
    for s in reversed(list(snap.get("recent_sessions") or [])):
        net = s.get("net")
        net_s = f"{float(net):+.2f}" if isinstance(net, (int, float)) else "—"
        ok = "OK" if s.get("ok") else "WARN"
        rows += (
            f"<tr>"
            f"<td style='padding:10px 12px;border-bottom:1px solid #e5e7eb;font-family:ui-monospace,monospace;font-size:12px'>"
            f"{html.escape(str(s.get('sid') or ''))}</td>"
            f"<td style='padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:600;"
            f"color:{'#0f766e' if isinstance(net,(int,float)) and net>=0 else '#b91c1c'}'>{net_s}</td>"
            f"<td style='padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:center'>{s.get('fills')}</td>"
            f"<td style='padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:center'>{ok}</td>"
            f"</tr>"
        )
    if not rows:
        rows = (
            "<tr><td colspan='4' style='padding:16px;color:#6b7280;text-align:center'>"
            "Sin sesiones REAL recientes</td></tr>"
        )

    subject = (
        f"[Poly Desk] día {day_pnl:+.2f} USDC · saldo {bal_s} · {day_date}"
    )
    text = (
        f"Informe Poly Desk Forever\n"
        f"UTC: {snap.get('ts_utc')}\n"
        f"Saldo: {bal_s} pUSD\n"
        f"PnL día ({day_date}): {day_pnl:+.4f} USDC ({day_n} sesiones)\n"
        f"Última sesión net={last_net} fills={last_fills}\n"
        f"Heartbeat: status={status} loops={loops}\n"
        f"Flags: ARMED={snap.get('armed')} DRY={snap.get('dry_run')}\n"
    )
    body = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b1220;font-family:Georgia,'Times New Roman',serif;color:#111827">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1220;padding:28px 12px">
    <tr><td align="center">
      <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#f8fafc;border-radius:18px;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.35)">
        <tr>
          <td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 55%,#0f766e 100%);padding:28px 32px;color:#f8fafc">
            <div style="font-size:12px;letter-spacing:.18em;text-transform:uppercase;opacity:.75;font-family:system-ui,sans-serif">Polymarket Desk</div>
            <div style="font-size:28px;line-height:1.15;margin-top:8px;font-weight:700">Informe de resultados</div>
            <div style="margin-top:10px;font-size:14px;opacity:.85;font-family:system-ui,sans-serif">{html.escape(str(snap.get('ts_utc')))}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px 8px">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
              <tr>
                <td width="50%" style="padding:0 8px 16px 0;vertical-align:top">
                  <div style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px 20px">
                    <div style="font-family:system-ui,sans-serif;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#6b7280">Saldo CLOB</div>
                    <div style="font-size:30px;margin-top:6px;font-weight:700;font-family:system-ui,sans-serif">{bal_s}</div>
                    <div style="font-family:system-ui,sans-serif;font-size:13px;color:#6b7280;margin-top:4px">pUSD disponible</div>
                  </div>
                </td>
                <td width="50%" style="padding:0 0 16px 8px;vertical-align:top">
                  <div style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px 20px">
                    <div style="font-family:system-ui,sans-serif;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#6b7280">PnL del día</div>
                    <div style="font-size:30px;margin-top:6px;font-weight:700;font-family:system-ui,sans-serif;color:{pnl_color}">{day_pnl:+.2f}</div>
                    <div style="font-family:system-ui,sans-serif;font-size:13px;color:#6b7280;margin-top:4px">{day_n} sesiones · {html.escape(day_date)}</div>
                  </div>
                </td>
              </tr>
            </table>
            <div style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px 20px;margin-bottom:18px;font-family:system-ui,sans-serif;font-size:14px;line-height:1.55;color:#374151">
              <strong style="color:#111827">Estado desk:</strong> {html.escape(status)}
              &nbsp;·&nbsp; loops={html.escape(str(loops))}
              &nbsp;·&nbsp; ARMED={html.escape(str(snap.get('armed')))}
              &nbsp;·&nbsp; DRY={html.escape(str(snap.get('dry_run')))}<br>
              <strong style="color:#111827">Última sesión:</strong>
              net={html.escape(str(last_net))} · fills={html.escape(str(last_fills))}
              · cfg={html.escape(str(snap.get('config')))}
            </div>
            <div style="font-family:system-ui,sans-serif;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#6b7280;margin:8px 0 10px">Últimas sesiones REAL</div>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;font-family:system-ui,sans-serif;font-size:13px">
              <tr style="background:#f3f4f6;color:#4b5563;text-align:left">
                <th style="padding:10px 12px">Sesión</th>
                <th style="padding:10px 12px;text-align:right">Net</th>
                <th style="padding:10px 12px;text-align:center">Fills</th>
                <th style="padding:10px 12px;text-align:center">OK</th>
              </tr>
              {rows}
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:8px 32px 28px;font-family:system-ui,sans-serif;font-size:12px;color:#9ca3af;line-height:1.5">
            Informe automático cada 3 horas desde <code>poly-desk-forever</code> en el servidor.
            Para detener el trading: <code>pm2 stop poly-desk-forever</code>.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return subject, text, body


def send_report(*, force: bool = False) -> dict[str, Any]:
    snap = collect_snapshot()
    subject, text, body = build_html(snap)
    if not force and os.getenv("POLY_DESK_REPORT_DISABLE", "0").strip() == "1":
        return {"ok": False, "error": "POLY_DESK_REPORT_DISABLE=1", "snap": snap}
    r = send_email(subject=subject, body_text=text, body_html=body)
    r["snap_keys"] = list(snap.keys())
    r["day_pnl"] = (snap.get("day_pnl") or {}).get("pnl")
    r["balance"] = snap.get("balance_pusd")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    r = send_report(force=bool(args.force))
    print(json.dumps({k: r.get(k) for k in ("ok", "to", "error", "day_pnl", "balance")}, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
