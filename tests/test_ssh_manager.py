from unittest.mock import MagicMock, patch

import paramiko
import pytest

from core.ssh_manager import SSHManager, forget_host_key, known_hosts_path


def _fake_exec_result(stdout_text="", stderr_text="", exit_code=0):
    """Build the (stdin, stdout, stderr) triple exec_command() returns."""
    stdin = MagicMock()
    stdout = MagicMock()
    stderr = MagicMock()
    stdout.read.return_value = stdout_text.encode()
    stderr.read.return_value = stderr_text.encode()
    stdout.channel.recv_exit_status.return_value = exit_code
    return stdin, stdout, stderr


# ---------------------------------------------------------------------------
# Not connected — every command method should short-circuit, not touch paramiko
# ---------------------------------------------------------------------------

def test_run_when_not_connected():
    ssh = SSHManager()
    assert ssh.run("echo hi") == ("", "Not connected", 1)


def test_run_sudo_when_not_connected():
    ssh = SSHManager()
    assert ssh.run_sudo("echo hi") == ("", "Not connected", 1)


def test_put_file_when_not_connected():
    ssh = SSHManager()
    assert ssh.put_file("local", "remote") == ("", "Not connected", 1)


def test_get_sftp_when_not_connected_raises():
    ssh = SSHManager()
    with pytest.raises(Exception):
        ssh.get_sftp()


def test_shutdown_when_not_connected():
    ssh = SSHManager()
    assert ssh.shutdown() == "Not connected"


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

def test_connect_success_with_password():
    fake_client = MagicMock()
    with patch("paramiko.SSHClient", return_value=fake_client):
        ssh = SSHManager()
        result = ssh.connect("host1", 22, "user1", password="secret")

    assert result is True
    assert ssh.connected is True
    assert ssh.client is fake_client
    fake_client.connect.assert_called_once()
    _, kwargs = fake_client.connect.call_args
    assert kwargs["password"] == "secret"
    assert "pkey" not in kwargs
    assert ssh._connect_args == {
        "host": "host1", "port": 22, "username": "user1",
        "password": "secret", "key_path": None,
    }


def test_connect_success_with_key(tmp_path):
    key_path = tmp_path / "id_rsa"
    key_path.write_text("not a real key, just needs to exist")

    fake_client = MagicMock()
    fake_key = MagicMock()
    with patch("paramiko.SSHClient", return_value=fake_client), \
         patch("paramiko.RSAKey.from_private_key_file", return_value=fake_key):
        ssh = SSHManager()
        result = ssh.connect("host1", 22, "user1", key_path=str(key_path))

    assert result is True
    assert ssh.connected is True
    _, kwargs = fake_client.connect.call_args
    assert kwargs["pkey"] is fake_key
    assert "password" not in kwargs


def test_connect_missing_key_file_fails_gracefully(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    fake_client = MagicMock()
    with patch("paramiko.SSHClient", return_value=fake_client):
        ssh = SSHManager()
        result = ssh.connect("host1", 22, "user1", key_path=missing)

    assert ssh.connected is False
    assert "SSH key not found" in result


def test_connect_bad_host_key_returns_warning_and_stays_disconnected():
    fake_client = MagicMock()
    fake_client.connect.side_effect = paramiko.BadHostKeyException(
        "host1", MagicMock(), MagicMock())
    with patch("paramiko.SSHClient", return_value=fake_client):
        ssh = SSHManager()
        result = ssh.connect("host1", 22, "user1", password="secret")

    assert ssh.connected is False
    assert "MISMATCH" in result
    assert "man-in-the-middle" in result


def test_connect_generic_exception_returns_message_and_stays_disconnected():
    fake_client = MagicMock()
    fake_client.connect.side_effect = OSError("network unreachable")
    with patch("paramiko.SSHClient", return_value=fake_client):
        ssh = SSHManager()
        result = ssh.connect("host1", 22, "user1", password="secret")

    assert ssh.connected is False
    assert "network unreachable" in result


# ---------------------------------------------------------------------------
# run() / run_sudo()
# ---------------------------------------------------------------------------

def _connected_manager():
    fake_client = MagicMock()
    with patch("paramiko.SSHClient", return_value=fake_client):
        ssh = SSHManager()
        ssh.connect("host1", 22, "user1", password="secret")
    return ssh, fake_client


def test_run_returns_stdout_stderr_and_exit_code():
    ssh, fake_client = _connected_manager()
    fake_client.exec_command.return_value = _fake_exec_result("hello\n", "", 0)

    out, err, code = ssh.run("echo hello")
    assert out == "hello\n"
    assert err == ""
    assert code == 0
    fake_client.exec_command.assert_called_with("echo hello")


def test_run_handles_exec_command_exception():
    ssh, fake_client = _connected_manager()
    fake_client.exec_command.side_effect = OSError("channel closed")

    out, err, code = ssh.run("echo hello")
    assert out == ""
    assert "channel closed" in err
    assert code == 1


def test_run_sudo_with_stored_password_feeds_stdin_and_uses_dash_capital_s():
    ssh, fake_client = _connected_manager()
    stdin, stdout, stderr = _fake_exec_result("done\n", "", 0)
    fake_client.exec_command.return_value = (stdin, stdout, stderr)

    out, err, code = ssh.run_sudo("systemctl restart sonarr")

    called_cmd = fake_client.exec_command.call_args[0][0]
    assert called_cmd == "sudo -S systemctl restart sonarr"
    stdin.write.assert_called_once_with("secret\n")
    # _strip_sudo_prompts always rebuilds via splitlines()/join(), which
    # drops a trailing newline even when there's nothing to actually strip
    assert out == "done"
    assert code == 0


def test_run_sudo_without_stored_password_uses_dash_n(tmp_path):
    key_path = tmp_path / "id_rsa"
    key_path.write_text("fake key contents")
    fake_client = MagicMock()
    with patch("paramiko.SSHClient", return_value=fake_client), \
         patch("paramiko.RSAKey.from_private_key_file", return_value=MagicMock()):
        ssh = SSHManager()
        connected = ssh.connect("host1", 22, "user1", key_path=str(key_path))
    assert connected is True  # sanity check the setup actually connected

    stdin, stdout, stderr = _fake_exec_result("done\n", "", 0)
    fake_client.exec_command.return_value = (stdin, stdout, stderr)

    ssh.run_sudo("systemctl restart sonarr")

    called_cmd = fake_client.exec_command.call_args[0][0]
    assert called_cmd == "sudo -n systemctl restart sonarr"
    stdin.write.assert_not_called()


def test_run_sudo_strips_password_prompt_lines_from_output():
    ssh, fake_client = _connected_manager()
    raw_out = "[sudo] password for user1:\nactual output line\n"
    fake_client.exec_command.return_value = _fake_exec_result(raw_out, "", 0)

    out, _, _ = ssh.run_sudo("some command")
    assert "password for user1" not in out
    assert "actual output line" in out


def test_strip_sudo_prompts_removes_various_prompt_formats():
    text = (
        "[sudo] password for user:\n"
        "Password:\n"
        "sudo: unable to resolve host\n"
        "real output line 1\n"
        "real output line 2\n"
    )
    result = SSHManager._strip_sudo_prompts(text)
    lines = result.splitlines()
    assert lines == ["real output line 1", "real output line 2"]


# ---------------------------------------------------------------------------
# is_alive / disconnect / reconnect
# ---------------------------------------------------------------------------

def test_is_alive_true_when_transport_active():
    ssh, fake_client = _connected_manager()
    fake_client.get_transport.return_value.is_active.return_value = True
    assert ssh.is_alive() is True


def test_is_alive_false_when_transport_inactive():
    ssh, fake_client = _connected_manager()
    fake_client.get_transport.return_value.is_active.return_value = False
    assert ssh.is_alive() is False


def test_is_alive_false_on_exception():
    ssh = SSHManager()  # client is None
    assert ssh.is_alive() is False


def test_disconnect_closes_client_and_resets_state():
    ssh, fake_client = _connected_manager()
    ssh.disconnect()
    fake_client.close.assert_called_once()
    assert ssh.connected is False


def test_reconnect_with_no_previous_connection():
    ssh = SSHManager()
    assert ssh.reconnect() == "No previous connection stored"


def test_reconnect_uses_stored_args():
    ssh, fake_client = _connected_manager()
    ssh.disconnect()
    with patch("paramiko.SSHClient", return_value=fake_client):
        result = ssh.reconnect()
    assert result is True
    assert ssh.connected is True


# ---------------------------------------------------------------------------
# Host key trust store (real file I/O, no paramiko.SSHClient mocking needed)
# ---------------------------------------------------------------------------

def test_forget_host_key_removes_a_stored_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.ssh_manager.known_hosts_path", lambda: str(tmp_path / "known_hosts"))

    keys = paramiko.hostkeys.HostKeys()
    fake_key = paramiko.RSAKey.generate(1024)
    keys.add("192.168.1.50", "ssh-rsa", fake_key)
    keys.save(str(tmp_path / "known_hosts"))

    assert "192.168.1.50" in paramiko.hostkeys.HostKeys(str(tmp_path / "known_hosts"))

    forget_host_key("192.168.1.50")

    reloaded = paramiko.hostkeys.HostKeys(str(tmp_path / "known_hosts"))
    assert "192.168.1.50" not in reloaded


def test_forget_host_key_on_missing_file_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.ssh_manager.known_hosts_path", lambda: str(tmp_path / "does_not_exist"))
    forget_host_key("192.168.1.50")  # should not raise


def test_known_hosts_path_is_stable_and_creates_parent_dir():
    p1 = known_hosts_path()
    p2 = known_hosts_path()
    assert p1 == p2
    import os
    assert os.path.isdir(os.path.dirname(p1))
