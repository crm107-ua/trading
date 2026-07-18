import httpx, time
from polymarket.src.ai.env_loader import load_repo_dotenv
load_repo_dotenv(override=True)
from polymarket.src.execution.clob_live import ClobLiveClient

RUN = "20260717_141236_5c1baf"
cli = ClobLiveClient(); cli.connect()
START = cli.balance_collateral_usdc()
print(f"GUARD micro_5 capital=1.1 start_bal={START:.4f} run={RUN}", flush=True)
# ~9 min
for i in range(70):
    try:
        r = httpx.get(f"http://127.0.0.1:4000/api/runs/{RUN}", timeout=5).json()
    except Exception as e:
        print("panel_err", e, flush=True); time.sleep(5); continue
    bal = cli.balance_collateral_usdc()
    orders = cli.open_orders()
    drop = START - bal
    status = r.get("status")
    last = (r.get("last_line") or "")[:180]
    # heartbeat every ~24s or on interesting lines
    interesting = any(x in last for x in ("FILL", "POST ", "FLATTEN", "SKIP_CASH", "POST_ERR", "ENTRY_RICH", "quote_"))
    if i % 3 == 0 or interesting or status != "running":
        print(
            f"[{i}] {status} pct={r.get('pct')} pnl={r.get('pnl')} bal={bal:.4f} drop={drop:.3f} "
            f"ord={len(orders)} | {last}",
            flush=True,
        )
    danger = False
    reason = ""
    if drop >= 0.35:
        danger, reason = True, f"cash_drop={drop:.2f}"
    if "DUST_STUCK" in last or "FLATTEN_WRONG_TOKEN" in last:
        danger, reason = True, "stuck_exit"
    if "FILL BUY" in last and "POST_ERR" in last:
        danger, reason = True, "fill_exit_error"
    # inventory open too long with large unrealized - check positions
    if danger:
        print(f"KILL {reason}", flush=True)
        httpx.post(f"http://127.0.0.1:4000/api/runs/{RUN}/stop", timeout=10)
        try:
            cli.cancel_all()
        except Exception:
            pass
        break
    if status != "running":
        print(f"DONE status={status} pnl={r.get('pnl')} equity={r.get('equity')} bal={bal:.4f}", flush=True)
        break
    time.sleep(8)
else:
    print("timeout window", flush=True)
print("final_bal", cli.balance_collateral_usdc(), "orders", len(cli.open_orders()))
