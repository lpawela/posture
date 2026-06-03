from app.auth import hash_password, new_token, verify_password


def test_hash_and_verify_roundtrip():
    salt, digest = hash_password("correct horse")
    assert verify_password("correct horse", salt, digest)
    assert not verify_password("wrong", salt, digest)


def test_salt_is_random_per_call():
    s1, h1 = hash_password("same")
    s2, h2 = hash_password("same")
    assert s1 != s2
    assert h1 != h2


def test_same_salt_reproduces_hash():
    salt, digest = hash_password("pw")
    salt2, digest2 = hash_password("pw", salt)
    assert salt2 == salt
    assert digest2 == digest


def test_tokens_are_unique_and_long():
    assert new_token() != new_token()
    assert len(new_token()) >= 20
