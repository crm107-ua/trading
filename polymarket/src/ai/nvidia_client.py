from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from polymarket.src.ai.env_loader import load_repo_dotenv, repo_root

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NIM_MODEL = "nvidia/nemotron-mini-4b-instruct"


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
    cache_hit: bool = False


def _default_cache_path() -> Path:
    return repo_root() / "polymarket" / "data_local" / "nvidia_models_cache.json"


def _decision_cache_dir() -> Path:
    return repo_root() / "polymarket" / "data_local" / "nim_decision_cache"


def _bearer_key() -> str:
    load_repo_dotenv()
    k = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not k:
        raise NvidiaNimError("Missing NVIDIA_API_KEY in environment")
    return k


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer_key()}", "Content-Type": "application/json"}


def primary_model_id() -> str:
    load_repo_dotenv()
    return os.environ.get("NVIDIA_NIM_MODEL", DEFAULT_NIM_MODEL).strip() or DEFAULT_NIM_MODEL


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


def _is_chat_decision_model(model_id: str) -> bool:
    """Exclude translation/vision/embed models from maker decision roster."""
    ml = model_id.lower()
    if any(x in ml for x in ("riva", "translate", "vision", "embed", "rerank", "guard")):
        return False
    if any(x in ml for x in ("51b", "70b", "80b", "405b", "90b", "253b")):
        return False
    return "instruct" in ml or ml.startswith("meta/llama-3")


def pick_fast_models(model_ids: list[str]) -> list[str]:
    primary = primary_model_id()
    eligible = [mid for mid in model_ids if _is_chat_decision_model(mid)]
    roster: list[str] = []
    if primary in eligible:
        roster.append(primary)
    # Prefer NVIDIA instruct models when primary absent from catalog.
    if primary not in eligible:
        for mid in eligible:
            ml = mid.lower()
            if mid.startswith("nvidia/") and "instruct" in ml and mid not in roster:
                roster.append(mid)
    for mid in eligible:
        if mid in roster:
            continue
        m = mid.lower()
        if any(x in m for x in ["1b", "3b", "4b", "7b", "8b"]) and "instruct" in m:
            roster.append(mid)
    if not roster:
        roster = [mid for mid in eligible if "instruct" in mid.lower()]
    if primary not in roster and primary and _is_chat_decision_model(primary):
        roster.insert(0, primary)

    def key(x: str) -> tuple[int, str]:
        if x == primary:
            return (0, x)
        xl = x.lower()
        if xl.startswith("nvidia/"):
            return (1, xl)
        for size, rank in [("1b", 2), ("3b", 3), ("4b", 4), ("7b", 5), ("8b", 6)]:
            if size in xl:
                return (rank, xl)
        return (99, xl)

    return sorted(roster, key=key)[:6]


def _cache_key(model: str, messages: list[dict[str, str]]) -> str:
    blob = json.dumps({"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def read_decision_cache(model: str, messages: list[dict[str, str]]) -> NimResponse | None:
    path = _decision_cache_dir() / f"{_cache_key(model, messages)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return NimResponse(
            model=str(data["model"]),
            content=str(data["content"]),
            latency_ms=int(data.get("latency_ms", 0)),
            raw=data.get("raw") or {},
            cache_hit=True,
        )
    except Exception:
        return None


def write_decision_cache(resp: NimResponse, messages: list[dict[str, str]]) -> None:
    d = _decision_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_cache_key(resp.model, messages)}.json"
    path.write_text(
        json.dumps(
            {
                "model": resp.model,
                "content": resp.content,
                "latency_ms": resp.latency_ms,
                "raw": resp.raw,
                "ts": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def chat_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout_ms: int = 1200,
    temperature: float = 0.0,
    max_tokens: int = 256,
    use_cache: bool = True,
) -> NimResponse:
    if use_cache:
        cached = read_decision_cache(model, messages)
        if cached is not None:
            return cached

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
    resp = NimResponse(model=model, content=str(content), latency_ms=latency_ms, raw=data)
    if use_cache:
        write_decision_cache(resp, messages)
    return resp


def robust_chat_completion(
    *,
    messages: list[dict[str, str]],
    timeout_ms: int = 1200,
    temperature: float = 0.0,
    max_tokens: int = 256,
    preferred_models: list[str] | None = None,
    use_cache: bool = True,
) -> NimResponse:
    """
    Primary model first (NVIDIA_NIM_MODEL), then fast roster fallback on transient errors only.
    """
    if preferred_models is None:
        cache = cache_models()
        model_ids = [m["id"] for m in cache.get("models") or [] if "id" in m]
        preferred_models = pick_fast_models(model_ids)
    if not preferred_models:
        raise NvidiaNimError("No models available to try")

    last_err: Exception | None = None
    for mid in preferred_models:
        for attempt in range(3):
            try:
                return chat_completion(
                    model=mid,
                    messages=messages,
                    timeout_ms=timeout_ms,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    use_cache=use_cache,
                )
            except NvidiaNimError as e:
                last_err = e
                time.sleep(0.35 * (attempt + 1))
                continue
            except Exception as e:  # noqa: BLE001
                last_err = e
                break
    raise NvidiaNimError(f"All models failed: {last_err}")
