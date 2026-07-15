"""AI integrations — NVIDIA NIM decision engine for Polymarket maker."""

from polymarket.src.ai.decision_engine import Decision, decide_quote_action
from polymarket.src.ai.env_loader import load_repo_dotenv, require_nvidia_api_key

__all__ = ["Decision", "decide_quote_action", "load_repo_dotenv", "require_nvidia_api_key"]

