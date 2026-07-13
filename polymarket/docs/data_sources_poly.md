# Fuentes de datos — Polymarket Lab

Patrón manifest: cada dataset en `polymarket/data_local/<dataset_id>/manifest.json`.

---

## APIs

| API | Base URL | Uso |
|-----|----------|-----|
| **Gamma** | `https://gamma-api.polymarket.com` | Discovery: eventos, mercados, token_ids, strike, endDate |
| **CLOB REST** | `https://clob.polymarket.com` | Book, prices-history, órdenes (live) |
| **CLOB WS** | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Book snapshots + trades en vivo |
| **Binance spot** | `https://api.binance.com` | Feed BTC USDT (referencia externa) |

---

## Endpoints clave

### Gamma — discovery

```
GET /public-search?q=Bitcoin+Up+or+Down&events_status=active
GET /events?slug=btc-updown-5m-{unix_window_start}   # fase A #16 — preferido
GET /markets/{id}
```

Campos útiles: `clobTokenIds`, `question`, `endDate`, `acceptingOrders`.

**Hueco entre ventanas 5m:** `public-search` puede tardar 1–3 min en listar la siguiente ventana. Eso **no** es fallo del recorder. Manifest: `market_inactive_periods[]` (espera) vs `feeds.*.gaps[]` (WS caído). Ver `PREREG_16` corrección 2026-07-13.

### CLOB — book y histórico

```
GET /book?token_id={asset_id}
GET /prices-history?market={asset_id}&interval=1d&fidelity=60
```

**Limitación:** `prices-history` devuelve solo **mid** (`t`, `p`). Sin depth histórico gratuito.

### CLOB WS — suscripción

```json
{"assets_ids": ["<token_id>"], "type": "market"}
```

Eventos: `book`, `price_change`, `last_trade_price`.

---

## Manifest (ejemplo)

```json
{
  "dataset_id": "clob_btc_5m_20260713",
  "source": "clob_recorder",
  "token_id": "...",
  "start_utc": "2026-07-13T15:00:00Z",
  "end_utc": "2026-07-13T16:00:00Z",
  "rows": 1200,
  "columns": ["timestamp_ms", "bids", "asks", "last_trade"],
  "notes": "WS market channel; no garantía de completitud"
}
```

---

## Límites y calidad

| Limitación | Mitigación en research |
|------------|------------------------|
| Sin depth histórico | Grabar WS hacia adelante; screen con slippage conservador |
| Mercados 5m efímeros | `market_discovery` cada ciclo; cache corto |
| Resolución oracle | Documentar fuente strike; no operar sin reglas claras |
| Geo/KYC | Checklist Fase 0.1 — responsabilidad del operador |

---

## Dependencias Python

```
httpx, websockets, pandas, numpy, pydantic
```

Opcional live: `py-clob-client` (firma Polygon) — no requerido para paper/research.
