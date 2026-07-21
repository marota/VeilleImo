"""Envoi d'email via SMTP Gmail. Lit les identifiants dans l'environnement
(jamais en dur) : GMAIL_ADDRESS, GMAIL_APP_PASSWORD, MAIL_TO."""
import os, ssl, smtplib
from email.message import EmailMessage


def send(subject, html_body, text_body=None, attachments=None):
    addr = os.environ["GMAIL_ADDRESS"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("MAIL_TO", addr)
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body or "Rapport de veille — version HTML ci-jointe.")
    msg.add_alternative(html_body, subtype="html")
    for fname, data, mime in (attachments or []):
        maintype, subtype = mime.split("/", 1)
        if isinstance(data, str):
            data = data.encode("utf-8")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(addr, pw)
        s.send_message(msg)
    return to
