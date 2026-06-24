# core/ssh_manager.py

import paramiko
import threading
import os


class SSHManager:
    """
    Handles SSH connections, dual-mode authentication,
    command execution, SFTP file transfers, safe disconnects,
    and auto-reconnect.
    """

    def __init__(self):
        self.client        = None
        self.connected     = False
        self.lock          = threading.Lock()
        self._connect_args = None   # stored on success for reconnect
        self._sftp         = None   # cached SFTP client

    # ---------------------------------------------------------
    # CONNECTION
    # ---------------------------------------------------------
    def connect(self, host, port, username, password=None, key_path=None):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if password:
                self.client.connect(
                    hostname=host, port=int(port),
                    username=username, password=password, timeout=10,
                )
            else:
                if key_path is None:
                    key_path = os.path.expanduser("~/.ssh/id_rsa")
                if not os.path.exists(key_path):
                    raise FileNotFoundError("SSH key not found: " + key_path)
                key = paramiko.RSAKey.from_private_key_file(key_path)
                self.client.connect(
                    hostname=host, port=int(port),
                    username=username, pkey=key, timeout=10,
                )

            self.connected     = True
            self._connect_args = {
                "host": host, "port": port, "username": username,
                "password": password, "key_path": key_path,
            }
            return True

        except Exception as e:
            self.connected = False
            return str(e)

    # ---------------------------------------------------------
    # LIVENESS + RECONNECT
    # ---------------------------------------------------------
    def is_alive(self):
        """Return True if the SSH transport is still active."""
        try:
            t = self.client.get_transport()
            return t is not None and t.is_active()
        except Exception:
            return False

    def reconnect(self):
        """Re-connect using the last successful connection args."""
        if not self._connect_args:
            return "No previous connection stored"
        self.disconnect()
        return self.connect(**self._connect_args)

    # ---------------------------------------------------------
    # DISCONNECT
    # ---------------------------------------------------------
    def disconnect(self):
        # Close cached SFTP first
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        finally:
            self._sftp = None

        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        finally:
            self.connected = False

    # ---------------------------------------------------------
    # RUN COMMAND (THREAD-SAFE)
    # ---------------------------------------------------------
    def run(self, command):
        if not self.connected:
            return "", "Not connected", 1
        with self.lock:
            try:
                stdin, stdout, stderr = self.client.exec_command(command)
                out  = stdout.read().decode(errors="ignore")
                err  = stderr.read().decode(errors="ignore")
                code = stdout.channel.recv_exit_status()
                return out, err, code
            except Exception as e:
                return "", str(e), 1

    # ---------------------------------------------------------
    # RUN AS SUDO
    # ---------------------------------------------------------
    def run_sudo(self, command):
        return self.run("sudo " + command)

    # ---------------------------------------------------------
    # SFTP
    # ---------------------------------------------------------
    def get_sftp(self):
        """Return a cached (or fresh) SFTP client."""
        if not self.connected:
            raise Exception("Not connected")
        try:
            # Reuse cached client if the channel is still open
            if self._sftp is not None:
                self._sftp.stat(".")  # lightweight liveness check
                return self._sftp
        except Exception:
            self._sftp = None

        self._sftp = self.client.open_sftp()
        return self._sftp

    # ---------------------------------------------------------
    # SHUTDOWN
    # ---------------------------------------------------------
    def shutdown(self):
        if not self.connected:
            return "Not connected"
        try:
            self.run_sudo("poweroff")
            return "Shutdown command sent"
        except Exception as e:
            return str(e)
