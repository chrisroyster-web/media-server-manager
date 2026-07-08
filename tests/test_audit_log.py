from unittest.mock import MagicMock

import ui.sftp_tab as sftp_tab_module


def _last_audit_entries(app, n=5):
    return app.metrics_store.get_audit_log(limit=n)


def test_audit_log_records_and_reads_back(app):
    app.audit_log("test.action", "some-target", detail="detail text", result="ok")
    entries = _last_audit_entries(app, 1)
    assert entries
    assert entries[0]["action"] == "test.action"
    assert entries[0]["target"] == "some-target"
    assert entries[0]["result"] == "ok"


def test_config_save_and_apply_is_audited(app):
    app.config_tab._save()
    entries = _last_audit_entries(app, 5)
    actions = [e["action"] for e in entries]
    assert "config.save_and_apply" in actions


def test_vpn_toggle_is_audited_only_on_change(app):
    ct = app.config_tab
    ct.vpn_enabled_var.set(False)
    ct._save()
    before_count = len(app.metrics_store.get_audit_log(limit=500))

    ct.vpn_enabled_var.set(True)
    ct._save()
    after_toggle = app.metrics_store.get_audit_log(limit=500)
    assert len(after_toggle) > before_count
    assert after_toggle[0]["action"] == "vpn.enable"

    # saving again with no change shouldn't emit a second vpn.* entry
    count_after_first_enable = len(after_toggle)
    ct._save()
    after_noop_save = app.metrics_store.get_audit_log(limit=500)
    new_actions = [e["action"] for e in after_noop_save[:len(after_noop_save) - count_after_first_enable]]
    assert "vpn.enable" not in new_actions
    assert "vpn.disable" not in new_actions

    ct.vpn_enabled_var.set(False)
    ct._save()
    final = app.metrics_store.get_audit_log(limit=500)
    assert final[0]["action"] == "vpn.disable"


def test_sftp_upload_is_audited(app, monkeypatch, tmp_path):
    tab = app.sftp_tab
    local_file = tmp_path / "upload_me.txt"
    local_file.write_text("hello")

    fake_ssh = MagicMock()
    fake_ssh.connected = True
    fake_sftp = MagicMock()
    fake_ssh.get_sftp.return_value = fake_sftp
    monkeypatch.setattr(app, "ssh", fake_ssh)

    monkeypatch.setattr(sftp_tab_module.filedialog, "askopenfilename",
                        lambda **kw: str(local_file))

    class SyncThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(sftp_tab_module.threading, "Thread", SyncThread)

    tab._current_path = "/remote/dir"
    tab._upload()
    app.update()

    entries = app.metrics_store.get_audit_log(limit=5)
    assert entries[0]["action"] == "sftp.upload"
    assert entries[0]["result"] == "ok"
    fake_sftp.put.assert_called_once()


def test_sftp_upload_failure_is_audited(app, monkeypatch, tmp_path):
    tab = app.sftp_tab
    local_file = tmp_path / "upload_me.txt"
    local_file.write_text("hello")

    fake_ssh = MagicMock()
    fake_ssh.connected = True
    fake_sftp = MagicMock()
    fake_sftp.put.side_effect = OSError("connection lost")
    fake_ssh.get_sftp.return_value = fake_sftp
    monkeypatch.setattr(app, "ssh", fake_ssh)

    monkeypatch.setattr(sftp_tab_module.filedialog, "askopenfilename",
                        lambda **kw: str(local_file))

    class SyncThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(sftp_tab_module.threading, "Thread", SyncThread)

    tab._current_path = "/remote/dir"
    tab._upload()
    app.update()

    entries = app.metrics_store.get_audit_log(limit=5)
    assert entries[0]["action"] == "sftp.upload"
    assert entries[0]["result"] == "fail"
