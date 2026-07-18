"""Cliente CLOB Polymarket V2 con gates (ARMED / DRY_RUN / caps).

Usa py-clob-client-v2: signature_type=3 (POLY_1271) requiere V2;
el cliente V1 rechaza type 3 con ValidationException.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from eth_account import Account

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"


@dataclass(frozen=True)
class LiveGates:
    armed: bool
    dry_run: bool
    max_capital_usdc: float
    signature_type: int
    funder: str
    eoa: str
    clob_ready: bool
    signing_ready: bool
    missing: list[str]


def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip() == "1"


def read_gates() -> LiveGates:
    missing: list[str] = []
    pk = (os.getenv("POLY_PRIVATE_KEY") or "").strip()
    key = (os.getenv("POLY_CLOB_API_KEY") or "").strip()
    secret = (os.getenv("POLY_CLOB_API_SECRET") or "").strip()
    phrase = (os.getenv("POLY_CLOB_API_PASSPHRASE") or "").strip()
    if not pk:
        missing.append("POLY_PRIVATE_KEY")
    for k, v in (
        ("POLY_CLOB_API_KEY", key),
        ("POLY_CLOB_API_SECRET", secret),
        ("POLY_CLOB_API_PASSPHRASE", phrase),
    ):
        if not v:
            missing.append(k)

    eoa = ""
    if pk:
        try:
            eoa = Account.from_key(pk).address
        except Exception:
            missing.append("POLY_PRIVATE_KEY(invalid)")

    funder = (
        (os.getenv("POLY_FUNDER_ADDRESS") or "").strip()
        or (os.getenv("POLYMARKET_PROXY_WALLET") or "").strip()
        or eoa
    )
    sig = int((os.getenv("POLY_SIGNATURE_TYPE") or "3").strip() or "3")
    max_cap = float(os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or "5")
    return LiveGates(
        armed=_flag("POLY_LIVE_ARMED", "0"),
        dry_run=(os.getenv("POLY_LIVE_DRY_RUN") or "1").strip() != "0",
        max_capital_usdc=max_cap,
        signature_type=sig,
        funder=funder,
        eoa=eoa,
        clob_ready=bool(key and secret and phrase),
        signing_ready=bool(pk and eoa),
        missing=missing,
    )


def _round_price(price: float, tick: float = 0.01) -> float:
    tick = float(tick) if tick and float(tick) > 0 else 0.01
    steps = round(float(price) / tick)
    px = round(steps * tick, 8)
    # stay inside (tick, 1-tick)
    lo = tick
    hi = 1.0 - tick
    return max(lo, min(hi, px))


# Polymarket CLOB production floors (seen in API errors)
MIN_ORDER_SHARES = 5.0
MIN_BUY_NOTIONAL_USDC = 1.0


def _round_size(size: float, *, decimals: int = 2) -> float:
    scale = 10**decimals
    sz = math.floor(float(size) * scale + 1e-12) / scale
    return round(max(sz, 0.0), decimals)


def round_inventory_size(size: float) -> float:
    """Tamaño de tokens condicionales (6 dec CLOB) sin redondear al alza."""
    return _round_size(size, decimals=6)


def normalize_live_order(
    *,
    side: str,
    price: float,
    size: float,
    tick: float = 0.01,
    enforce_min_shares: bool | None = None,
) -> tuple[float, float]:
    """Ajusta price/size. BUY: min 5 shares y notional >= $1.
    SELL: NUNCA subir size por encima del inventario (enforce_min_shares=False)."""
    side_u = side.upper()
    px = _round_price(price, tick)
    if enforce_min_shares is None:
        enforce_min_shares = side_u == "BUY"
    if side_u == "SELL":
        # Exacto al inventario disponible (floor 6dp) — no bump a 5
        sz = round_inventory_size(size)
        return px, sz
    sz = _round_size(size, decimals=2)
    if enforce_min_shares:
        sz = max(sz, MIN_ORDER_SHARES)
    if side_u == "BUY" and px > 0 and px * sz < MIN_BUY_NOTIONAL_USDC:
        need = math.ceil((MIN_BUY_NOTIONAL_USDC / px) * 100) / 100.0
        sz = max(sz, need, MIN_ORDER_SHARES)
        sz = _round_size(sz, decimals=2)
        if px * sz < MIN_BUY_NOTIONAL_USDC:
            sz = _round_size(MIN_BUY_NOTIONAL_USDC / px + 0.01, decimals=2)
            sz = max(sz, MIN_ORDER_SHARES)
    return px, sz


class ClobLiveClient:
    """Wrapper sobre py-clob-client-v2. DRY_RUN no envía órdenes."""

    def __init__(self) -> None:
        self.gates = read_gates()
        self._client: Any = None

    def connect(self) -> None:
        from py_clob_client_v2 import ApiCreds, ClobClient

        g = self.gates
        if g.missing:
            raise RuntimeError(f"Credenciales incompletas: {', '.join(g.missing)}")
        host = (os.getenv("POLY_CLOB_HOST") or "https://clob.polymarket.com").rstrip("/")
        creds = ApiCreds(
            api_key=os.environ["POLY_CLOB_API_KEY"].strip(),
            api_secret=os.environ["POLY_CLOB_API_SECRET"].strip(),
            api_passphrase=os.environ["POLY_CLOB_API_PASSPHRASE"].strip(),
        )
        self._client = ClobClient(
            host,
            chain_id=int(os.getenv("POLY_CHAIN_ID") or "137"),
            key=os.environ["POLY_PRIVATE_KEY"].strip(),
            creds=creds,
            signature_type=g.signature_type,
            funder=g.funder or None,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self.connect()
        return self._client

    def balance_collateral_usdc(self) -> float:
        from py_clob_client_v2 import AssetType, BalanceAllowanceParams

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        try:
            self.client.update_balance_allowance(params)
        except Exception:
            pass
        bal = self.client.get_balance_allowance(params)
        return int(bal.get("balance") or "0") / 1e6

    def balance_conditional_shares(self, token_id: str) -> float:
        """Shares del token condicional (tras update allowance)."""
        from py_clob_client_v2 import AssetType, BalanceAllowanceParams

        params = BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL, token_id=str(token_id)
        )
        try:
            self.client.update_balance_allowance(params)
        except Exception:
            pass
        bal = self.client.get_balance_allowance(params)
        return int(bal.get("balance") or "0") / 1e6

    def assert_can_trade(self, *, capital: float, allow_dry: bool = True) -> None:
        g = self.gates
        if capital > g.max_capital_usdc + 1e-9:
            raise RuntimeError(
                f"Capital {capital} > POLY_LIVE_MAX_CAPITAL_USDC={g.max_capital_usdc}"
            )
        if not g.armed:
            raise RuntimeError("POLY_LIVE_ARMED=0 — modo SAFE.")
        if g.dry_run and not allow_dry:
            raise RuntimeError("POLY_LIVE_DRY_RUN=1 — solo simulación de post.")
        if g.missing:
            raise RuntimeError(f"Faltan credenciales: {', '.join(g.missing)}")

    def place_post_only_gtc(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        side_u = side.upper()
        if side_u not in ("BUY", "SELL"):
            raise ValueError(f"side inválido: {side}")

        tick = 0.01
        try:
            tick = float(self.client.get_tick_size(str(token_id)) or 0.01)
        except Exception:
            pass
        px, sz = normalize_live_order(side=side_u, price=price, size=size, tick=tick)
        if px <= 0 or px >= 1 or sz <= 0:
            raise ValueError(f"precio/size inválidos: price={px} size={sz}")
        if sz < MIN_ORDER_SHARES:
            raise ValueError(
                f"size {side_u} {sz} < min {MIN_ORDER_SHARES} "
                "(CLOB no acepta órdenes bajo 5 shares; fill parcial = dust)"
            )
        if side_u == "BUY" and px * sz < MIN_BUY_NOTIONAL_USDC - 1e-9:
            raise ValueError(
                f"notional BUY {px * sz:.2f} < min ${MIN_BUY_NOTIONAL_USDC:.0f}"
            )

        return self._post_normalized(
            token_id=str(token_id),
            side_u=side_u,
            px=px,
            sz=sz,
            post_only=True,
            order_type="GTC",
        )

    def place_aggressive(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "FAK",
    ) -> dict[str, Any]:
        """Salida/entrada que puede cruzar el libro (sin post-only)."""
        side_u = side.upper()
        if side_u not in ("BUY", "SELL"):
            raise ValueError(f"side inválido: {side}")
        tick = 0.01
        try:
            tick = float(self.client.get_tick_size(str(token_id)) or 0.01)
        except Exception:
            pass
        px, sz = normalize_live_order(side=side_u, price=price, size=size, tick=tick)
        if px <= 0 or px >= 1 or sz <= 0:
            raise ValueError(f"precio/size inválidos: price={px} size={sz}")
        if sz < MIN_ORDER_SHARES:
            raise ValueError(
                f"size {side_u} {sz} < min {MIN_ORDER_SHARES} (dust no vendible)"
            )
        if side_u == "BUY" and px * sz < MIN_BUY_NOTIONAL_USDC - 1e-9:
            raise ValueError(
                f"notional BUY {px * sz:.2f} < min ${MIN_BUY_NOTIONAL_USDC:.0f}"
            )
        ot = (order_type or "FAK").upper()
        if ot not in ("GTC", "FOK", "FAK"):
            ot = "FAK"
        return self._post_normalized(
            token_id=str(token_id),
            side_u=side_u,
            px=px,
            sz=sz,
            post_only=False,
            order_type=ot,
        )

    def _post_normalized(
        self,
        *,
        token_id: str,
        side_u: str,
        px: float,
        sz: float,
        post_only: bool,
        order_type: str,
    ) -> dict[str, Any]:
        from py_clob_client_v2 import OrderArgs, OrderType, Side

        payload = {
            "token_id": str(token_id),
            "side": side_u,
            "price": px,
            "size": sz,
            "notional": round(px * sz, 4),
            "post_only": bool(post_only),
            "order_type": order_type,
            "signature_type": self.gates.signature_type,
            "client": "py-clob-client-v2",
        }
        if self.gates.dry_run:
            return {"status": "DRY_RUN", "would_post": payload, "orderID": None}

        if not self.gates.armed:
            raise RuntimeError("Bloqueado: no ARMED")

        args = OrderArgs(
            token_id=str(token_id),
            price=px,
            size=sz,
            side=Side.BUY if side_u == "BUY" else Side.SELL,
        )
        signed = self.client.create_order(args)
        ot = getattr(OrderType, order_type, OrderType.GTC)
        resp = self.client.post_order(signed, ot, post_only=bool(post_only))
        return {
            "status": "LIVE",
            "response": resp,
            "would_post": payload,
            "orderID": _extract_order_id(resp),
        }

    def cancel(self, order_id: str) -> dict[str, Any]:
        from py_clob_client_v2 import OrderPayload

        if self.gates.dry_run or not order_id:
            return {"status": "DRY_RUN", "cancelled": order_id}
        if not self.gates.armed:
            raise RuntimeError("Bloqueado: no ARMED")
        payload = OrderPayload(orderID=str(order_id))
        return {"status": "LIVE", "response": self.client.cancel_order(payload)}

    def cancel_all(self) -> dict[str, Any]:
        if self.gates.dry_run:
            return {"status": "DRY_RUN", "cancelled_all": True}
        if not self.gates.armed:
            return {"status": "SAFE", "skipped": True}
        return {"status": "LIVE", "response": self.client.cancel_all()}

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        if not order_id or str(order_id).startswith("dry-"):
            return None
        try:
            raw = self.client.get_order(str(order_id))
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None

    def open_orders(self, asset_id: str | None = None) -> list[dict]:
        from py_clob_client_v2 import OpenOrderParams

        params = OpenOrderParams(asset_id=asset_id) if asset_id else OpenOrderParams()
        raw = self.client.get_open_orders(params)
        if isinstance(raw, list):
            return raw
        return list(raw or [])

    def recent_trades(self, asset_id: str | None = None, after: int | None = None) -> list[dict]:
        """Trades del usuario. NO filtrar por asset_id: el fill maker UP
        a veces aparece como trade del lado Down (complementario)."""
        from py_clob_client_v2 import TradeParams

        kwargs: dict[str, Any] = {}
        # Solo filtrar asset si se pide explícitamente; por defecto todos
        if asset_id:
            kwargs["asset_id"] = asset_id
        if after is not None:
            kwargs["after"] = after
        params = TradeParams(**kwargs) if kwargs else TradeParams()
        raw = self.client.get_trades(params)
        if isinstance(raw, list):
            return raw
        return list(raw or [])

    @staticmethod
    def fill_from_order(order: dict[str, Any]) -> dict[str, Any] | None:
        """Extrae fill desde get_order (status MATCHED / size_matched)."""
        if not order:
            return None
        status = str(order.get("status") or "").upper()
        try:
            matched = float(order.get("size_matched") or 0)
            price = float(order.get("price") or 0)
            original = float(order.get("original_size") or matched or 0)
        except (TypeError, ValueError):
            return None
        if matched <= 0 or price <= 0:
            return None
        # Completo o casi completo
        done = status in ("MATCHED", "CLOSED", "FILLED") or matched >= original - 1e-9
        if not done and status in ("LIVE", "OPEN", "ACTIVE"):
            # partial: aún reportar matched para sync
            pass
        side = str(order.get("side") or "BUY").upper()
        return {
            "order_id": str(order.get("id") or order.get("orderID") or ""),
            "side": side,
            "price": price,
            "size": matched,
            "status": status,
            "asset_id": str(order.get("asset_id") or ""),
        }

    @staticmethod
    def fills_from_trades(trades: list[dict], our_order_ids: set[str]) -> list[dict[str, Any]]:
        """Detecta fills nuestros vía maker_orders / order ids en trades."""
        out: list[dict[str, Any]] = []
        our = {str(x).lower() for x in our_order_ids if x}
        for t in trades or []:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            makers = t.get("maker_orders") or []
            hit = None
            for mo in makers:
                if not isinstance(mo, dict):
                    continue
                oid = str(mo.get("order_id") or mo.get("id") or "")
                if oid.lower() in our:
                    hit = mo
                    break
            taker_oid = str(t.get("taker_order_id") or "")
            if hit is None and taker_oid.lower() in our:
                hit = {"order_id": taker_oid, "price": t.get("price"), "matched_amount": t.get("size")}
            if hit is None:
                continue
            try:
                price = float(hit.get("price") or t.get("price") or 0)
                size = float(
                    hit.get("matched_amount")
                    or hit.get("size")
                    or t.get("size")
                    or 0
                )
            except (TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            # Nuestro side: el de la orden maker, no el del taker trade
            side = str(hit.get("side") or "").upper()
            if side not in ("BUY", "SELL"):
                # Infer: if we were maker on complementary print, still use our resting side later
                side = ""
            out.append(
                {
                    "trade_id": tid,
                    "order_id": str(hit.get("order_id") or ""),
                    "side": side,
                    "price": price,
                    "size": size,
                }
            )
        return out


def _extract_order_id(resp: Any) -> str | None:
    if resp is None:
        return None
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("orderID", "order_id", "id"):
            if resp.get(k):
                return str(resp[k])
        inner = resp.get("order") or resp.get("data")
        if isinstance(inner, dict):
            return _extract_order_id(inner)
    return None


def live_health() -> dict[str, Any]:
    from polymarket.src.execution.live_policy import (
        MIN_REAL_BALANCE_PUSD,
        evaluate_readiness,
        load_checklist,
        load_day_pnl,
    )

    g = read_gates()
    out: dict[str, Any] = {
        "armed": g.armed,
        "dry_run": g.dry_run,
        "max_capital_usdc": g.max_capital_usdc,
        "signature_type": g.signature_type,
        "funder": g.funder,
        "eoa": g.eoa,
        "clob_ready": g.clob_ready,
        "signing_ready": g.signing_ready,
        "missing": g.missing,
        "client": "py-clob-client-v2",
        "balance_pusd": None,
        "can_live": False,
        "can_dry": False,
        "error": None,
        "min_real_balance_pusd": MIN_REAL_BALANCE_PUSD,
        "checklist": load_checklist(),
        "day_pnl": load_day_pnl(),
        "policy_blockers": [],
    }
    try:
        bal = None
        if g.signing_ready and g.clob_ready:
            cli = ClobLiveClient()
            cli.connect()
            bal = cli.balance_collateral_usdc()
            out["balance_pusd"] = round(bal, 4)
        ready = evaluate_readiness(balance_pusd=bal, dry_run=g.dry_run)
        out["can_dry"] = bool(g.armed and g.dry_run and not g.missing)
        out["can_live"] = bool(
            g.armed and (not g.dry_run) and ready.can_real and not g.missing
        )
        out["policy_blockers"] = ready.blockers
        out["checklist_ok"] = ready.checklist_ok
        out["open_orders"] = 0
        if g.signing_ready and g.clob_ready and bal is not None:
            try:
                out["open_orders"] = len(cli.open_orders())
            except Exception:
                pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
