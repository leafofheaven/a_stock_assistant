"""Optional email notification framework for scheduled workflows."""

from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = ("password", "token", "secret", "key")


def email_enabled(env: dict[str, str] | None = None) -> bool:
    """Return whether email notification is enabled."""
    values = env or os.environ
    return str(values.get("NOTIFY_EMAIL_ENABLED", "false")).lower() in {"1", "true", "yes", "on"}


def send_email_notification(
    *,
    subject: str,
    body: str,
    attachment_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send an optional email notification when fully configured."""
    values = env or os.environ
    if not email_enabled(values):
        return {"enabled": False, "status": "disabled", "error": ""}
    required = ["NOTIFY_EMAIL_TO", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]
    missing = [key for key in required if not values.get(key)]
    if missing:
        return {"enabled": True, "status": "skipped", "error": f"邮件配置不完整: {', '.join(missing)}"}
    if dry_run:
        return {"enabled": True, "status": "dry_run", "error": ""}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = values["SMTP_FROM"]
    message["To"] = values["NOTIFY_EMAIL_TO"]
    message.set_content(body)
    if attachment_path:
        path = Path(attachment_path)
        if path.exists():
            message.add_attachment(
                path.read_bytes(),
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=path.name,
            )
    try:
        port = int(values.get("SMTP_PORT", "465"))
        if str(values.get("SMTP_USE_SSL", "true")).lower() in {"1", "true", "yes", "on"}:
            with smtplib.SMTP_SSL(values["SMTP_HOST"], port, timeout=15) as smtp:
                smtp.login(values["SMTP_USER"], values["SMTP_PASSWORD"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(values["SMTP_HOST"], port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(values["SMTP_USER"], values["SMTP_PASSWORD"])
                smtp.send_message(message)
    except Exception as exc:
        return {"enabled": True, "status": "failed", "error": _mask_sensitive(str(exc))}
    return {"enabled": True, "status": "sent", "error": ""}


def _mask_sensitive(value: str) -> str:
    masked = str(value)
    for key in SENSITIVE_KEYS:
        idx = masked.lower().find(key)
        if idx >= 0:
            masked = masked[: idx + len(key)] + "***"
    return masked
