"""Imagen Docker pinneada — única fuente de verdad con docker-compose.yml."""

from __future__ import annotations

import os
import re

# Pin por digest — actualizar solo tras probar pickle/hyperopt e informative merge.
FREQTRADE_IMAGE_REPO = "freqtradeorg/freqtrade"
FREQTRADE_IMAGE_DIGEST = (
  "sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a"
)
FREQTRADE_IMAGE_PINNED = f"{FREQTRADE_IMAGE_REPO}@{FREQTRADE_IMAGE_DIGEST}"

# Candidato Py 3.12 para probar hyperopt paralelo (freqtrade 2025.3 = Python 3.12.9).
FREQTRADE_IMAGE_PY312_CANDIDATE = os.environ.get(
  "FREQTRADE_IMAGE_PY312_CANDIDATE", "freqtradeorg/freqtrade:2025.3"
)


def pinned_image_ref() -> str:
  return os.environ.get("FREQTRADE_IMAGE", FREQTRADE_IMAGE_PINNED)


def image_digest_from_ref(ref: str) -> str | None:
  match = re.search(r"sha256:[a-f0-9]{64}", ref)
  return match.group(0) if match else None
