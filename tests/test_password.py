"""Tests for Argon2id password hashing with salting and peppering."""

from bookstuff.web.password import (
    generate_pepper,
    hash_password,
    needs_rehash,
    verify_password,
)


class TestHashAndVerify:
    def test_correct_password_verifies(self):
        h = hash_password("secret", pepper="pep")
        assert verify_password("secret", h, pepper="pep")

    def test_wrong_password_rejected(self):
        h = hash_password("secret", pepper="pep")
        assert not verify_password("wrong", h, pepper="pep")

    def test_wrong_pepper_rejected(self):
        h = hash_password("secret", pepper="pep")
        assert not verify_password("secret", h, pepper="other")

    def test_empty_pepper_works(self):
        h = hash_password("secret")
        assert verify_password("secret", h)

    def test_each_hash_unique(self):
        """Random salt means identical inputs produce different hashes."""
        h1 = hash_password("same", pepper="pep")
        h2 = hash_password("same", pepper="pep")
        assert h1 != h2

    def test_hash_is_argon2id(self):
        h = hash_password("x", pepper="p")
        assert h.startswith("$argon2id$")


class TestVerifyEdgeCases:
    def test_empty_hash_returns_false(self):
        assert not verify_password("secret", "", pepper="p")

    def test_garbage_hash_returns_false(self):
        assert not verify_password("secret", "not-a-hash", pepper="p")

    def test_empty_password_can_be_hashed(self):
        h = hash_password("", pepper="p")
        assert verify_password("", h, pepper="p")
        assert not verify_password("x", h, pepper="p")


class TestNeedsRehash:
    def test_current_params_no_rehash(self):
        h = hash_password("pw", pepper="p")
        assert not needs_rehash(h)

    def test_garbage_needs_rehash(self):
        assert needs_rehash("invalid")


class TestGeneratePepper:
    def test_length(self):
        p = generate_pepper()
        assert len(p) == 64  # 32 bytes = 64 hex chars

    def test_unique(self):
        assert generate_pepper() != generate_pepper()
