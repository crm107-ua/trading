# Investigación: `macau.weather` (0x4989…983e)

**Perfil:** https://polymarket.com/es/profile/0x4989bfed5900ba096b08ba1f9b718464527c983e  
**Alias:** macau.weather · joined 2026-06-09 · ~592 predicciones · volumen ponderado ~$14.7k  
**Artifact:** `data_local/local_lab/weather_research/macau_weather_profile.json`

## Qué es (no es un bot de crypto 5m)

Es un **bot de mercados de temperatura** (familia Temperature Ladder / SurferX), no un maker de BTC-5m.

A pesar del nombre “macau”, el PnL histórico está casi todo en **Hong Kong**:

| Universo | Eventos | WR evento | PnL realizado |
|----------|--------:|----------:|--------------:|
| HK **highest** temp | 54 | 59.3% | **+$5,312** |
| HK **lowest** temp | 54 | 68.5% | **+$4,669** |
| Shenzhen highest | 17 | 11.8% | −$228 |
| Guangzhou highest | 10 | 0% | −$97 |
| Otros (Paris, etc.) | ~7 | ~0–33% | ~$0 |

**PnL agregado a nivel evento ≈ +$9.7k** (skew positivo enorme; WR por pierna ~30% porque compra muchas alas baratas).

## DNA operativo (cómo gana)

1. **Ladder multi-bucket** en el mismo día/ciudad (mediana **5 piernas** por evento).
2. Compra sobre todo **YES baratos** (mediana precio pierna ~**11¢**; ~86% de trades ≤40¢).
3. Un winner a $1 paga el bloque; piernas perdedoras son “seguro” barato.
4. Opera **highest** y también **lowest** temperature (segundo sleeve muy rentable en HK).
5. Casi todo **BUY** (1184) vs SELL (218); cobró algo de maker/taker rebates (secundario).
6. Tamaño agresivo en días buenos (p.ej. HK 14-jul: ~3k shares en 28°C → +$2.0k en esa pierna).

## Qué NO copiar

| Señal macau.weather | Por qué no |
|---------------------|------------|
| Basket unitario mediano **~0.82** | Muchos días caros → WR evento ~50% y drawdowns −$600/−$900 |
| Shenzhen / Guangzhou | PnL negativo neto |
| Width 5–8 sin filtro de precio | Alas basura + capital muerto |
| Copiar ciegamente ahora | Perfil casi flat reciente (~$1 en posiciones; seasonality julio) |

## Compatibilidad con nuestro sistema

| Pieza nuestra | Encaje |
|---------------|--------|
| `src/weather/ladder.py` (SurferX cluster) | **Directo** — misma familia |
| Multi-sleeve champion (SG/SH/HK + Beijing) | **Compatible**; HK ya está en sleeve `core` |
| Floor-trap gate | **Mejora** respecto a macau (ellos también pueden pillar open-ended) |
| Filtros cheap basket ≤0.50 / pierna ≤0.39 | **Más selectivos** que macau → menos volumen, mucho mejor WR research |
| Lowest-temperature markets | **Hueco** — ellos sacan +$4.7k ahí; nosotros aún no |
| Maker grind NIM | Ortogonal; no es su edge |

## Estrategia clave útil **hoy** (síntesis)

**No clonar su agresividad.** Tomar su *universo ganador* y ejecutarlo con *nuestros* gates:

1. **Primario (ya congelado):** multi-sleeve  
   - core SG/SH/**HK** (bias+0.5, basket≤0.50)  
   - Beijing (bias+1.0, basket≤0.55)  
   - floor gate `center < min(buckets)`  
   → research **WR 100% / +$623** · paper 12d **+$418**
2. **Priorizar Hong Kong** en discovery (ciudad donde macau.weather de verdad imprime).
3. **Excluir** Shenzhen/Guangzhou/Seoul/Taipei-volume.
4. **No** subir `max_basket_cost` hacia 0.80 “porque macau lo hace”.
5. **Próximo sleeve (research):** `lowest-temperature-in-hong-kong-*` con el mismo ladder + gates (edge empírico de este wallet).

## Comandos

```bash
# Re-analizar wallet
python -m polymarket.research.local_lab.analyze_macau_weather_wallet

# Desk actual (compatible + más estricto)
python -m polymarket.research.local_lab.validate_two_tier
python -m polymarket.research.local_lab.weather_ladder_paper \
  --config polymarket/config/weather_ladder_champion_v2.json
```
