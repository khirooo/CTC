import logging
from ctc.auth.email_sender import ConsoleEmailSender, email_sender_from_env, SmtpEmailSender


def test_console_logs_link(caplog):
    sender = ConsoleEmailSender(logging.getLogger("test"))
    with caplog.at_level(logging.INFO):
        sender.send_magic_link("a@b.com", "http://x/auth/magic?token=zzz")
    assert "a@b.com" in caplog.text and "auth/magic?token=zzz" in caplog.text


def test_from_env_defaults_to_console():
    s = email_sender_from_env({}, logging.getLogger("t"))
    assert isinstance(s, ConsoleEmailSender)


def test_from_env_smtp_selects_smtp():
    s = email_sender_from_env({
        "CTC_EMAIL_BACKEND": "smtp", "CTC_SMTP_HOST": "mail", "CTC_SMTP_PORT": "25",
        "CTC_SMTP_FROM": "ctc@x",
    }, logging.getLogger("t"))
    assert isinstance(s, SmtpEmailSender)


def test_smtp_builds_and_sends(monkeypatch):
    sent = {}
    class FakeSMTP:
        def __init__(self, host, port): sent["addr"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): sent["tls"] = True
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, msg): sent["msg"] = msg
    monkeypatch.setattr("ctc.auth.email_sender.smtplib.SMTP", FakeSMTP)
    SmtpEmailSender("mail", 587, "u", "p", "ctc@x").send_magic_link("a@b.com", "http://link")
    assert sent["addr"] == ("mail", 587)
    assert sent["msg"]["To"] == "a@b.com"
    assert "http://link" in sent["msg"].get_content()
