import pytest
from api_service_handler.encryption import encrypt_api_key, decrypt_api_key, is_encrypted, mask_key, _derive_key

def test_derive_key():
    key1 = _derive_key("secret1")
    key2 = _derive_key("secret1")
    key3 = _derive_key("secret2")
    assert len(key1) == 32
    assert key1 == key2
    assert key1 != key3

def test_encrypt_decrypt():
    plain_text = "sk-test12345"
    shared_secret = "my_super_secret"
    
    encrypted = encrypt_api_key(plain_text, shared_secret)
    assert encrypted != plain_text
    assert is_encrypted(encrypted) is True
    
    decrypted = decrypt_api_key(encrypted, shared_secret)
    assert decrypted == plain_text

def test_decrypt_invalid_format():
    shared_secret = "my_super_secret"
    assert decrypt_api_key("not.an.encrypted.format", shared_secret) == "not.an.encrypted.format"
    assert decrypt_api_key("too.few", shared_secret) == "too.few"

def test_decrypt_invalid_secret():
    plain_text = "sk-test12345"
    encrypted = encrypt_api_key(plain_text, "secret1")
    
    # Decrypting with wrong secret should fail gracefully and return the encrypted string
    decrypted = decrypt_api_key(encrypted, "secret2")
    assert decrypted == encrypted

def test_mask_key():
    assert mask_key("sk-abcdefghijk", 8) == "sk-abcde***"
    assert mask_key("sk-a", 8) == "sk-a"
