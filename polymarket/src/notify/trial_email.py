#!/usr/bin/env python3
"""Plantillas HTML mobile-first para informes overnight."""

from __future__ import annotations

from html import escape
from typing import Any


def _f(v: Any, nd: int = 2) -> str:
    try:
        return f"{float(v):+.{nd}f}"
    except Exception:
        return "—"


def _pct(v: Any) -> str:
    try:
        return f"{100.0 * float(v):.1f}%"
    except Exception:
        return "—"


def build_trial_email(
    *,
    row: dict[str, Any],
    cfg: dict[str, Any],
    run_id: str,
    trial_dir: str,
    summary: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Returns (subject, text, html)."""
    total = float(row.get("total") or 0)
    avg = float(row.get("avg") or 0)
    wr = float(row.get("wr") or 0)
    saldo = 100.0 + total
    wins = int(row.get("wins") or 0)
    losses = int(row.get("losses") or 0)
    traded = int(row.get("traded") or 0)
    sessions = int(row.get("sessions") or 0)
    minutes = row.get("minutes")
    nets = list(row.get("nets") or [])
    hit = bool(row.get("hit"))
    badge = "HIT OBJETIVO" if hit else ("EN VERDE" if total > 0 else ("EN ROJO" if total < 0 else "FLAT"))
    badge_bg = "#0f766e" if hit or total > 0 else ("#b91c1c" if total < 0 else "#57534e")

    subject = (
        f"[poly] T{row.get('trial')} {badge} · "
        f"{_f(total)}€ · WR {_pct(wr)} · saldo {saldo:.2f}€"
    )

    # Plain text fallback
    lines = [
        f"POLY OVERNIGHT — Trial {row.get('trial')} — {badge}",
        f"Run: {run_id}",
        f"Label: {row.get('label')} | Method: {row.get('method')}",
        f"Batch: {sessions} x {minutes} min",
        "",
        f"SALDO: {saldo:.2f} EUR  (base 100 + {_f(total)})",
        f"PnL total: {_f(total)} EUR | avg {_f(avg)} EUR",
        f"WR: {_pct(wr)}  ({wins}W / {losses}L)  traded={traded}/{sessions}",
        f"Mejor sesión: {_f(row.get('best_sess'))} | Peor: {_f(row.get('worst'))}",
        f"Streak kill: {row.get('stopped_early_streak')}",
        "",
        "SESIONES:",
    ]
    for i, n in enumerate(nets, 1):
        tag = "WIN" if n > 0 else ("LOSS" if n < 0 else "FLAT")
        lines.append(f"  S{i}: {tag} {_f(n)} EUR")
    lines += [
        "",
        "PARAMS:",
        f"  size={cfg.get('quote_size_shares')} mult={cfg.get('max_size_mult')} "
        f"cap={cfg.get('max_quote_size_shares')}",
        f"  edge={cfg.get('min_edge')} soft={cfg.get('soft_edge')} hard={cfg.get('hard_edge')}",
        f"  max_loss={cfg.get('max_loss_usdc')} kill={cfg.get('session_kill_net_usdc')} "
        f"lock={cfg.get('lock_profit_usdc')}",
        f"  mid=[{cfg.get('min_quote_mid')}-{cfg.get('max_quote_mid')}] "
        f"entries={cfg.get('max_entry_fills')} TP={cfg.get('min_take_profit')}-{cfg.get('max_take_profit')}",
        f"  no_pyramid={cfg.get('no_pyramid_entries')} fair_fade={cfg.get('fair_fade_exit')}",
        "",
        f"Informe disco: {trial_dir}",
        "Paper lab — no on-chain.",
    ]
    if summary:
        lines.append(f"stopped_early_streak(summary)={summary.get('stopped_early_streak')}")
    body_text = "\n".join(lines)

    # Session cards HTML
    sess_blocks: list[str] = []
    running = 100.0
    for i, n in enumerate(nets, 1):
        running += float(n)
        if n > 0:
            col, tag = "#047857", "WIN"
        elif n < 0:
            col, tag = "#b91c1c", "LOSS"
        else:
            col, tag = "#78716c", "FLAT"
        sess_blocks.append(
            f"""
            <tr>
              <td style="padding:12px 10px;border-bottom:1px solid #e7e5e4;font-size:15px;">
                <strong>S{i}</strong>
                <span style="display:inline-block;margin-left:8px;padding:2px 8px;border-radius:999px;
                  background:{col};color:#fff;font-size:12px;font-weight:700;">{escape(tag)}</span>
              </td>
              <td style="padding:12px 10px;border-bottom:1px solid #e7e5e4;text-align:right;
                font-size:16px;font-weight:700;color:{col};">{escape(_f(n))} €</td>
              <td style="padding:12px 10px;border-bottom:1px solid #e7e5e4;text-align:right;
                font-size:13px;color:#57534e;">{escape(f"{running:.2f}")} €</td>
            </tr>
            """
        )
    if not sess_blocks:
        sess_blocks.append(
            '<tr><td colspan="3" style="padding:14px;color:#78716c;">Sin sesiones cerradas</td></tr>'
        )

    html = f"""\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f4;font-family:-apple-system,BlinkMacSystemFont,
  'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1c1917;">
  <div style="max-width:560px;margin:0 auto;padding:12px;">
    <div style="background:#1c1917;color:#fafaf9;border-radius:16px;padding:18px 16px;margin-bottom:12px;">
      <div style="font-size:12px;letter-spacing:0.06em;text-transform:uppercase;opacity:0.75;">
        Poly Overnight · Paper
      </div>
      <div style="font-size:22px;font-weight:800;margin-top:6px;line-height:1.25;">
        Trial {escape(str(row.get('trial')))} · {escape(str(row.get('method') or ''))}
      </div>
      <div style="margin-top:10px;">
        <span style="display:inline-block;padding:6px 12px;border-radius:999px;background:{badge_bg};
          color:#fff;font-size:13px;font-weight:700;">{escape(badge)}</span>
      </div>
    </div>

    <div style="background:#fff;border-radius:16px;padding:16px;margin-bottom:12px;
      box-shadow:0 1px 2px rgba(0,0,0,0.04);">
      <div style="font-size:13px;color:#78716c;margin-bottom:4px;">Saldo paper</div>
      <div style="font-size:36px;font-weight:800;line-height:1.1;color:#1c1917;">
        {saldo:.2f} <span style="font-size:18px;font-weight:600;">EUR</span>
      </div>
      <div style="margin-top:6px;font-size:15px;color:{'#047857' if total>=0 else '#b91c1c'};font-weight:700;">
        PnL {_f(total)} EUR · base 100
      </div>
    </div>

    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px;">
      <tr>
        <td width="50%" style="padding:0 4px 8px 0;vertical-align:top;">
          <div style="background:#fff;border-radius:14px;padding:14px;">
            <div style="font-size:12px;color:#78716c;">Win rate</div>
            <div style="font-size:24px;font-weight:800;">{escape(_pct(wr))}</div>
            <div style="font-size:13px;color:#57534e;">{wins}W / {losses}L</div>
          </div>
        </td>
        <td width="50%" style="padding:0 0 8px 4px;vertical-align:top;">
          <div style="background:#fff;border-radius:14px;padding:14px;">
            <div style="font-size:12px;color:#78716c;">Avg / sesión</div>
            <div style="font-size:24px;font-weight:800;color:{'#047857' if avg>=0 else '#b91c1c'};">
              {escape(_f(avg))}
            </div>
            <div style="font-size:13px;color:#57534e;">EUR</div>
          </div>
        </td>
      </tr>
      <tr>
        <td width="50%" style="padding:0 4px 0 0;vertical-align:top;">
          <div style="background:#fff;border-radius:14px;padding:14px;">
            <div style="font-size:12px;color:#78716c;">Mejor</div>
            <div style="font-size:20px;font-weight:800;color:#047857;">{escape(_f(row.get('best_sess')))}</div>
          </div>
        </td>
        <td width="50%" style="padding:0 0 0 4px;vertical-align:top;">
          <div style="background:#fff;border-radius:14px;padding:14px;">
            <div style="font-size:12px;color:#78716c;">Peor</div>
            <div style="font-size:20px;font-weight:800;color:#b91c1c;">{escape(_f(row.get('worst')))}</div>
          </div>
        </td>
      </tr>
    </table>

    <div style="background:#fff;border-radius:16px;padding:8px 6px 4px;margin-bottom:12px;">
      <div style="padding:8px 10px 4px;font-size:13px;font-weight:700;color:#44403c;">
        Sesiones ({escape(str(sessions))}×{escape(str(minutes))} min) · traded {traded}
      </div>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding:4px 10px;font-size:11px;color:#a8a29e;">Sesión</td>
          <td style="padding:4px 10px;font-size:11px;color:#a8a29e;text-align:right;">Net</td>
          <td style="padding:4px 10px;font-size:11px;color:#a8a29e;text-align:right;">Saldo</td>
        </tr>
        {''.join(sess_blocks)}
      </table>
    </div>

    <div style="background:#fff;border-radius:16px;padding:16px;margin-bottom:12px;">
      <div style="font-size:13px;font-weight:700;margin-bottom:10px;color:#44403c;">Parámetros</div>
      <div style="font-size:14px;line-height:1.55;color:#292524;">
        <div><strong>Size</strong> {escape(str(cfg.get('quote_size_shares')))}
          · mult {escape(str(cfg.get('max_size_mult')))}
          · cap {escape(str(cfg.get('max_quote_size_shares')))}</div>
        <div><strong>Edge</strong> {escape(str(cfg.get('min_edge')))}
          / soft {escape(str(cfg.get('soft_edge')))}
          / hard {escape(str(cfg.get('hard_edge')))}</div>
        <div><strong>Riesgo</strong> max_loss {escape(str(cfg.get('max_loss_usdc')))}
          · kill {escape(str(cfg.get('session_kill_net_usdc')))}
          · lock {escape(str(cfg.get('lock_profit_usdc')))} €</div>
        <div><strong>Mid</strong> {escape(str(cfg.get('min_quote_mid')))}–{escape(str(cfg.get('max_quote_mid')))}
          · entries {escape(str(cfg.get('max_entry_fills')))}</div>
        <div><strong>TP</strong> {escape(str(cfg.get('min_take_profit')))}–{escape(str(cfg.get('max_take_profit')))}
          · pyramid off={escape(str(cfg.get('no_pyramid_entries')))}</div>
        <div><strong>Label</strong> {escape(str(row.get('label')))}</div>
      </div>
    </div>

    <div style="padding:8px 4px 20px;font-size:12px;color:#78716c;line-height:1.45;">
      Run <strong>{escape(run_id)}</strong><br/>
      Disco: {escape(trial_dir)}<br/>
      Lab paper · no on-chain · no garantía de ingresos reales
    </div>
  </div>
</body>
</html>
"""
    return subject, body_text, html


def build_simple_banner_email(*, title: str, body: str) -> tuple[str, str]:
    """HTML simple mobile para START/FIN."""
    html = f"""\
<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/></head>
<body style="margin:0;background:#f5f5f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:16px;">
    <div style="background:#1c1917;color:#fff;border-radius:16px;padding:18px;">
      <div style="font-size:20px;font-weight:800;">{escape(title)}</div>
    </div>
    <div style="background:#fff;border-radius:16px;padding:16px;margin-top:12px;
      font-size:15px;line-height:1.5;white-space:pre-wrap;">{escape(body)}</div>
  </div>
</body></html>
"""
    return body, html
