import httpx, time, json
from polymarket.src.ai.env_loader import load_repo_dotenv
load_repo_dotenv(override=True)
from polymarket.src.execution.clob_live import ClobLiveClient

RUN = "20260717_140407_9bc2eb"
START_BAL = None
cli = ClobLiveClient(); cli.connect()
START_BAL = cli.balance_collateral_usdc()
print(f"MONITOR start bal={START_BAL:.4f} run={RUN}", flush=True)

# loss trip: >0.35 pUSD drop or open position + flatten spam / stuck
for i in range(40):  # ~3-4 min of samples then continue if still running
    try:
        r = httpx.get(f"http://127.0.0.1:4000/api/runs/{RUN}", timeout=5).json()
    except Exception as e:
        print("panel", e); time.sleep(5); continue
    bal = cli.balance_collateral_usdc()
    orders = cli.open_orders()
    drop = START_BAL - bal
    status = r.get("status")
    last = (r.get("last_line") or "")[:160]
    print(
        f"[{i}] status={status} pct={r.get('pct')} pnl={r.get('pnl')} "
        f"bal={bal:.4f} drop={drop:.3f} orders={len(orders)} | {last}",
        flush=True,
    )
    # Kill switches
    danger = False
    reason = ""
    if drop >= 0.40:
        danger, reason = True, f"drop={drop:.2f}>=0.40"
    if any(str(o.get("side","")).upper()=="BUY" and float(o.get("price") or 0)*float(o.get("original_size") or 0) > bal+0.5 for o in orders):
        danger, reason = True, "buy_order_oversize"
    # stuck sell dust spam signals in last_line
    if "POST_ERR" in last and "balance" in last.lower() and "FILL" in last:
        danger, reason = True, "fill_then_exit_fail"
    if "DUST_STUCK" in last or "FLATTEN_WRONG_TOKEN" in last:
        danger, reason = True, "dust_or_wrong_token"
    if danger:
        print(f"STOP_TRIP {reason}", flush=True)
        try:
            httpx.post(f"http://127.0.0.1:4000/api/runs/{RUN}/stop", timeout=10)
        except Exception as e:
            print("stop_err", e)
        try:
            cli.cancel_all()
        except Exception:
            pass
        break
    if status != "running":
        print(f"RUN_ENDED status={status} pnl={r.get('pnl')} equity={r.get('equity')}", flush=True)
        break
    time.sleep(8)
else:
    print("monitor window done; run may still be active — recheck", flush=True)
    r = httpx.get(f"http://127.0.0.1:4000/api/runs/{RUN}", timeout=5).json()
    print("final", r.get("status"), r.get("pnl"), r.get("last_line"))
print("end_bal", cli.balance_collateral_usdc())
