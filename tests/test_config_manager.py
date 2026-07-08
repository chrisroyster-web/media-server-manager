import json

import pytest

from core.config_manager import ConfigManager

# Captured at module load (before any fixture runs) so it's the real
# implementation regardless of what other test modules do to the class.
# conftest.py's session-scoped `app` fixture permanently replaces
# ConfigManager.save with a no-op (a plain assignment, not monkeypatch,
# since it needs to outlive every individual test) so the shared GUI
# fixture never touches the real assets/config.json — but that leaks
# into any test file that happens to run afterward in the same session
# unless it's explicitly undone here.
_REAL_SAVE = ConfigManager.save


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigManager, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(ConfigManager, "save", _REAL_SAVE)
    return ConfigManager()


def test_fresh_config_file_is_created_with_defaults(cfg):
    assert cfg.get("sidebar_collapsed") is False
    assert cfg.get("dashboard_refresh_interval") == 30


def test_get_set_round_trips_and_persists_to_disk(cfg):
    cfg.set("theme_mode", "light")
    assert cfg.get("theme_mode") == "light"

    on_disk = json.loads(open(cfg.CONFIG_PATH).read())
    assert on_disk["theme_mode"] == "light"


def test_get_returns_default_for_missing_key(cfg):
    assert cfg.get("no_such_key", "fallback") == "fallback"


def test_per_server_setting_falls_back_to_global_when_no_active_server(cfg):
    """With no servers configured, _gs/_ss should fall back to the plain
    global config dict rather than raising."""
    cfg._ss("dashboard_refresh_interval", 45)
    assert cfg._gs("dashboard_refresh_interval") == 45
    assert cfg.config["dashboard_refresh_interval"] == 45


def test_per_server_setting_is_scoped_to_the_active_server(cfg):
    cfg.upsert_server("host-a")
    cfg.upsert_server("host-b")
    cfg.set_active_server_index(0)
    cfg._ss("sonarr_apikey", "key-for-a")

    cfg.set_active_server_index(1)
    cfg._ss("sonarr_apikey", "key-for-b")

    cfg.set_active_server_index(0)
    assert cfg._gs("sonarr_apikey") == "key-for-a"
    cfg.set_active_server_index(1)
    assert cfg._gs("sonarr_apikey") == "key-for-b"


def test_upsert_server_adds_new_and_updates_existing(cfg):
    cfg.upsert_server("myhost", username="alice", port="22")
    servers = cfg.get_servers()
    assert len(servers) == 1
    assert servers[0]["host"] == "myhost"
    assert servers[0]["username"] == "alice"

    # Re-upserting the same host updates in place rather than duplicating
    cfg.upsert_server("myhost", username="bob")
    servers = cfg.get_servers()
    assert len(servers) == 1
    assert servers[0]["username"] == "bob"


def test_upsert_server_does_not_overwrite_credentials_with_blank_values(cfg):
    cfg.upsert_server("myhost", username="alice", password="secret123")
    cfg.upsert_server("myhost", username="", password="")
    servers = cfg.get_servers()
    assert servers[0]["username"] == "alice"
    assert servers[0]["password"] == "secret123"


def test_get_active_server_returns_none_when_no_servers(cfg):
    assert cfg.get_active_server() is None


def test_get_active_server_returns_the_selected_server(cfg):
    cfg.upsert_server("host-a")
    cfg.upsert_server("host-b")
    cfg.set_active_server_index(1)
    assert cfg.get_active_server()["host"] == "host-b"


def test_update_server_settings_bulk_writes_active_server(cfg):
    cfg.upsert_server("myhost")
    cfg.update_server_settings({"vpn_enabled": True, "vpn_type": "ProtonVPN"})
    active = cfg.get_active_server()
    assert active["settings"]["vpn_enabled"] is True
    assert active["settings"]["vpn_type"] == "ProtonVPN"


def test_secrets_are_encrypted_on_disk_but_plaintext_in_memory(cfg):
    cfg.upsert_server("myhost")
    cfg.update_server_settings({"sonarr_apikey": "my-plaintext-key"})

    # In-memory copy stays plaintext for every other call site to use
    assert cfg.get_active_server()["settings"]["sonarr_apikey"] == "my-plaintext-key"

    # On-disk copy must not contain the plaintext secret anywhere
    raw = open(cfg.CONFIG_PATH).read()
    assert "my-plaintext-key" not in raw


def test_reloading_config_decrypts_secrets_back_to_plaintext(cfg):
    cfg.upsert_server("myhost")
    cfg.update_server_settings({"sonarr_apikey": "my-plaintext-key"})

    # Simulate a fresh app start reading the same file back (cfg fixture's
    # monkeypatch of CONFIG_PATH stays in effect for this whole test, so
    # this reads the same isolated file).
    reloaded = ConfigManager()
    assert reloaded.get_active_server()["settings"]["sonarr_apikey"] == "my-plaintext-key"


def test_property_wrappers_use_the_same_per_server_mechanism(cfg):
    """Spot-check a couple of the ~100 generated property wrappers rather
    than testing every single one — they're all _gs/_ss one-liners, and
    that mechanism is already covered directly above."""
    cfg.upsert_server("myhost")
    cfg.sonarr_apikey = "abc123"
    assert cfg.sonarr_apikey == "abc123"

    cfg.dashboard_refresh_interval = 15
    assert cfg.dashboard_refresh_interval == 15


def test_minimize_to_tray_on_close_defaults_true_and_round_trips(cfg):
    """Defaults to True to preserve the app's original (pre-toggle)
    behavior — minimizing to tray whenever a tray icon actually started."""
    assert cfg.minimize_to_tray_on_close is True

    cfg.minimize_to_tray_on_close = False
    assert cfg.minimize_to_tray_on_close is False

    on_disk = json.loads(open(cfg.CONFIG_PATH).read())
    assert on_disk["minimize_to_tray_on_close"] is False
