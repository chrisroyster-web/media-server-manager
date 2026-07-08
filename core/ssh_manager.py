# core/ssh_manager.py

import paramiko
import threading
import os
import sys


def known_hosts_path():
    """
    Path to our trust-on-first-use host key store (OpenSSH known_hosts format).
    Lives next to config.json: assets/ in dev, %APPDATA% when frozen.
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = os.path.join(appdata, "All Clear Server Services")
    else:
        base = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "known_hosts")


def configure_host_key_verification(client):
    """
    Trust-on-first-use host key checking, shared by SSHManager and any code
    that opens its own paramiko client (e.g. the multi-server aggregate poll).

    Known keys are persisted to disk and reloaded on every connection, so a
    host key that changes between connections raises paramiko.BadHostKeyException
    instead of being silently re-trusted (which is what a bare AutoAddPolicy
    does — it never compares against a previous connection, so it can't
    actually detect a MITM). Genuinely new hosts are still auto-trusted on
    first use, same as a normal SSH client's default behavior.
    """
    path = known_hosts_path()
    if os.path.exists(path):
        try:
            client.load_host_keys(path)
        except Exception:
            pass
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


def persist_host_keys(client):
    """Save any newly-trusted host keys so future connections can verify against them."""
    try:
        client.save_host_keys(known_hosts_path())
    except Exception:
        pass


def forget_host_key(host, port=22):
    """
    Remove a stored host key so the next connection re-trusts on first use.
    Use only after independently verifying the server's new key out-of-band
    (e.g. the server's OS/SSH host keys were legitimately regenerated).
    """
    path = known_hosts_path()
    if not os.path.exists(path):
        return
    keys = paramiko.hostkeys.HostKeys()
    try:
        keys.load(path)
    except Exception:
        return
    lookup = host if int(port) == 22 else "[{}]:{}".format(host, port)
    if lookup in keys:
        del keys[lookup]
        keys.save(path)


class SSHManager:
    """
    Handles SSH connections, dual-mode authentication,
    command execution, SFTP file transfers, safe disconnects,
    and auto-reconnect.
    """

    def __init__(self):
        self.client        = None
        self.connected     = False
        # Guards connect()/disconnect() state transitions only — NOT command
        # execution. Paramiko's Transport safely multiplexes concurrent
        # exec_command() calls from multiple threads, each getting its own
        # Channel, so run()/run_sudo() don't fully serialize on this lock.
        self.lock          = threading.Lock()
        self._sftp_lock    = threading.Lock()  # guards the cached SFTP client
        # Bounds how many commands can be in flight at once. Fully unbounded
        # concurrency runs into sshd's MaxSessions limit (10 by default) and
        # exec_command() starts failing with "open failed: Connect failed";
        # 6 gives real parallelism (vs. the old one-at-a-time lock, which is
        # what let one slow command like `docker pull` stall every other tab
        # and watchdog) while staying comfortably under that ceiling.
        self._cmd_semaphore = threading.Semaphore(6)
        self._connect_args = None   # stored on success for reconnect
        self._sftp         = None   # cached SFTP client

    # ---------------------------------------------------------
    # CONNECTION
    # ---------------------------------------------------------
    def connect(self, host, port, username, password=None, key_path=None):
        with self.lock:
            try:
                client = paramiko.SSHClient()
                configure_host_key_verification(client)

                if password:
                    client.connect(
                        hostname=host, port=int(port),
                        username=username, password=password, timeout=10,
                    )
                else:
                    if key_path is None:
                        key_path = os.path.expanduser("~/.ssh/id_rsa")
                    if not os.path.exists(key_path):
                        raise FileNotFoundError("SSH key not found: " + key_path)
                    key = paramiko.RSAKey.from_private_key_file(key_path)
                    client.connect(
                        hostname=host, port=int(port),
                        username=username, pkey=key, timeout=10,
                    )

                persist_host_keys(client)

                self.client         = client
                self.connected      = True
                self._connect_args = {
                    "host": host, "port": port, "username": username,
                    "password": password, "key_path": key_path,
                }
                return True

            except paramiko.BadHostKeyException as e:
                self.connected = False
                return (
                    "SSH HOST KEY MISMATCH for {} — the server's identity does not match "
                    "the key we trusted previously. This could mean the server was "
                    "reinstalled, OR that someone is intercepting the connection "
                    "(man-in-the-middle). Refusing to connect. If you're certain the "
                    "server's key legitimately changed, clear the saved key for this "
                    "host before reconnecting.".format(e.hostname)
                )
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
        with self.lock:
            # Close cached SFTP first
            with self._sftp_lock:
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
    # RUN COMMAND
    # ---------------------------------------------------------
    def run(self, command):
        """
        Bounded-concurrent, not fully serialized: paramiko multiplexes
        exec_command() calls over one connection safely (each gets its own
        Channel), so multiple tabs/watchdogs can have commands in flight at
        the same time instead of queuing behind whichever one is slowest.
        """
        if not self.connected:
            return "", "Not connected", 1
        with self._cmd_semaphore:
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
        """Run a command with sudo, feeding the stored password via stdin.
        Falls back to sudo -n (requires NOPASSWD) when no password is stored.
        Bounded-concurrent, not fully serialized — see run()."""
        if not self.connected:
            return "", "Not connected", 1
        with self._cmd_semaphore:
            try:
                password = (self._connect_args or {}).get("password") or ""
                if password:
                    stdin, stdout, stderr = self.client.exec_command(f"sudo -S {command}")
                    stdin.write(password + "\n")
                    stdin.flush()
                else:
                    stdin, stdout, stderr = self.client.exec_command(f"sudo -n {command}")
                stdin.channel.shutdown_write()
                out  = stdout.read().decode(errors="ignore")
                err  = stderr.read().decode(errors="ignore")
                code = stdout.channel.recv_exit_status()
                # Strip sudo password-prompt lines from both streams
                out = self._strip_sudo_prompts(out)
                err = self._strip_sudo_prompts(err)
                return out, err, code
            except Exception as e:
                return "", str(e), 1

    @staticmethod
    def _strip_sudo_prompts(text):
        # The real sudo prompt format is "[sudo] password for <user>: "
        # (closing bracket, then a space) — "[sudo:" never actually
        # matches that and let every prompt line straight through to the
        # UI. Found via tests/test_ssh_manager.py.
        return "\n".join(
            l for l in text.splitlines()
            if not (l.strip().startswith("[sudo]") or
                    l.strip().lower().startswith("password:") or
                    l.strip().lower().startswith("sudo:"))
        )

    # ---------------------------------------------------------
    # FILE UPLOAD (stdin pipe — no SFTP subsystem needed)
    # ---------------------------------------------------------
    def put_file(self, local_path, remote_path):
        """Write a local file to the server by piping its content via sudo tee."""
        if not self.connected:
            return "", "Not connected", 1
        with self._cmd_semaphore:
            try:
                with open(local_path, "rb") as f:
                    content = f.read()
                cmd = "sudo tee '{}' > /dev/null && sudo chmod +x '{}'".format(
                    remote_path, remote_path)
                stdin, stdout, stderr = self.client.exec_command(cmd)
                stdin.write(content)
                stdin.channel.shutdown_write()
                out  = stdout.read().decode(errors="ignore")
                err  = stderr.read().decode(errors="ignore")
                code = stdout.channel.recv_exit_status()
                return out, err, code
            except Exception as e:
                return "", str(e), 1

    # ---------------------------------------------------------
    # SFTP
    # ---------------------------------------------------------
    def get_sftp(self):
        """Return a cached (or fresh) SFTP client. Locked so two threads
        racing on a dead cached client don't both open a replacement."""
        if not self.connected:
            raise Exception("Not connected")
        with self._sftp_lock:
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
