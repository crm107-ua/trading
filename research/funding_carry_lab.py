#!/usr/bin/env python3
"""
#14 Funding Rate Carry — simulador delta-neutral dual-leg (research).

Congelado: docs/PREREG_14_FUNDING_CARRY.md

Modelado obligatorio v1:
  1. Funding con signo real cada 8h (short paga si rate < 0).
  2. Basis: precios spot y perp (mark) separados en entrada/salida.
  3. Fricción: 4 ejecuciones × (fee + slippage) por ciclo.
  4. Margen perp isolated 1×: notional/leg = slot_capital/2; retorno sobre cuenta 10k.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import compute_metrics  # noqa: E402

# --- Congelado (PREREG) ---
WHITELIST = ("BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT")
INITIAL_CAPITAL = 10_000.0
MAX_POSITIONS = 2
ENTRY_ANN_PCT = 0.12
ENTRY_STREAK = 3
EXIT_ANN_PCT = 0.06
MAX_HOLD_DAYS = 21
LIQ_MIN_QUOTE_VOL_30D = 50_000_000.0

FEE_SPOT = 0.001
FEE_PERP = 0.0005
SLIP_SPOT = 0.001
SLIP_PERP = 0.001

START = pd.Timestamp("2021-01-01", tz="UTC")
HALVES = {
  "2021-23": (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2023-12-31", tz="UTC")),
  "2024-26": (pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2099-01-01", tz="UTC")),
}

FUNDING_DIR = ROOT / "research" / "data_local" / "funding"
SPOT_DIR = ROOT / "research" / "data_local" / "binance"
MARK_DIR = ROOT / "research" / "data_local" / "mark_1h"
OUTPUT_BASE = ROOT / "research" / "output" / "funding_carry_14"

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
MARK_KLINES_URL = "https://fapi.binance.com/fapi/v1/markPriceKlines"
SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"


@dataclass(frozen=True)
class CostModel:
  fee_spot: float = FEE_SPOT
  fee_perp: float = FEE_PERP
  slip_spot: float = SLIP_SPOT
  slip_perp: float = SLIP_PERP

  def open_spot_cost(self, notional: float) -> tuple[float, float, float]:
    """Returns (cash_out, fee_usdt, slip_usdt)."""
    fee = notional * self.fee_spot
    slip = notional * self.slip_spot
    return notional + fee + slip, fee, slip

  def close_spot_proceeds(self, notional_at_mark: float) -> tuple[float, float, float]:
    fee = notional_at_mark * self.fee_spot
    slip = notional_at_mark * self.slip_spot
    return notional_at_mark - fee - slip, fee, slip

  def open_perp_margin(self, notional: float) -> tuple[float, float, float]:
    fee = notional * self.fee_perp
    slip = notional * self.slip_perp
    return notional + fee + slip, fee, slip

  def close_perp_release(self, notional_at_mark: float) -> tuple[float, float, float]:
    fee = notional_at_mark * self.fee_perp
    slip = notional_at_mark * self.slip_perp
    return notional_at_mark - fee - slip, fee, slip

  def friction_per_cycle(self, notional: float) -> float:
    """4 ejecuciones: fees + slippage en apertura y cierre de ambas patas."""
    return 2 * notional * (self.fee_spot + self.slip_spot + self.fee_perp + self.slip_perp)


@dataclass
class Position:
  pair: str
  entry_time: pd.Timestamp
  notional: float
  spot_qty: float
  spot_entry_px: float
  perp_entry_px: float
  margin_locked: float
  funding_settled: float = 0.0


@dataclass
class PnLComponents:
  funding_signed: float = 0.0
  basis: float = 0.0
  fees: float = 0.0
  slippage: float = 0.0
  cycles_closed: int = 0
  by_pair: dict[str, dict[str, float]] = field(default_factory=dict)

  def add_pair(self, pair: str, key: str, val: float) -> None:
    self.by_pair.setdefault(pair, {})
    self.by_pair[pair][key] = self.by_pair[pair].get(key, 0.0) + val

  @property
  def friction_total(self) -> float:
    return self.fees + self.slippage

  @property
  def net_total(self) -> float:
    return self.funding_signed + self.basis - self.friction_total

  def to_dict(self) -> dict:
    return {
      "funding_signed_usdt": self.funding_signed,
      "basis_usdt": self.basis,
      "fees_usdt": self.fees,
      "slippage_usdt": self.slippage,
      "friction_total_usdt": self.friction_total,
      "net_usdt": self.net_total,
      "cycles_closed": self.cycles_closed,
      "by_pair": self.by_pair,
    }


def _asset(pair: str) -> str:
  return pair.split("/")[0]


def _symbol(pair: str) -> str:
  return _asset(pair) + "USDT"


def annualized(rate_8h: float) -> float:
  return float(rate_8h) * 3.0 * 365.0


def _fetch_paginated_json(
  client: httpx.Client, url: str, params: dict, *, time_key: str, start_ms: int
) -> list[dict]:
  rows: list[dict] = []
  cursor = start_ms
  while True:
    p = {**params, "startTime": cursor, "limit": 1000}
    resp = client.get(url, params=p)
    if resp.status_code == 400:
      return rows
    resp.raise_for_status()
    batch = resp.json()
    if not batch:
      break
    if isinstance(batch[0], list):
      # klines format
      for row in batch:
        rows.append({"t": int(row[0]), "close": float(row[4])})
    else:
      rows.extend(batch)
    if isinstance(batch[0], list):
      last = int(batch[-1][0])
    else:
      last = int(batch[-1][time_key])
    nxt = last + 1
    if nxt <= cursor or len(batch) < 1000:
      break
    cursor = nxt
    time.sleep(0.1)
  return rows


def ensure_funding(pair: str, client: httpx.Client) -> pd.DataFrame:
  FUNDING_DIR.mkdir(parents=True, exist_ok=True)
  path = FUNDING_DIR / f"{pair.replace('/', '_')}-funding.feather"
  if path.is_file():
    df = pd.read_feather(path)
    if len(df) > 100:
      return df
  start_ms = int(pd.Timestamp("2019-09-01", tz="UTC").timestamp() * 1000)
  rows = _fetch_paginated_json(
    client, FUNDING_URL, {"symbol": _symbol(pair)}, time_key="fundingTime", start_ms=start_ms
  )
  if not rows:
    raise RuntimeError(f"sin funding para {pair}")
  df = pd.DataFrame(rows)
  out = pd.DataFrame(
    {
      "funding_time": pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True),
      "funding_rate": df["fundingRate"].astype(float),
    }
  ).drop_duplicates(subset=["funding_time"]).sort_values("funding_time")
  out.to_feather(path)
  return out


def ensure_hourly_spot(pair: str, client: httpx.Client) -> pd.Series:
  SPOT_DIR.mkdir(parents=True, exist_ok=True)
  path = SPOT_DIR / f"{pair.replace('/', '_')}-1h.feather"
  if path.is_file():
    df = pd.read_feather(path)
    if len(df) > 500:
      s = df.set_index(pd.to_datetime(df["date"], utc=True))["close"].sort_index()
      return s
  start_ms = int(START.timestamp() * 1000)
  rows = _fetch_paginated_json(
    client,
    SPOT_KLINES_URL,
    {"symbol": _symbol(pair), "interval": "1h"},
    time_key="t",
    start_ms=start_ms,
  )
  if not rows:
    raise RuntimeError(f"sin spot 1h para {pair}")
  df = pd.DataFrame(rows)
  out = pd.DataFrame(
    {
      "date": pd.to_datetime(df["t"], unit="ms", utc=True),
      "close": df["close"],
    }
  )
  out.to_feather(path)
  return out.set_index("date")["close"].sort_index()


def ensure_hourly_mark(pair: str, client: httpx.Client) -> pd.Series:
  MARK_DIR.mkdir(parents=True, exist_ok=True)
  path = MARK_DIR / f"{pair.replace('/', '_')}-mark-1h.feather"
  if path.is_file():
    df = pd.read_feather(path)
    if len(df) > 500:
      s = df.set_index(pd.to_datetime(df["date"], utc=True))["close"].sort_index()
      return s
  start_ms = int(START.timestamp() * 1000)
  rows = _fetch_paginated_json(
    client,
    MARK_KLINES_URL,
    {"symbol": _symbol(pair), "interval": "1h"},
    time_key="t",
    start_ms=start_ms,
  )
  if not rows:
    raise RuntimeError(f"sin mark 1h para {pair}")
  df = pd.DataFrame(rows)
  out = pd.DataFrame(
    {
      "date": pd.to_datetime(df["t"], unit="ms", utc=True),
      "close": df["close"],
    }
  )
  out.to_feather(path)
  return out.set_index("date")["close"].sort_index()


def load_spot_1d_quote_vol(pair: str, client: httpx.Client) -> pd.Series:
  path = SPOT_DIR / f"{pair.replace('/', '_')}-1d.feather"
  if not path.is_file():
    start_ms = int(START.timestamp() * 1000)
    all_rows: list = []
    cursor = start_ms
    while True:
      resp = client.get(
        SPOT_KLINES_URL,
        params={"symbol": _symbol(pair), "interval": "1d", "startTime": cursor, "limit": 1000},
      )
      resp.raise_for_status()
      batch = resp.json()
      if not batch:
        break
      all_rows.extend(batch)
      nxt = int(batch[-1][0]) + 86_400_000
      if nxt <= cursor or len(batch) < 1000:
        break
      cursor = nxt
      time.sleep(0.1)
    out = pd.DataFrame(
      {
        "date": pd.to_datetime([int(r[0]) for r in all_rows], unit="ms", utc=True),
        "close": [float(r[4]) for r in all_rows],
        "quote_volume": [float(r[7]) for r in all_rows],
      }
    )
    out.to_feather(path)
  df = pd.read_feather(path)
  if "quote_volume" not in df.columns:
    df["quote_volume"] = df["volume"].astype(float) * df["close"].astype(float)
  return df.set_index(pd.to_datetime(df["date"], utc=True))["quote_volume"].sort_index()


def price_at_or_before(series: pd.Series, ts: pd.Timestamp) -> float:
  sub = series.loc[:ts]
  if sub.empty:
    raise KeyError(f"sin precio <= {ts}")
  return float(sub.iloc[-1])


def build_entry_signal(funding: pd.DataFrame) -> pd.Series:
  fdf = funding.set_index("funding_time")
  ann = fdf["funding_rate"].map(annualized)
  hot = ann > ENTRY_ANN_PCT
  streak = hot.astype(int).rolling(ENTRY_STREAK, min_periods=ENTRY_STREAK).sum() >= ENTRY_STREAK
  return streak.fillna(False)


def build_exit_signal(funding: pd.DataFrame) -> pd.Series:
  fdf = funding.set_index("funding_time")
  ann = fdf["funding_rate"].map(annualized)
  return (ann < EXIT_ANN_PCT).fillna(False)


def slot_notional_per_leg(free_equity: float, open_count: int) -> float:
  """
  Margen isolated 1×: cada posición consume 2× notional (spot cash + perp margin).
  Con MAX_POSITIONS slots, notional_leg = equity / (2 * MAX_POSITIONS).
  """
  slots_left = max(1, MAX_POSITIONS - open_count)
  deployable = free_equity * (MAX_POSITIONS - open_count) / MAX_POSITIONS
  slot_budget = deployable / slots_left if slots_left else 0.0
  return max(0.0, slot_budget / 2.0)


def simulate(
  *,
  pairs: tuple[str, ...] = WHITELIST,
  start: pd.Timestamp = START,
  costs: CostModel = CostModel(),
) -> tuple[pd.Series, PnLComponents, list[dict]]:
  with httpx.Client(timeout=60.0) as client:
    funding_dfs: dict[str, pd.DataFrame] = {}
    spot_1h: dict[str, pd.Series] = {}
    mark_1h: dict[str, pd.Series] = {}
    liq_1d: dict[str, pd.Series] = {}
    entry_sig: dict[str, pd.Series] = {}
    exit_sig: dict[str, pd.Series] = {}

    for pair in pairs:
      print(f"Cargando {pair}...", flush=True)
      fdf = ensure_funding(pair, client)
      fdf = fdf[fdf["funding_time"] >= start].copy()
      funding_dfs[pair] = fdf.set_index("funding_time")
      spot_1h[pair] = ensure_hourly_spot(pair, client)
      mark_1h[pair] = ensure_hourly_mark(pair, client)
      liq_1d[pair] = load_spot_1d_quote_vol(pair, client)
      entry_sig[pair] = build_entry_signal(fdf)
      exit_sig[pair] = build_exit_signal(fdf)

  all_times = sorted(set().union(*[set(df.index) for df in funding_dfs.values()]))

  cash = INITIAL_CAPITAL
  positions: dict[str, Position] = {}
  pnl = PnLComponents()
  equity_rows: list[tuple[pd.Timestamp, float]] = []
  trade_log: list[dict] = []

  def mark_equity(ts: pd.Timestamp) -> float:
    eq = cash
    for pos in positions.values():
      sp = price_at_or_before(spot_1h[pos.pair], ts)
      mp = price_at_or_before(mark_1h[pos.pair], ts)
      spot_val = pos.spot_qty * sp
      perp_unreal = pos.notional * (pos.perp_entry_px - mp) / pos.perp_entry_px
      eq += spot_val + pos.margin_locked + perp_unreal
    return eq

  def liq_ok(pair: str, ts: pd.Timestamp) -> bool:
    qv = liq_1d[pair].loc[:ts]
    if len(qv) < 30:
      return False
    return float(qv.tail(30).median()) >= LIQ_MIN_QUOTE_VOL_30D

  for ts in all_times:
    # 1) settle funding on open positions (signed)
    for pair, pos in list(positions.items()):
      if ts not in funding_dfs[pair].index:
        continue
      rate = float(funding_dfs[pair].loc[ts, "funding_rate"])
      flow = pos.notional * rate  # short: + when rate>0, - when rate<0
      cash += flow
      pos.funding_settled += flow
      pnl.funding_signed += flow
      pnl.add_pair(pair, "funding_signed", flow)

    # 2) exits
    for pair, pos in list(positions.items()):
      if ts not in funding_dfs[pair].index:
        continue
      days_held = (ts - pos.entry_time).total_seconds() / 86_400.0
      should_exit = bool(exit_sig[pair].loc[ts]) or days_held >= MAX_HOLD_DAYS
      if not should_exit:
        continue

      spot_px = price_at_or_before(spot_1h[pair], ts)
      perp_px = price_at_or_before(mark_1h[pair], ts)
      perp_exit_notional = pos.notional * perp_px / pos.perp_entry_px

      spot_mark_val = pos.spot_qty * spot_px
      spot_proceeds, fee_s, slip_s = costs.close_spot_proceeds(spot_mark_val)
      cash += spot_proceeds
      pnl.fees += fee_s
      pnl.slippage += slip_s
      pnl.add_pair(pair, "fees", fee_s)
      pnl.add_pair(pair, "slippage", slip_s)

      spot_leg = pos.spot_qty * (spot_px - pos.spot_entry_px)
      perp_leg = pos.notional * (pos.perp_entry_px - perp_px) / pos.perp_entry_px
      basis_realized = spot_leg + perp_leg
      pnl.basis += basis_realized
      pnl.add_pair(pair, "basis", basis_realized)

      _, fee_p, slip_p = costs.close_perp_release(perp_exit_notional)
      perp_cash = pos.margin_locked + perp_leg - fee_p - slip_p
      cash += perp_cash
      pnl.fees += fee_p
      pnl.slippage += slip_p
      pnl.add_pair(pair, "fees", fee_p)
      pnl.add_pair(pair, "slippage", slip_p)

      pnl.cycles_closed += 1
      trade_log.append(
        {
          "pair": pair,
          "entry_time": str(pos.entry_time),
          "exit_time": str(ts),
          "days_held": days_held,
          "notional_leg": pos.notional,
          "funding_settled": pos.funding_settled,
          "basis_realized": basis_realized,
          "friction_cycle": costs.friction_per_cycle(pos.notional),
        }
      )
      del positions[pair]

    # 3) entries
    if len(positions) < MAX_POSITIONS:
      eq = mark_equity(ts)
      candidates: list[tuple[float, str]] = []
      for pair in pairs:
        if pair in positions:
          continue
        if ts not in funding_dfs[pair].index:
          continue
        if not bool(entry_sig[pair].loc[ts]):
          continue
        if not liq_ok(pair, ts):
          continue
        ann = annualized(float(funding_dfs[pair].loc[ts, "funding_rate"]))
        candidates.append((ann, pair))
      candidates.sort(reverse=True)
      for _, pair in candidates:
        if len(positions) >= MAX_POSITIONS:
          break
        notional = slot_notional_per_leg(eq, len(positions))
        if notional < 50:
          continue
        spot_px = price_at_or_before(spot_1h[pair], ts)
        perp_px = price_at_or_before(mark_1h[pair], ts)
        spot_entry = spot_px * (1.0 + costs.slip_spot)
        perp_entry = perp_px * (1.0 - costs.slip_perp)

        spot_out, fee_s, slip_s = costs.open_spot_cost(notional)
        perp_lock, fee_p, slip_p = costs.open_perp_margin(notional)
        total_need = spot_out + perp_lock
        if cash < total_need:
          continue

        cash -= total_need
        pnl.fees += fee_s + fee_p
        pnl.slippage += slip_s + slip_p
        pnl.add_pair(pair, "fees", fee_s + fee_p)
        pnl.add_pair(pair, "slippage", slip_s + slip_p)

        spot_qty = notional / spot_entry
        positions[pair] = Position(
          pair=pair,
          entry_time=ts,
          notional=notional,
          spot_qty=spot_qty,
          spot_entry_px=spot_entry,
          perp_entry_px=perp_entry,
          margin_locked=perp_lock,
        )
        trade_log.append(
          {
            "pair": pair,
            "entry_time": str(ts),
            "notional_leg": notional,
            "spot_entry_px": spot_entry,
            "perp_entry_px": perp_entry,
            "basis_at_entry": perp_entry - spot_entry,
            "event": "open",
          }
        )

    equity_rows.append((ts, mark_equity(ts)))

  equity = pd.Series(
    [e for _, e in equity_rows],
    index=pd.DatetimeIndex([t for t, _ in equity_rows], tz="UTC"),
    name="equity",
  )
  return equity, pnl, trade_log


def daily_equity_returns(equity: pd.Series) -> pd.Series:
  daily = equity.resample("1D").last().ffill()
  return np.log(daily / daily.shift(1)).dropna()


def slice_equity(equity: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
  return equity.loc[start:end]


def evaluate_screen(equity: pd.Series, pnl: PnLComponents, trade_log: list[dict]) -> dict:
  closed = [t for t in trade_log if "exit_time" in t]
  metrics_full = compute_metrics(daily_equity_returns(equity))
  half_results: dict[str, dict] = {}
  for name, (a, b) in HALVES.items():
    sub = slice_equity(equity, a, b)
    if len(sub) < 2:
      half_results[name] = {"pnl_net_usdt": 0.0, "sharpe": 0.0}
      continue
    rets = daily_equity_returns(sub)
    m = compute_metrics(rets)
    half_results[name] = {
      "equity_start": float(sub.iloc[0]),
      "equity_end": float(sub.iloc[-1]),
      "pnl_net_usdt": float(sub.iloc[-1] - sub.iloc[0]),
      "sharpe": m.sharpe,
      "max_drawdown": m.max_drawdown,
    }

  d1_fail = pnl.funding_signed < pnl.friction_total
  gates = {
    "net_pnl_positive": pnl.net_total > 0,
    "d1_carry_ge_friction": not d1_fail,
    "cycles_ge_20": pnl.cycles_closed >= 20,
    "half_2021_23_positive": half_results.get("2021-23", {}).get("pnl_net_usdt", 0) > 0,
    "half_2024_26_positive": half_results.get("2024-26", {}).get("pnl_net_usdt", 0) > 0,
    "max_dd_lt_30pct": metrics_full.max_drawdown > -0.30,
  }
  passes = all(gates.values())

  # concentration D-3 preview on net by pair
  pair_net: dict[str, float] = {}
  for pair, comp in pnl.by_pair.items():
    f = comp.get("funding_signed", 0.0)
    b = comp.get("basis", 0.0)
    fr = comp.get("fees", 0.0) + comp.get("slippage", 0.0)
    pair_net[pair] = f + b - fr
  total_net = sum(pair_net.values()) or 1e-9
  conc = {p: v / total_net for p, v in pair_net.items()}
  max_conc = max(conc.values()) if conc else 0.0
  d3_fail = max_conc > 0.40

  if d1_fail:
    verdict = "MUERTA"
    death = "D-1"
  elif d3_fail:
    verdict = "MUERTA"
    death = "D-3"
  elif not passes:
    verdict = "DESCARTADA"
    death = "D-5"
  else:
    verdict = "PASA_SCREEN"
    death = None

  return {
    "verdict": verdict,
    "death_condition": death,
    "passes_screen": passes and not d1_fail and not d3_fail,
    "gates": gates,
    "components": pnl.to_dict(),
    "account": {
      "initial_usdt": INITIAL_CAPITAL,
      "final_equity_usdt": float(equity.iloc[-1]),
      "return_on_account_pct": (float(equity.iloc[-1]) / INITIAL_CAPITAL - 1.0) * 100.0,
      "cagr": metrics_full.cagr,
      "sharpe": metrics_full.sharpe,
      "max_drawdown": metrics_full.max_drawdown,
    },
    "halves": half_results,
    "concentration_by_pair": conc,
    "max_concentration": max_conc,
    "d3_concentration_fail": d3_fail,
    "cycles_closed": pnl.cycles_closed,
    "friction_per_cycle_nominal_pct": costs_pct_per_cycle(),
    "trades_sample": closed[:5],
    "trades_total": len(closed),
  }


def costs_pct_per_cycle() -> float:
  c = CostModel()
  n = 2500.0  # ejemplo notional leg con 10k / 2 slots / 2 patas
  return c.friction_per_cycle(n) / n * 100.0


def run_screen(run_id: str | None = None) -> Path:
  run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  out_dir = OUTPUT_BASE / run_id
  out_dir.mkdir(parents=True, exist_ok=True)

  equity, pnl, trade_log = simulate()
  screen = evaluate_screen(equity, pnl, trade_log)

  report = {
    "hypothesis": 14,
    "phase": "screen",
    "run_id": run_id,
    "prereg": "docs/PREREG_14_FUNDING_CARRY.md",
    "frozen_params": {
      "whitelist": list(WHITELIST),
      "entry_ann_pct": ENTRY_ANN_PCT,
      "entry_streak": ENTRY_STREAK,
      "exit_ann_pct": EXIT_ANN_PCT,
      "max_hold_days": MAX_HOLD_DAYS,
      "initial_capital": INITIAL_CAPITAL,
      "max_positions": MAX_POSITIONS,
      "margin_model": "isolated_1x_dual_leg_slot_budget_over_2",
    },
    "cost_model_B": asdict(CostModel()),
    "modeling_notes": [
      "funding_signed_each_8h",
      "separate_spot_and_mark_prices",
      "four_leg_friction_per_cycle",
      "return_on_total_account_not_position_notional",
    ],
    "screen": screen,
    "discipline": (
      "Parametros 12%/3/6%/21d congelados. Cerca del umbral = muerte, no casi. "
      "Prohibido hyperopt manual post-screen."
    ),
  }

  out_path = out_dir / "report.json"
  out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
  equity.to_frame().reset_index().to_feather(out_dir / "equity_8h.feather")
  print(json.dumps(screen, indent=2))
  print(f"\nReporte: {out_path}")
  return out_path


def main() -> int:
  parser = argparse.ArgumentParser(description="Funding carry #14 research simulator")
  parser.add_argument("--screen", action="store_true", help="Ejecutar screen unico")
  parser.add_argument("--run-id", default=None)
  args = parser.parse_args()
  if args.screen:
    run_screen(args.run_id)
    return 0
  parser.print_help()
  return 1


if __name__ == "__main__":
  raise SystemExit(main())
