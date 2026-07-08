from core import secure_storage


def test_encrypt_decrypt_round_trip():
    plaintext = "sup3r-secret-api-key"
    encrypted = secure_storage.encrypt(plaintext)
    assert encrypted != plaintext
    assert encrypted.startswith(secure_storage.MARKER)
    assert secure_storage.decrypt(encrypted) == plaintext


def test_encrypt_empty_string_is_left_alone():
    assert secure_storage.encrypt("") == ""


def test_decrypt_passes_through_unmarked_values():
    """Values written before encryption existed have no "dpapi:" marker —
    decrypt() must return them unchanged rather than erroring or mangling
    them, or every pre-existing config.json would break on first load."""
    assert secure_storage.decrypt("plain-old-value") == "plain-old-value"
    assert secure_storage.decrypt("") == ""


def test_decrypt_non_string_passes_through():
    assert secure_storage.decrypt(None) is None
    assert secure_storage.decrypt(123) == 123


def test_is_sensitive_key_matches_common_secret_names():
    for key in ("password", "Password", "sabnzbd_apikey", "api_key",
                "plex_token", "restic_password", "some_secret_value"):
        assert secure_storage.is_sensitive_key(key), key


def test_is_sensitive_key_does_not_match_ordinary_keys():
    for key in ("host", "port", "username", "enabled", "refresh_interval"):
        assert not secure_storage.is_sensitive_key(key), key


def test_encrypted_value_is_not_readable_as_plaintext():
    """The whole point: ciphertext shouldn't contain the plaintext secret
    anywhere, even base64-encoded verbatim."""
    secret = "hunter2-password-do-not-leak"
    encrypted = secure_storage.encrypt(secret)
    assert secret not in encrypted
