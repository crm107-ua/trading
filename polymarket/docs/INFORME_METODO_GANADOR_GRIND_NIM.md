# Informe — Método ganador Grind NIM BEST

**Fecha:** 2026-07-18  
**Nombre corto:** Grind NIM BEST  
**IDs:** catálogo `grind_nim_best` · config `maker_demo_grind_nim_best.json`  
**Veredicto lab:** WR **80%** paper @10 EUR (4 wins / 1 loss, +0.37 EUR)  
**Aviso:** no es PnL on-chain; no extrapolar a live sin revalidación.

Documento hermano con detalle de hito:  
[`MILESTONE_2026-07-18_GRIND_NIM_BEST.md`](./MILESTONE_2026-07-18_GRIND_NIM_BEST.md)

---

## Resumen ejecutivo

Se iteró con NVIDIA NIM (hybrid + grind) sobre metodologías micro (5/10/15 EUR) hasta superar el umbral **WR ≥ 75%** en sesiones con fills. El campeón es una variante **grind** que:

- solo compra el lado **barato** (bid Up),
- rechaza edges absurdos modelo↔mercado (`max_abs_edge`),
- cobra pronto (~0.10 EUR) y corta pérdidas con techo bajo,
- usa NIM para decidir entradas ambiguas y asistir flatten.

Resultado binding del batch campeón (6×5 min @10 EUR):

```text
WR traded = 80%
Wins / Losses = 4 / 1
Total paper  = +0.37 EUR
Worst        = -0.43 EUR
Fills        = 5 (todos bid)
```

---

## Especificación operativa del método

### Entrada (cuándo cotizar)

```text
mercado: BTC Up/Down 5m
estrategia: maker_edge
mid ∈ [0.28, 0.72]
|fair - mid| ∈ [min_edge≈0.026, max_abs_edge=0.09]
solo cheap_side (bid Up); rich/ask OFF
1 fill de entrada por sesión
size = 5 shares
NIM hybrid (sin auto rule_strong_edge en grind)
```

### Salida (cuándo aplanar)

```text
lock_profit_usdc = 0.10
max_loss_usdc    = 0.10
stop_loss_mid    = 0.008
flatten_before_window_s ≥ 90
NVIDIA_NIM_GRIND + PROFIT_ASSIST ON
```

### Capitales objetivo

- Diseño: apuestas / sesiones de **5, 10 o 15 EUR**.
- Evidencia fuerte actual: **10 EUR**.
- 5 EUR y 15 EUR: OOS corta débil (ver milestone §4) → no declarar victoria multi-capital todavía.

---

## Comparativa en la ronda campeona

| Estrategia | Capital | WR | Total | Champion? |
|------------|---------|-----|-------|-----------|
| **grind_nim_flow** | 10 | **0.80** | **+0.37** | **SÍ** |
| hito_margin | 10 | 0.33 | −0.13 | no |

---

## Checklist pre-live (obligatorio)

- [ ] Revalidar `grind_nim_best` 6×5 (o más) en 5, 10 y 15 EUR
- [ ] Dry-E2E checklist OK
- [ ] Balance real ≥ ~5 pUSD
- [ ] Confirmar que pérdidas no superan `max_loss` en paper (hoy aún se vio −0.43)
- [ ] `POLY_LIVE_ARMED` solo tras lo anterior

---

## Comandos

```powershell
# Reproducir búsqueda / revalidar
python -m polymarket.research.local_lab.iterate_grind_wr --rounds 1 --sessions 6 --minutes 5 --strategies grind_nim_flow --capitals 10

# Panel
python -m polymarket.web_lab
# -> estrategia grind_nim_best
```

---

## Autoría lab

Iteración automática: `iterate_grind_wr.py`  
Modelo NIM: `nvidia/nemotron-mini-4b-instruct`  
Snapshot config: `maker_demo_grind_nim_best.json` (2026-07-18)
