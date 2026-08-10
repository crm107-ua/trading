#!/usr/bin/env python3
from __future__ import annotations
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/var/www/html/trader")
RUN = ROOT / "polymarket/data_local/local_lab/vps_runs"
ALERTS = RUN / "ALERTS.log"

def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        if "TELEGRAM" in k:
            env[k] = v
    return env

def token(e=None) -> str:
    e = e or _env()
    return e.get("MANAGER_TELEGRAM_TOKEN") or e.get("MONITOR_TELEGRAM_TOKEN") or e.get("FREQTRADE__TELEGRAM__TOKEN") or ""

def chat_id(e=None) -> str:
    e = e or _env()
    return e.get("MANAGER_TELEGRAM_CHAT_ID") or e.get("MONITOR_TELEGRAM_CHAT_ID") or e.get("FREQTRADE__TELEGRAM__CHAT_ID") or ""

def _api(tok: str, method: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{tok}/{method}"
    if data is None:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode())
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def discover_chat_id(tok: str) -> str | None:
    d = _api(tok, "getUpdates")
    for u in reversed(d.get("result") or []):
        m = u.get("message") or u.get("edited_message") or {}
        chat = m.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None

def persist_chat_id(cid: str) -> None:
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8").splitlines()
    keys = {
        "MANAGER_TELEGRAM_CHAT_ID": cid,
        "MONITOR_TELEGRAM_CHAT_ID": cid,
        "FREQTRADE__TELEGRAM__CHAT_ID": cid,
    }
    out=[]; seen=set()
    for line in lines:
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            out.append(line); continue
        k,_=line.split("=",1); k=k.strip()
        if k in keys:
            out.append(f"{k}={keys[k]}"); seen.add(k)
        else:
            out.append(line)
    for k,v in keys.items():
        if k not in seen:
            out.append(f"{k}={v}")
    p.write_text("\n".join(out)+"\n", encoding="utf-8")

def fmt_structured(title: str, fields: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["<b>Ladder Manager</b>", f"<b>{title}</b>", f"<i>{now}</i>", ""]
    for k, v in fields.items():
        lines.append(f"• <b>{k}</b>: <code>{v}</code>")
    return "\n".join(lines)

def send(title: str, fields: dict[str, Any], *, silent: bool = False) -> dict[str, Any]:
    RUN.mkdir(parents=True, exist_ok=True)
    e = _env(); tok = token(e)
    if not tok:
        raise RuntimeError("missing telegram token")
    cid = chat_id(e)
    if not cid:
        cid = discover_chat_id(tok) or ""
        if cid:
            persist_chat_id(cid)
    if not cid:
        raise RuntimeError("missing chat_id — open t.me/waxochitobot and tap Start")
    text = fmt_structured(title, fields)
    plain = f"[{datetime.now(timezone.utc).isoformat()}] {title} | " + " | ".join(f"{k}={v}" for k,v in fields.items())
    with ALERTS.open("a", encoding="utf-8") as f:
        f.write(plain + "\n")
    return _api(tok, "sendMessage", {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": "true" if silent else "false",
    })

if __name__ == "__main__":
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else "TEST"
    fields = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"status": "ok"}
    print(json.dumps(send(title, fields), indent=2)[:1000])
