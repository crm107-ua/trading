# Fase A #16 — despliegue Hetzner + PM2

**Alcance congelado:** solo **BTC Up/Down 5m** (15m excluido).  
**Config:** [`config/phase_a.json`](../config/phase_a.json)  
**Pre-reg:** [`PREREG_16_POLY_MAKER_STALE.md`](../docs/PREREG_16_POLY_MAKER_STALE.md)

---

## Requisitos servidor

| Item | Detalle |
|------|---------|
| OS | Linux (Hetzner VPS Polifair Bot) |
| Python | 3.11+ |
| PM2 | ya instalado |
| NTP | `timedatectl status` → synchronized |
| Disco | estimar tras 24h; reservar ≥20 GB para 30d |
| Repo | `/opt/trading` (git pull) |

---

## Parámetros congelados (no cambiar a mitad de grabación)

| Parámetro | Valor |
|-----------|-------|
| `top_book_levels` | **10** |
| `compression` | gzip jsonl |
| `rotation` | horaria UTC |
| `scope` | btc_updown_5m_only |
| `pre_subscribe_lead_seconds` | **45** (smoke: ~38–45s efectivo por poll 10s) |
| `phase_a_uptime_threshold` | **95%** |
| `phase_a_min_wall_clock_days` | **30** |

---

## Instalación (una vez)

```bash
cd /opt/trading
git pull
python3 -m pip install -r polymarket/requirements.txt

# Verificar NTP
timedatectl status

# Smoke test discovery 5m
python3 -m polymarket.research.collectors.market_discovery

# Probar 60s en foreground (opcional)
timeout 60 python3 -m polymarket.research.collectors.daemon_btc_feed
timeout 60 python3 -m polymarket.research.collectors.daemon_clob_recorder
```

---

## PM2 (procesos long-running)

```bash
cd /opt/trading
pm2 start polymarket/deploy/ecosystem.config.cjs
pm2 status
pm2 logs poly16-btc-feed --lines 50
pm2 logs poly16-clob-rec --lines 50
pm2 save
```

**No usar** cron con `--duration 300` en loop — deja huecos.

---

## Salida de datos

```
polymarket/data_local/phase_a_16/
  manifest.json          # health, gaps, switches — actualizado cada hora
  btc/YYYY-MM-DD/HH.jsonl.gz
  clob/YYYY-MM-DD/HH.jsonl.gz
```

Cada línea incluye `ts_ns` (evento) y `recv_ts_ns` (reloj local).

Gaps WS: `manifest.json → feeds.*.gaps[]` con `{start_ns, end_ns}` — **solo desconexiones WS**.

**No confundir** con `market_inactive_periods[]` (clob): tramos sin ventana 5m listada en Gamma / esperando slug. El recorder sigue vivo; BTC feed puede seguir. **No** restan del uptime de fase A.

---

## Health check diario

```bash
chmod +x polymarket/deploy/health_check.sh
crontab -e
# 0 8 * * * /opt/trading/polymarket/deploy/health_check.sh >> /var/log/poly16_health.log 2>&1
```

Exit code 1 = feed stale >10 min → investigar PM2.

---

## Rotación de mercados 5m

`daemon_clob_recorder`:

1. Discovery por slug `btc-updown-5m-{timestamp}` (+ `public-search` como respaldo)
2. Filtra ventanas 5m (regex; excluye daily/hourly/15m)
3. Pre-suscribe la **siguiente** ventana **45s** antes del cierre de la actual (poll 10s en ventana de rollover)
4. Registra token **Up** only (pre-reg #16)

**Huecos entre ventanas:** si Gamma no expone la siguiente ventana 5m durante 1–3 min, el clob puede estar en espera sin token. Eso va a `market_inactive_periods` en manifest — **no** a `feeds.clob.gaps`.

---

## Validación fin fase A (día 30+)

```bash
python3 -m polymarket.research.collectors.validate_phase_a
```

| Resultado | Acción |
|-----------|--------|
| exit 0, uptime ≥95% | Fase B paper maker |
| exit 1 | **Repetir fase A** — no “aprovechar lo que hay” |
| exit 2 | Aún no han pasado 30 días |

---

## Estimación volumen (24h)

Tras el primer día, revisar:

```bash
du -sh polymarket/data_local/phase_a_16/
find polymarket/data_local/phase_a_16 -name '*.gz' | wc -l
```

Si disco insuficiente: **abortar y re-pre-registrar** (cambio de params = nuevo intento).

---

## Windows

**Smoke test** permitido en Windows (~90 min) solo en `data_local/smoke_test/` -- ver [`SMOKE_TEST_LOCAL.md`](SMOKE_TEST_LOCAL.md).

**Fase A oficial (30d)** solo Hetzner PM2 -> `phase_a_16/`. Crear `official_start.json` al validar hora 1 prod:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ > polymarket/data_local/phase_a_16/official_start.json
```
