import smtplib
from unittest.mock import MagicMock, patch

from core.notification_manager import NotificationManager


class _FakeConfig:
    def __init__(self):
        self.notify_ntfy_enabled = False
        self.notify_ntfy_topic = ""
        self.notify_ntfy_server = "https://ntfy.sh"
        self.notify_ntfy_token = ""
        self.notify_email_enabled = False
        self.notify_email_to = ""
        self.notify_smtp_host = ""
        self.notify_smtp_port = "587"
        self.notify_smtp_user = ""
        self.notify_smtp_pass = ""
        self.notify_apprise_enabled = False
        self._apprise_urls = []

    def get_apprise_url_list(self):
        return self._apprise_urls


class _SyncThread:
    """Stand-in for threading.Thread that runs synchronously, so tests
    can assert on side effects without waiting on a background thread."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


# ---------------------------------------------------------------------------
# notify() dedup logic
# ---------------------------------------------------------------------------

def test_notify_sends_on_new_alerts(monkeypatch):
    nm = NotificationManager(_FakeConfig())
    monkeypatch.setattr("core.notification_manager.threading.Thread", _SyncThread)
    sent = []
    monkeypatch.setattr(nm, "_send_all", lambda alerts: sent.append(alerts))

    nm.notify(["CPU high"])
    assert sent == [["CPU high"]]


def test_notify_does_not_resend_identical_alerts(monkeypatch):
    nm = NotificationManager(_FakeConfig())
    monkeypatch.setattr("core.notification_manager.threading.Thread", _SyncThread)
    sent = []
    monkeypatch.setattr(nm, "_send_all", lambda alerts: sent.append(alerts))

    nm.notify(["CPU high"])
    nm.notify(["CPU high"])  # same alert again — should not resend
    assert len(sent) == 1


def test_notify_resends_when_a_new_alert_is_added(monkeypatch):
    nm = NotificationManager(_FakeConfig())
    monkeypatch.setattr("core.notification_manager.threading.Thread", _SyncThread)
    sent = []
    monkeypatch.setattr(nm, "_send_all", lambda alerts: sent.append(alerts))

    nm.notify(["CPU high"])
    nm.notify(["CPU high", "RAM high"])
    assert len(sent) == 2
    assert sent[1] == ["RAM high"]  # only the genuinely new one


def test_notify_with_empty_alerts_clears_state_without_sending(monkeypatch):
    nm = NotificationManager(_FakeConfig())
    monkeypatch.setattr("core.notification_manager.threading.Thread", _SyncThread)
    sent = []
    monkeypatch.setattr(nm, "_send_all", lambda alerts: sent.append(alerts))

    nm.notify(["CPU high"])
    nm.notify([])
    assert len(sent) == 1  # the empty call didn't trigger a send

    # after clearing, the same alert is "new" again
    nm.notify(["CPU high"])
    assert len(sent) == 2


# ---------------------------------------------------------------------------
# send_rule_alert_sync() — per-channel gating
# ---------------------------------------------------------------------------

def test_send_rule_alert_sync_only_sends_to_requested_and_enabled_channels(monkeypatch):
    cfg = _FakeConfig()
    cfg.notify_ntfy_enabled = True
    cfg.notify_ntfy_topic = "alerts"
    cfg.notify_email_enabled = True
    cfg.notify_email_to = "me@example.com"
    nm = NotificationManager(cfg)

    calls = []
    monkeypatch.setattr(nm, "_send_ntfy", lambda t, b: calls.append("ntfy"))
    monkeypatch.setattr(nm, "_send_email", lambda t, b: calls.append("email"))
    monkeypatch.setattr(nm, "_send_apprise", lambda t, b: calls.append("apprise"))

    nm.send_rule_alert_sync("Title", "Body", channels=["ntfy"])
    assert calls == ["ntfy"]


def test_send_rule_alert_sync_skips_channel_disabled_in_config(monkeypatch):
    cfg = _FakeConfig()
    cfg.notify_ntfy_enabled = False  # disabled despite being requested
    nm = NotificationManager(cfg)
    calls = []
    monkeypatch.setattr(nm, "_send_ntfy", lambda t, b: calls.append("ntfy"))

    nm.send_rule_alert_sync("Title", "Body", channels=["ntfy"])
    assert calls == []


def test_send_rule_alert_sync_skips_ntfy_without_topic(monkeypatch):
    cfg = _FakeConfig()
    cfg.notify_ntfy_enabled = True
    cfg.notify_ntfy_topic = ""  # enabled but not configured
    nm = NotificationManager(cfg)
    calls = []
    monkeypatch.setattr(nm, "_send_ntfy", lambda t, b: calls.append("ntfy"))

    nm.send_rule_alert_sync("Title", "Body", channels=["ntfy"])
    assert calls == []


# ---------------------------------------------------------------------------
# _send_ntfy
# ---------------------------------------------------------------------------

def test_send_ntfy_posts_to_the_configured_topic_url():
    cfg = _FakeConfig()
    cfg.notify_ntfy_server = "https://ntfy.sh"
    cfg.notify_ntfy_topic = "mytopic"
    nm = NotificationManager(cfg)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = req.headers
        return MagicMock()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        nm._send_ntfy("Alert Title", "Alert body")

    assert captured["url"] == "https://ntfy.sh/mytopic"
    assert captured["data"] == b"Alert body"


def test_send_ntfy_includes_bearer_token_when_configured():
    cfg = _FakeConfig()
    cfg.notify_ntfy_topic = "mytopic"
    cfg.notify_ntfy_token = "secrettoken"
    nm = NotificationManager(cfg)

    captured = {}
    with patch("urllib.request.urlopen",
              side_effect=lambda req, timeout=None: captured.setdefault("req", req)):
        nm._send_ntfy("Title", "Body")

    assert captured["req"].headers["Authorization"] == b"Bearer secrettoken"


def test_send_ntfy_silently_swallows_network_errors():
    cfg = _FakeConfig()
    cfg.notify_ntfy_topic = "mytopic"
    nm = NotificationManager(cfg)
    with patch("urllib.request.urlopen", side_effect=OSError("no network")):
        nm._send_ntfy("Title", "Body")  # must not raise


# ---------------------------------------------------------------------------
# _send_email
# ---------------------------------------------------------------------------

def test_send_email_does_nothing_without_host_or_recipient():
    cfg = _FakeConfig()
    nm = NotificationManager(cfg)
    with patch("smtplib.SMTP") as smtp_cls, patch("smtplib.SMTP_SSL") as ssl_cls:
        nm._send_email("Subject", "Body")
    smtp_cls.assert_not_called()
    ssl_cls.assert_not_called()


def test_send_email_uses_starttls_for_non_ssl_port():
    cfg = _FakeConfig()
    cfg.notify_smtp_host = "smtp.example.com"
    cfg.notify_smtp_port = "587"
    cfg.notify_email_to = "me@example.com"
    cfg.notify_smtp_user = "user@example.com"
    cfg.notify_smtp_pass = "pw"
    nm = NotificationManager(cfg)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    with patch("smtplib.SMTP", return_value=fake_smtp) as smtp_cls:
        nm._send_email("Subject", "Body")

    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
    fake_smtp.starttls.assert_called_once()
    fake_smtp.login.assert_called_once_with("user@example.com", "pw")
    fake_smtp.sendmail.assert_called_once()


def test_send_email_uses_ssl_for_port_465():
    cfg = _FakeConfig()
    cfg.notify_smtp_host = "smtp.example.com"
    cfg.notify_smtp_port = "465"
    cfg.notify_email_to = "me@example.com"
    nm = NotificationManager(cfg)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    with patch("smtplib.SMTP_SSL", return_value=fake_smtp) as ssl_cls:
        nm._send_email("Subject", "Body")

    ssl_cls.assert_called_once()
    fake_smtp.sendmail.assert_called_once()


def test_send_email_skips_login_without_credentials():
    cfg = _FakeConfig()
    cfg.notify_smtp_host = "smtp.example.com"
    cfg.notify_email_to = "me@example.com"
    nm = NotificationManager(cfg)

    fake_smtp = MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    with patch("smtplib.SMTP", return_value=fake_smtp):
        nm._send_email("Subject", "Body")
    fake_smtp.login.assert_not_called()


def test_send_email_silently_swallows_smtp_errors():
    cfg = _FakeConfig()
    cfg.notify_smtp_host = "smtp.example.com"
    cfg.notify_email_to = "me@example.com"
    nm = NotificationManager(cfg)
    with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("boom")):
        nm._send_email("Subject", "Body")  # must not raise


# ---------------------------------------------------------------------------
# _send_apprise
# ---------------------------------------------------------------------------

def test_send_apprise_does_nothing_without_urls():
    cfg = _FakeConfig()
    nm = NotificationManager(cfg)
    with patch("core.notification_manager.apprise") as fake_apprise_module:
        nm._send_apprise("Title", "Body")
    fake_apprise_module.Apprise.assert_not_called()


def test_send_apprise_adds_each_url_and_notifies():
    cfg = _FakeConfig()
    cfg._apprise_urls = ["discord://webhook1", "tgram://token/chatid"]
    nm = NotificationManager(cfg)

    fake_instance = MagicMock()
    with patch("core.notification_manager.apprise") as fake_apprise_module:
        fake_apprise_module.Apprise.return_value = fake_instance
        nm._send_apprise("Title", "Body")

    assert fake_instance.add.call_count == 2
    fake_instance.notify.assert_called_once_with(title="Title", body="Body")


def test_send_apprise_does_nothing_when_module_unavailable(monkeypatch):
    monkeypatch.setattr("core.notification_manager.apprise", None)
    cfg = _FakeConfig()
    cfg._apprise_urls = ["discord://webhook1"]
    nm = NotificationManager(cfg)
    nm._send_apprise("Title", "Body")  # must not raise
