# NVIDIA NIM (build.nvidia.com) — integración local/paper

## Qué es

NVIDIA Build expone modelos (NIM) vía un endpoint **OpenAI-compatible** para prototipado.

## Endpoint y auth

- **Base URL**: `https://integrate.api.nvidia.com/v1`
- **API key**: `NVIDIA_API_KEY` (suele empezar por `nvapi-...`)
- **Header**: `Authorization: Bearer $NVIDIA_API_KEY`

Endpoints usados:

- `GET /models`
- `POST /chat/completions`

## Errores comunes

- **403 Forbidden**: la key se creó sin el scope de **Public API Endpoints**. Solución: crear una key nueva en `build.nvidia.com` con ese permiso.
- **429 Too Many Requests**: rate limit; aplicar backoff + fallback a otro modelo.

## Uso en este repo (congelado)

Esta integración es **solo lab/paper**:

- Decide **acción** (`quote`/`hold`/`cancel_replace`) con guardas y fallback.
- **No** cambia los parámetros congelados del pre-reg #16 (spread/sigma/tamaño) ni genera proyecciones de PnL.

Archivos:

- `polymarket/src/ai/nvidia_client.py`
- `polymarket/src/ai/decision_engine.py`
- `polymarket/research/local_lab/test_nvidia_nim.py`

Ejecutar el test:

```powershell
$env:NVIDIA_API_KEY = "nvapi-..."
python -m polymarket.research.local_lab.test_nvidia_nim
```

