from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Mapping, Protocol


class EmailSender(Protocol):
    def send_magic_link(self, email: str, link: str) -> None: ...


class ConsoleEmailSender:
    def __init__(self, log):
        self.log = log

    def send_magic_link(self, email: str, link: str) -> None:
        self.log.info("magic-link for %s: %s", email, link)


class SmtpEmailSender:
    def __init__(self, host, port, user=None, password=None, sender=None, starttls=True):
        self.host, self.port = host, int(port)
        self.user, self.password = user, password
        self.sender = sender or user or "ctc@localhost"
        self.starttls = starttls

    def send_magic_link(self, email: str, link: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = email
        msg["Subject"] = "Your CTC sign-in link"
        msg.set_content(f"Click to sign in (expires shortly):\n\n{link}\n")
        with smtplib.SMTP(self.host, self.port) as s:
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password or "")
            s.send_message(msg)


def email_sender_from_env(env: Mapping, log) -> EmailSender:
    if (env.get("CTC_EMAIL_BACKEND") or "console").strip().lower() == "smtp":
        return SmtpEmailSender(
            env["CTC_SMTP_HOST"], env.get("CTC_SMTP_PORT", "587"),
            env.get("CTC_SMTP_USER"), env.get("CTC_SMTP_PASS"),
            env.get("CTC_SMTP_FROM"),
            starttls=(env.get("CTC_SMTP_STARTTLS", "1").strip().lower() in ("1", "true", "on")),
        )
    return ConsoleEmailSender(log)
