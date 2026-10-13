from __future__ import annotations

from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("s3cret-password")
    assert not verify_password("s3cret-passwore", hashed)
    assert not verify_password("", hashed)


def test_password_hashes_are_salted_per_call() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_tolerates_a_corrupt_hash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_passwords_longer_than_bcrypt_limit_are_truncated_consistently() -> None:
    long_password = "x" * 200
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed)
    # Both truncate at the same byte boundary, so they are indistinguishable — the reason
    # bcrypt input is truncated explicitly rather than silently.
    assert verify_password("x" * 72, hashed)


def test_token_roundtrip_carries_subject_and_tenant() -> None:
    token = create_access_token("user-1", "tenant-1")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-1"
    assert payload["tid"] == "tenant-1"


def test_tampered_token_is_rejected() -> None:
    token = create_access_token("user-1", "tenant-1")
    head, payload, signature = token.split(".")
    assert decode_access_token(f"{head}.{payload}.{signature[:-2]}xx") is None


def test_garbage_token_is_rejected() -> None:
    assert decode_access_token("not.a.jwt") is None
    assert decode_access_token("") is None


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-1", "tenant-1", expires_minutes=-1)
    assert decode_access_token(token) is None
