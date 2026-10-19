"""Phase 20.2: app.notifications.secret_crypto in isolation -- the
DEDICATED encryption-key path (PUSHOVER_KEY_ENCRYPTION_KEY), decoupled
from SECRET_KEY/JWT signing."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.notifications.secret_crypto import decrypt_secret, encrypt_secret


def test_round_trips_correctly():
    ciphertext = encrypt_secret("my-pushover-key", encryption_key="encryption-key-a")
    assert decrypt_secret(ciphertext, encryption_key="encryption-key-a") == "my-pushover-key"


def test_ciphertext_never_contains_the_plaintext():
    ciphertext = encrypt_secret("my-pushover-key", encryption_key="encryption-key-a")
    assert "my-pushover-key" not in ciphertext


def test_decrypting_with_the_wrong_encryption_key_returns_none_not_raises():
    ciphertext = encrypt_secret("my-pushover-key", encryption_key="encryption-key-a")
    assert decrypt_secret(ciphertext, encryption_key="a-totally-different-encryption-key") is None


def test_decrypting_garbage_returns_none_not_raises():
    assert decrypt_secret("not-a-real-fernet-token", encryption_key="encryption-key-a") is None


def test_two_different_plaintexts_produce_different_ciphertexts():
    a = encrypt_secret("key-one", encryption_key="encryption-key-a")
    b = encrypt_secret("key-two", encryption_key="encryption-key-a")
    assert a != b


def test_the_same_plaintext_and_encryption_key_produce_different_ciphertexts_each_time():
    """Fernet includes a random IV/nonce -- two encryptions of the same
    plaintext must not be byte-identical (otherwise equal ciphertexts
    would leak that two users share a key)."""
    a = encrypt_secret("same-key", encryption_key="encryption-key-a")
    b = encrypt_secret("same-key", encryption_key="encryption-key-a")
    assert a != b
    assert decrypt_secret(a, encryption_key="encryption-key-a") == "same-key"
    assert decrypt_secret(b, encryption_key="encryption-key-a") == "same-key"


def test_a_real_fernet_generated_key_is_accepted_and_used_directly():
    """`PUSHOVER_KEY_ENCRYPTION_KEY` may itself already be a valid Fernet
    key (e.g. produced by `Fernet.generate_key()`) -- this must work,
    not just arbitrary strings that get SHA-256-derived."""
    real_fernet_key = Fernet.generate_key().decode("utf-8")
    ciphertext = encrypt_secret("destination-key", encryption_key=real_fernet_key)
    assert decrypt_secret(ciphertext, encryption_key=real_fernet_key) == "destination-key"


def test_arbitrary_non_fernet_shaped_strings_are_safely_transformed():
    """An operator-chosen plain string (not already base64/32-byte
    shaped) must still work -- safely transformed into a valid Fernet
    key rather than rejected."""
    ciphertext = encrypt_secret("destination-key", encryption_key="just-a-plain-operator-chosen-secret")
    assert (
        decrypt_secret(ciphertext, encryption_key="just-a-plain-operator-chosen-secret")
        == "destination-key"
    )


def test_encrypt_and_decrypt_take_only_an_explicit_encryption_key_argument():
    """Phase 20.2's actual fix, verified by signature rather than by
    source-text matching (the module's own docstring legitimately
    discusses the old, removed SECRET_KEY-derived design in prose): the
    only secret either function accepts is `encryption_key` -- there is
    no way to call either function and have it reach into
    app.config.Settings.secret_key, so rotating SECRET_KEY cannot
    possibly affect this module's behavior."""
    import inspect

    encrypt_params = set(inspect.signature(encrypt_secret).parameters)
    decrypt_params = set(inspect.signature(decrypt_secret).parameters)
    assert encrypt_params == {"plaintext", "encryption_key"}
    assert decrypt_params == {"ciphertext", "encryption_key"}
