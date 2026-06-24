# core/notification_manager.py
"""
Sends alert notifications via SMTP email or ntfy.sh push.
All sends happen in a background thread so they never block the UI.
"""

import smtplib
import ssl
import threading
import urllib.request
import urllib.error
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class NotificationManager:

    def __init__(self, config_manager):
        self.cfg = config_manager
        self._last_alerts = set()   # avoid repeat-spamming the same alert

    # =========================================================
    # PUBLIC
    # =========================================================
    def notify(self, alerts: list):
        """
        Call with the active alert strings from fire_alerts().
        Only sends a notification when alerts are NEW (not seen in the
        previous call) to avoid flooding.
        """
        if not alerts:
            self._last_alerts.clear()
            return

        new_alerts = [a for a in alerts if a not in self._last_alerts]
        if not new_alerts:
            return

        self._last_alerts = set(alerts)
        threading.Thread(
            target=self._send_all,
            args=(new_alerts,),
            daemon=True,
        ).start()

    # =========================================================
    # INTERNAL
    # =========================================================
    def _send_all(self, alerts):
        subject = "⚠ Media Server Alert"
        body    = "Active alerts:\n\n" + "\n".join("• " + a for a in alerts)

        if self.cfg.notify_ntfy_enabled and self.cfg.notify_ntfy_topic:
            self._send_ntfy(subject, body)

        if self.cfg.notify_email_enabled and self.cfg.notify_email_to:
            self._send_email(subject, body)

    # ---- ntfy.sh ------------------------------------------------
    def _send_ntfy(self, title, body):
        topic    = self.cfg.notify_ntfy_topic.strip()
        server   = self.cfg.notify_ntfy_server.strip().rstrip("/") or "https://ntfy.sh"
        url      = "{}/{}".format(server, topic)
        token    = self.cfg.notify_ntfy_token.strip()
        headers  = {
            "Title":        title.encode(),
            "Priority":     b"high",
            "Tags":         b"warning",
            "Content-Type": b"text/plain",
        }
        if token:
            headers["Authorization"] = ("Bearer " + token).encode()
        try:
            req = urllib.request.Request(
                url,
                data=body.encode(),
                headers={k: v for k, v in headers.items()},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception:
            pass  # silent fail — don't crash the app over a notification

    # ---- SMTP email ---------------------------------------------
    def _send_email(self, subject, body):
        host   = self.cfg.notify_smtp_host.strip()
        port   = int(self.cfg.notify_smtp_port or 587)
        user   = self.cfg.notify_smtp_user.strip()
        pw     = self.cfg.notify_smtp_pass.strip()
        to     = self.cfg.notify_email_to.strip()
        frm    = user or "mediaserver@localhost"

        if not host or not to:
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = frm
        msg["To"]      = to
        msg.attach(MIMEText(body, "plain"))

        try:
            ctx = ssl.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=10) as s:
                    if user and pw:
                        s.login(user, pw)
                    s.sendmail(frm, [to], msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=10) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    if user and pw:
                        s.login(user, pw)
                    s.sendmail(frm, [to], msg.as_string())
        except Exception:
            pass
