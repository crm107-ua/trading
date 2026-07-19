# Certificación pulse@10 (pre-inversión real)

## DNA
- Champ paper: `maker_demo_promo_pulse_c10.json`
- **Locked live:** `maker_demo_promo_pulse_c10_live.json` (más selectivo)

## Barras CERTIFIED
- WR decisivo ≥ **80%**
- Decisive ≥ **16** (ventana ≤3h, excl. flats/outliers `|net|>0.35`)
- PnL robusto ≥ **+0.50**
- Dry-run CLOB: `verdict=LIVE_DRY_RUN` (0 órdenes reales)

```bash
python3 -m polymarket.research.local_lab.certify_pulse_c10 \
  --waves 2 --sessions 8 --lines 4 --minutes 5 --dry-minutes 5
```

## Armado solo si CERTIFIED
1. `ARMED=1` `DRY_RUN=1` `MAX_CAPITAL=5` — dry 30–60 min  
2. `DRY_RUN=0` `MAX_CAPITAL=2..5` — micro real  
3. DNA: `maker_demo_promo_pulse_c10_live.json`  
4. Matar si adverse/WR se degrada; volver a SAFE
