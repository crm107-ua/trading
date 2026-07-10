"""Lockfile de validación — evita herramientas que toquen user_data/ durante un run activo."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "user_data" / "validation_reports" / ".run_lock.json"
AUDIT_LOG_PATH = ROOT / "user_data" / "validation_reports" / ".run_lock_audit.log"
LOCK_VERSION = 1
# Respaldo si la detección de PID falla (p. ej. reuse raro en Windows).
STALE_LOCK_MAX_HOURS = float(os.environ.get("VALIDATION_LOCK_MAX_HOURS", "168"))
STALE_HEARTBEAT_MAX_HOURS = float(os.environ.get("VALIDATION_LOCK_HEARTBEAT_MAX_HOURS", "6"))

logger = logging.getLogger(__name__)


@dataclass
class RunLock:
  pid: int
  strategy: str
  run_id: str
  profile: str
  started_at: str
  hostname: str = ""
  lock_version: int = LOCK_VERSION
  heartbeat_at: str = ""

  def to_dict(self) -> dict:
    return asdict(self)


class ValidationRunActiveError(RuntimeError):
  """Hay un run_validation activo; herramientas deben abortar o usar --force."""


def _utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _audit(operation: str, *, reason: str = "", **fields: object) -> None:
  """Append-only: toda mutación del lock pasa por aquí."""
  LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
  entry = {
    "ts": _utc_now_iso(),
    "pid": os.getpid(),
    "op": operation,
    "reason": reason,
    **fields,
  }
  with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _pid_alive(pid: int) -> bool:
  """Comprueba si ``pid`` sigue vivo. Conservador: ante duda, asumir vivo."""
  if pid <= 0:
    return False
  try:
    import psutil

    return psutil.pid_exists(pid)
  except ImportError:
    pass
  if os.name == "nt":
    try:
      import ctypes

      kernel32 = ctypes.windll.kernel32
      PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
      ERROR_ACCESS_DENIED = 5
      handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
      if handle:
        kernel32.CloseHandle(handle)
        return True
      if kernel32.GetLastError() == ERROR_ACCESS_DENIED:
        return True
      return False
    except Exception:
      return True
  try:
    os.kill(pid, 0)
    return True
  except OSError:
    return False


def _parse_ts(value: str) -> datetime | None:
  try:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError:
    return None


def _lock_age_hours(lock: RunLock) -> float:
  started = _parse_ts(lock.started_at)
  if started is None:
    return STALE_LOCK_MAX_HOURS + 1.0
  return (datetime.now(timezone.utc) - started).total_seconds() / 3600.0


def _heartbeat_age_hours(lock: RunLock) -> float:
  ts = lock.heartbeat_at or lock.started_at
  heartbeat = _parse_ts(ts)
  if heartbeat is None:
    return STALE_HEARTBEAT_MAX_HOURS + 1.0
  return (datetime.now(timezone.utc) - heartbeat).total_seconds() / 3600.0


def _stale_reason(lock: RunLock) -> str | None:
  if not _pid_alive(lock.pid):
    return f"pid={lock.pid} no responde como proceso vivo"
  age = _lock_age_hours(lock)
  if age > STALE_LOCK_MAX_HOURS:
    return f"antiguedad {age:.1f}h > {STALE_LOCK_MAX_HOURS}h"
  hb_age = _heartbeat_age_hours(lock)
  if hb_age > STALE_HEARTBEAT_MAX_HOURS:
    return f"heartbeat {hb_age:.1f}h > {STALE_HEARTBEAT_MAX_HOURS}h"
  return None


def _load_lock_file() -> RunLock | None:
  if not LOCK_PATH.is_file():
    return None
  try:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return RunLock(**{k: v for k, v in data.items() if k in RunLock.__dataclass_fields__})
  except (json.JSONDecodeError, TypeError, ValueError):
    LOCK_PATH.unlink(missing_ok=True)
    logger.warning("Lock de validación eliminado (json inválido): %s", LOCK_PATH)
    return None


def _write_lock(lock: RunLock) -> None:
  LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
  LOCK_PATH.write_text(json.dumps(lock.to_dict(), indent=2), encoding="utf-8")


def _remove_stale_lock(*, context: str) -> RunLock | None:
  lock = _load_lock_file()
  if lock is None:
    return None
  reason = _stale_reason(lock)
  if reason is None:
    return None
  LOCK_PATH.unlink(missing_ok=True)
  _audit(
    "stale_clear",
    reason=reason,
    context=context,
    strategy=lock.strategy,
    run_id=lock.run_id,
    lock_pid=lock.pid,
    lock_path=str(LOCK_PATH),
  )
  logger.warning(
    "Lock de validación eliminado (%s): strategy=%s run_id=%s pid=%s started_at=%s — %s",
    context,
    lock.strategy,
    lock.run_id,
    lock.pid,
    lock.started_at,
    reason,
  )
  return lock


def clear_stale_lock() -> RunLock | None:
  """Elimina lock huérfano (PID muerto, antiguo o sin heartbeat). Devuelve el lock eliminado."""
  return _remove_stale_lock(context="clear_stale_lock")


def read_lock() -> RunLock | None:
  _remove_stale_lock(context="read_lock")
  return _load_lock_file()


def acquire_lock(*, strategy: str, run_id: str, profile: str) -> RunLock:
  clear_stale_lock()
  existing = read_lock()
  if existing is not None:
    raise ValidationRunActiveError(
      f"Validación activa: {existing.strategy} run_id={existing.run_id} "
      f"pid={existing.pid} desde={existing.started_at}"
    )
  now = _utc_now_iso()
  lock = RunLock(
    pid=os.getpid(),
    strategy=strategy,
    run_id=run_id,
    profile=profile,
    started_at=now,
    heartbeat_at=now,
    hostname=socket.gethostname(),
    lock_version=LOCK_VERSION,
  )
  _write_lock(lock)
  if not LOCK_PATH.is_file():
    raise RuntimeError(f"FAIL: lock no persistió tras acquire: {LOCK_PATH}")
  _audit(
    "acquire",
    strategy=strategy,
    run_id=run_id,
    profile=profile,
    lock_pid=lock.pid,
    lock_path=str(LOCK_PATH),
    hostname=lock.hostname,
  )
  logger.info(
    "Lock de validación adquirido: strategy=%s run_id=%s pid=%s path=%s",
    strategy,
    run_id,
    lock.pid,
    LOCK_PATH,
  )
  return lock


def touch_lock_heartbeat() -> RunLock | None:
  """Renueva heartbeat del lock del proceso actual (mismo pid/run_id, started_at original)."""
  lock = _load_lock_file()
  if lock is None or lock.pid != os.getpid():
    return None
  lock.heartbeat_at = _utc_now_iso()
  _write_lock(lock)
  _audit(
    "heartbeat",
    strategy=lock.strategy,
    run_id=lock.run_id,
    lock_pid=lock.pid,
    lock_path=str(LOCK_PATH),
  )
  return lock


def release_lock() -> None:
  if not LOCK_PATH.is_file():
    return
  try:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    pid = int(data.get("pid", -1))
    strategy = data.get("strategy", "?")
    run_id = data.get("run_id", "?")
  except (json.JSONDecodeError, TypeError, ValueError):
    LOCK_PATH.unlink(missing_ok=True)
    logger.warning("Lock de validación eliminado (json inválido en release): %s", LOCK_PATH)
    return
  if pid == os.getpid():
    _audit(
      "release",
      strategy=strategy,
      run_id=run_id,
      lock_pid=pid,
      lock_path=str(LOCK_PATH),
    )
    LOCK_PATH.unlink(missing_ok=True)
    logger.info(
      "Lock de validación liberado: strategy=%s run_id=%s pid=%s",
      strategy,
      run_id,
      pid,
    )


def require_no_active_validation(*, force: bool = False, tool: str = "tool") -> RunLock | None:
  """
  Comprueba que no haya run_validation activo.

  Las herramientas que tocan user_data/ deben llamar esto al inicio.
  Limpia locks huérfanos (PID muerto, started_at o heartbeat antiguos).
  """
  clear_stale_lock()
  lock = read_lock()
  if lock is None:
    return None
  if force:
    return lock
  raise ValidationRunActiveError(
    f"{tool} abortado: validación activa ({lock.strategy}, run_id={lock.run_id}, "
    f"pid={lock.pid}, started_at={lock.started_at}). "
    "Espere a que termine o use --force bajo su responsabilidad."
  )


def assert_lock_available() -> None:
  """Usado por batch scripts antes de lanzar cada estrategia."""
  clear_stale_lock()
  lock = read_lock()
  if lock is not None:
    raise ValidationRunActiveError(
      f"Batch bloqueado: validación en curso ({lock.strategy}, pid={lock.pid}, "
      f"started_at={lock.started_at})"
    )


def _cli_check() -> int:
  logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
  try:
    assert_lock_available()
    print("OK: sin lock de validación activo")
    return 0
  except ValidationRunActiveError as exc:
    print(f"LOCKED: {exc}")
    return 3


if __name__ == "__main__":
  if len(sys.argv) > 1 and sys.argv[1] == "check":
    raise SystemExit(_cli_check())
  print("Uso: python -m pipeline.run_lock check")
  raise SystemExit(1)
