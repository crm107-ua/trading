#!/usr/bin/env python3
"""Plantillas HTML mobile-first para informes overnight (+ Top 10)."""

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


_CAT_COLORS = {
    "ELITE": "#0f766e",
    "PROMISING": "#047857",
    "MARGINAL": "#a16207",
    "WEAK": "#b45309",
    "STARVED": "#57534e",
    "REJECT": "#b91c1c",
}


def strategy_card_html(rank: int, s: dict[str, Any]) -> str:
    total = float(s.get("total") or 0)
    col = "#047857" if total > 0 else ("#b91c1c" if total < 0 else "#57534e")
    medal = {1: "1", 2: "2", 3: "3"}.get(rank, str(rank))
    p = s.get("params") or {}
    name = escape(str(s.get("name") or s.get("label") or "estrategia"))
    method = escape(str(s.get("method") or "—"))
    family = escape(str(s.get("family") or "—"))
    cat = str(s.get("category") or "—")
    cat_bg = _CAT_COLORS.get(cat, "#57534e")
    tag = escape(str(s.get("tag") or ""))
    hyp = escape(str(s.get("hypothesis") or "")[:220])
    return f"""
    <div style="border:1px solid #e7e5e4;border-radius:14px;padding:12px;margin:0 0 10px 0;background:#fafaf9;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <span style="display:inline-block;min-width:28px;height:28px;line-height:28px;text-align:center;
          border-radius:999px;background:#1c1917;color:#fff;font-size:13px;font-weight:800;">{medal}</span>
        <div style="font-size:15px;font-weight:800;color:#1c1917;line-height:1.25;">{name}</div>
      </div>
      <div style="margin-bottom:8px;">
        <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{cat_bg};
          color:#fff;font-size:11px;font-weight:700;">{escape(cat)}</span>
      </div>
      <div style="font-size:12px;color:#78716c;margin-bottom:8px;">
        <strong>ID</strong> {tag}<br/>
        <strong>Familia</strong> {family}
        · <strong>Método</strong> {method}
        · Trial {escape(str(s.get('trial')))}
        · {escape(str(s.get('sessions')))}×{escape(str(s.get('minutes')))} min
      </div>
      <div style="font-size:14px;font-weight:700;color:{col};margin-bottom:6px;">
        PnL {_f(total)} € · WR {_pct(s.get('wr'))} · avg {_f(s.get('avg'))} €
      </div>
      <div style="font-size:12px;color:#44403c;line-height:1.45;">
        {int(s.get('wins') or 0)}W / {int(s.get('losses') or 0)}L
        · traded {escape(str(s.get('traded')))}
        · best {_f(s.get('best_sess'))} / worst {_f(s.get('worst'))}<br/>
        <strong>Params</strong>
        size={escape(str(p.get('size')))}
        mult={escape(str(p.get('mult')))}
        cap={escape(str(p.get('cap')))}
        edge={escape(str(p.get('edge')))}
        max_loss={escape(str(p.get('max_loss')))}
        kill={escape(str(p.get('kill')))}
        lock={escape(str(p.get('lock')))}
        mid={escape(str(p.get('mid_lo')))}–{escape(str(p.get('mid_hi')))}
        TP={escape(str(p.get('tp_min')))}–{escape(str(p.get('tp_max')))}
        entries={escape(str(p.get('entries')))}
      </div>
      <div style="font-size:11px;color:#57534e;margin-top:6px;line-height:1.4;">
        <strong>Hipótesis</strong> {hyp or "—"}
      </div>
      <div style="font-size:11px;color:#a8a29e;margin-top:4px;word-break:break-all;">
        nets={escape(str(s.get('nets')))}
      </div>
    </div>
    """


def build_trial_email(
    *,
    row: dict[str, Any],
    cfg: dict[str, Any],
    run_id: str,
    trial_dir: str,
    summary: dict[str, Any] | None = None,
    top10: list[dict[str, Any]] | None = None,
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
    top10 = list(top10 or [])

    category = str(row.get("category") or "—")
    subject = (
        f"[poly] T{row.get('trial')} [{category}] {badge} · "
        f"{_f(total)}€ · WR {_pct(wr)} · saldo {saldo:.2f}€"
    )

    lines = [
        f"POLY OVERNIGHT — Trial {row.get('trial')} — {badge}",
        f"Run: {run_id}",
        f"Familia: {row.get('family')} | Método: {row.get('method')} | Cat: {category}",
        f"Diagnóstico: {row.get('diagnosis')} — {row.get('diagnosis_detail')}",
        f"Hipótesis: {row.get('hypothesis')}",
        f"Por qué: {row.get('rationale')}",
        f"Batch: {sessions} x {minutes} min",
        "",
        f"SALDO: {saldo:.2f} EUR  (base 100 + {_f(total)})",
        f"PnL total: {_f(total)} EUR | avg {_f(avg)} EUR",
        f"WR: {_pct(wr)}  ({wins}W / {losses}L)  traded={traded}/{sessions}",
        f"Mejor sesión: {_f(row.get('best_sess'))} | Peor: {_f(row.get('worst'))}",
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
        f"  edge={cfg.get('min_edge')} max_loss={cfg.get('max_loss_usdc')} "
        f"lock={cfg.get('lock_profit_usdc')}",
        "",
        "=== TOP 10 ESTRATEGIAS (acumulado) ===",
    ]
    for i, s in enumerate(top10[:10], 1):
        p = s.get("params") or {}
        lines.append(
            f"{i}. [{s.get('tag')}] {s.get('name')} | method={s.get('method')} | "
            f"PnL={_f(s.get('total'))} WR={_pct(s.get('wr'))} avg={_f(s.get('avg'))} | "
            f"size={p.get('size')} edge={p.get('edge')} max_loss={p.get('max_loss')} lock={p.get('lock')}"
        )
    lines += ["", f"Informe disco: {trial_dir}", "Paper lab — no on-chain."]
    body_text = "\n".join(lines)

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

    top_html = "".join(strategy_card_html(i, s) for i, s in enumerate(top10[:10], 1))
    if not top_html:
        top_html = '<div style="padding:12px;color:#78716c;font-size:14px;">Aún no hay ranking.</div>'

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
        Trial {escape(str(row.get('trial')))} · {escape(str(row.get('family') or row.get('method') or ''))}
      </div>
      <div style="font-size:13px;opacity:0.85;margin-top:4px;">
        {escape(str(row.get('method') or ''))} · {escape(str(row.get('label') or ''))}
      </div>
      <div style="margin-top:10px;">
        <span style="display:inline-block;padding:6px 12px;border-radius:999px;background:{badge_bg};
          color:#fff;font-size:13px;font-weight:700;">{escape(badge)}</span>
        <span style="display:inline-block;margin-left:6px;padding:6px 12px;border-radius:999px;
          background:{_CAT_COLORS.get(category, '#57534e')};color:#fff;font-size:13px;font-weight:700;">
          {escape(category)}</span>
      </div>
    </div>

    <div style="background:#fff;border-radius:16px;padding:16px;margin-bottom:12px;">
      <div style="font-size:13px;font-weight:700;color:#44403c;margin-bottom:8px;">Hipótesis de esta prueba</div>
      <div style="font-size:14px;line-height:1.45;color:#292524;margin-bottom:10px;">
        {escape(str(row.get('hypothesis') or '—'))}
      </div>
      <div style="font-size:12px;color:#78716c;line-height:1.4;">
        <strong>Diagnóstico</strong> {escape(str(row.get('diagnosis') or '—'))}:
        {escape(str(row.get('diagnosis_detail') or ''))}<br/>
        <strong>Por qué se eligió</strong> {escape(str(row.get('rationale') or '—'))}
      </div>
    </div>

    <div style="background:#fff;border-radius:16px;padding:16px;margin-bottom:12px;">
      <div style="font-size:13px;color:#78716c;margin-bottom:4px;">Saldo paper (esta prueba)</div>
      <div style="font-size:36px;font-weight:800;line-height:1.1;">{saldo:.2f}
        <span style="font-size:18px;font-weight:600;">EUR</span></div>
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
              {escape(_f(avg))}</div>
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
      <div style="font-size:13px;font-weight:700;margin-bottom:10px;color:#44403c;">Parámetros de esta prueba</div>
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
        <div><strong>TP</strong> {escape(str(cfg.get('min_take_profit')))}–{escape(str(cfg.get('max_take_profit')))}</div>
      </div>
    </div>

    <div style="background:#fff;border-radius:16px;padding:16px;margin-bottom:12px;">
      <div style="font-size:16px;font-weight:800;margin-bottom:4px;color:#1c1917;">Top 10 estrategias</div>
      <div style="font-size:12px;color:#78716c;margin-bottom:12px;line-height:1.4;">
        Ranking acumulado (todas las pruebas). Se actualiza en cada email aunque pares el proceso.
        Orden: HIT → PnL total → WR → avg → menos losses.
      </div>
      {top_html}
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
