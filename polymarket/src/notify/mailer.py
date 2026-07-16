#!/usr/bin/env python3
"""SMTP mailer — credenciales solo desde .env (nunca hardcode)."""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from polymarket.src.ai.env_loader import load_repo_dotenv


def _cfg() -> dict[str, str]:
    load_repo_dotenv()
    return {
        "host": os.environ.get("MAIL_HOST", "smtp.gmail.com").strip(),
        "port": os.environ.get("MAIL_PORT", "465").strip(),
        "user": os.environ.get("MAIL_USERNAME", "").strip(),
        "password": os.environ.get("MAIL_PASSWORD", "").strip(),
        "encryption": os.environ.get("MAIL_ENCRYPTION", "ssl").strip().lower(),
        "from_addr": os.environ.get("MAIL_FROM", "").strip()
        or os.environ.get("MAIL_USERNAME", "").strip(),
        "to_addr": os.environ.get("MAIL_TO", "caromamusic@gmail.com").strip(),
    }


def send_email(*, subject: str, body_text: str, body_html: str | None = None) -> dict:
    """
    Envía email. No loguea password ni el cuerpo completo en excepciones sensibles.
    Returns: {ok: bool, to: str, error?: str}
    """
    c = _cfg()
    if not c["user"] or not c["password"]:
        return {"ok": False, "to": c["to_addr"], "error": "MAIL_USERNAME/MAIL_PASSWORD missing in .env"}
    to_addr = c["to_addr"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = c["from_addr"]
    msg["To"] = to_addr
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        port = int(c["port"] or "465")
        if c["encryption"] == "ssl" or port == 465:
            with smtplib.SMTP_SSL(c["host"], port, timeout=45) as smtp:
                smtp.login(c["user"], c["password"])
                smtp.sendmail(c["from_addr"], [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(c["host"], port, timeout=45) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(c["user"], c["password"])
                smtp.sendmail(c["from_addr"], [to_addr], msg.as_string())
        return {"ok": True, "to": to_addr}
    except Exception as e:
        return {"ok": False, "to": to_addr, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    """Smoke test: python -m polymarket.src.notify.mailer"""
    r = send_email(
        subject="[trader] SMTP smoke test OK",
        body_text=(
            "Prueba de correo desde polymarket overnight autotune.\n"
            "Si lees esto, SMTP Gmail funciona en el servidor.\n"
        ),
    )
    print(r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
