from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaNimError(RuntimeError):
    pass


@dataclass(frozen=True)
class NimModel:
    id: str
    owned_by: str | None = None


@dataclass(frozen=True)
class NimResponse:
    model: str
    content: str
    latency_ms: int
    raw: dict[str, Any]


def _default_cache_path() -> Path:
    # Keep cache out of git-tracked source by default.
    root = Path(__file__).resolve().parents[2]
    return root / "data_local" / "nvidia_models_cache.json"


def _bearer_key() -> str:
    k = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not k:
        raise NvidiaNimError("Missing NVIDIA_API_KEY in environment")
    return k


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer_key()}", "Content-Type": "application/json"}


def list_models(*, timeout_s: float = 10.0) -> list[NimModel]:
    with httpx.Client(timeout=timeout_s) as client:
        r = client.get(f"{NVIDIA_BASE_URL}/models", headers=_headers())
        if r.status_code == 403:
            raise NvidiaNimError(
                "403 Forbidden from NVIDIA NIM. "
                "Your key may be missing the 'Public API endpoints' scope."
            )
        r.raise_for_status()
        data = r.json()
        out = []
        for m in data.get("data") or []:
            mid = m.get("id")
            if mid:
                out.append(NimModel(id=str(mid), owned_by=m.get("owned_by")))
        return out


def cache_models(
    *,
    cache_path: Path | None = None,
    max_age_s: int = 6 * 3600,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    cache_path = cache_path or _default_cache_path()
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - float(data.get("ts", 0)) < max_age_s:
                return data
        except Exception:
            pass
    models = list_models(timeout_s=timeout_s)
    payload = {"ts": time.time(), "base_url": NVIDIA_BASE_URL, "models": [m.__dict__ for m in models]}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def pick_fast_models(model_ids: list[str]) -> list[str]:
    """
    Heuristic fast roster: prefer small instruct models.
    We don't assume exact catalog; we filter by common size hints.
    """
    preferred = []
    for mid in model_ids:
        m = mid.lower()
        if any(x in m for x in ["1b", "3b", "4b", "7b", "8b"]) and "instruct" in m:
            preferred.append(mid)
    # Fallback: any instruct model
    if not preferred:
        preferred = [mid for mid in model_ids if "instruct" in mid.lower()]
    # Stable order: smaller first if possible
    def key(x: str) -> tuple[int, str]:
        xl = x.lower()
        for size, rank in [("1b", 1), ("3b", 2), ("4b", 3), ("7b", 4), ("8b", 5)]:
            if size in xl:
                return (rank, xl)
        return (99, xl)

    return sorted(preferred, key=key)[:6]


def chat_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout_ms: int = 1200,
    temperature: float = 0.0,
    max_tokens: int = 256,
) -> NimResponse:
    t0 = time.perf_counter()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    timeout = httpx.Timeout(timeout_ms / 1000.0, connect=3.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{NVIDIA_BASE_URL}/chat/completions", headers=_headers(), json=payload)
        if r.status_code in (429, 500, 502, 503, 504):
            raise NvidiaNimError(f"Transient NVIDIA NIM error {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        data = r.json()
    latency_ms = int((time.perf_counter() - t0) * 1000)
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise NvidiaNimError(f"Unexpected response shape: {data}") from exc
    return NimResponse(model=model, content=str(content), latency_ms=latency_ms, raw=data)


def robust_chat_completion(
    *,
    messages: list[dict[str, str]],
    timeout_ms: int = 1200,
    temperature: float = 0.0,
    max_tokens: int = 256,
    preferred_models: list[str] | None = None,
) -> NimResponse:
    """
    Try multiple models sequentially (fast roster), with 1 retry on transient errors.
    """
    if preferred_models is None:
        cache = cache_models()
        model_ids = [m["id"] for m in cache.get("models") or [] if "id" in m]
        preferred_models = pick_fast_models(model_ids)
    if not preferred_models:
        raise NvidiaNimError("No models available to try")

    last_err: Exception | None = None
    for mid in preferred_models:
        for attempt in range(2):
            try:
                return chat_completion(
                    model=mid,
                    messages=messages,
                    timeout_ms=timeout_ms,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except NvidiaNimError as e:
                last_err = e
                # quick backoff
                time.sleep(0.2 * (attempt + 1))
                continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                break
    raise NvidiaNimError(f"All models failed: {last_err}")

