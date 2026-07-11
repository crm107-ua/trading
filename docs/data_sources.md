# Fuentes de datos — inventario y viabilidad

Última revisión: 2026-07-11.

## Spot OHLCV 1d (en uso)

| Campo | Detalle |
|-------|---------|
| Fuente | Binance spot API `GET /api/v3/klines` |
| Script | `research/download_e2_local.py` → `research/data_local/binance/` (gitignored) |
| Cobertura | Universo E2 (16 pares), desde 2021-01-01, completo |
| Fiabilidad | Alta — mismo dato que el datadir Freqtrade de PC1 |

## Funding rates USDT-perp (descargado 2026-07-11)

| Campo | Detalle |
|-------|---------|
| Fuente | Binance futures API `GET /fapi/v1/fundingRate` (público, paginado 1000) |
| Script | `research/download_funding_local.py` → `research/data_local/funding/` + manifest |
| Cobertura | 16/16 perpetuals del universo E2. BTC desde 2019-09, ETH 2019-11, mayoría de alts 2020; **DEXE solo desde 2024-12** (listing tardío del perp) |
| Granularidad | 8h (3 registros/día); en research se agrega a media diaria |
| Advertencia | Dato de **futuros** usado como señal para operar **spot**. El funding refleja posicionamiento del perp, no del libro spot. Documentado en manifest y en cada experimento que lo use |

## Open interest — NO VIABLE con histórico gratuito (familia aparcada)

Comprobación empírica (2026-07-11, llamada real a la API):

- `GET /futures/data/openInterestHist` con `period=1d&limit=500` devuelve **30 filas** — Binance **limita el histórico de OI a ~30 días** en todas las granularidades (5m…1d). Verificado: primer registro devuelto 2026-06-12, último 2026-07-11.
- `GET /fapi/v1/openInterest` es solo snapshot actual (sin histórico).

Alternativas evaluadas (sin comprar nada, sin fuentes dudosas):

| Fuente | Histórico | Coste | Veredicto |
|--------|-----------|-------|-----------|
| Binance API | ~30 días | Gratis | Insuficiente |
| Coinglass | Años | API de pago (free tier muy limitado, sin histórico profundo) | Descartado (de pago) |
| CryptoQuant / Glassnode / Laevitas | Años | De pago | Descartado (de pago) |
| Scrapear/descargar de terceros no oficiales | ? | "Gratis" | Descartado (procedencia no auditable) |

**Decisión:** la familia de hipótesis basadas en OI queda **aparcada** — el criterio del laboratorio exige ≥ 2 años de histórico fiable para testear con split por mitades, y no existe vía gratuita y auditable. Se podría empezar a **acumular** OI diario desde hoy con un job propio (snapshot diario), pero eso solo produciría muestra útil dentro de años; no se implementa por ahora.

## Regla general

Todo dato nuevo entra por script versionado en `research/` con manifest JSON en `research/data_local/` (gitignored), indicando fuente, fecha de descarga, cobertura por par y advertencias de uso.
