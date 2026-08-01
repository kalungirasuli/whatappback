from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from fastapi import HTTPException
from jose import jwt

from src.admin.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    ALGORITHM,
    pwd_context,
)
from src.domain.enums import AdminRole


class TestHashPassword:
    @patch.object(pwd_context, "hash", side_effect=lambda p: f"$2b$12$fakedhashfor{p}")
    def test_returns_string(self, mock_hash):
        result = hash_password("mypassword")
        assert isinstance(result, str)
        mock_hash.assert_called_once_with("mypassword")

    @patch.object(pwd_context, "hash")
    def test_different_hashes_for_same_password(self, mock_hash):
        mock_hash.side_effect = [f"$2b$12$hash_a", f"$2b$12$hash_b"]
        h1 = hash_password("password123")
        h2 = hash_password("password123")
        assert h1 != h2

    @patch.object(pwd_context, "hash", return_value="$2b$12$fakehash")
    def test_hash_not_equal_to_plaintext(self, mock_hash):
        h = hash_password("secret")
        assert h != "secret"

    @patch.object(pwd_context, "hash", return_value="$2b$12$fakehashvalue")
    def test_bcrypt_prefix(self, mock_hash):
        h = hash_password("test")
        assert h.startswith("$2")

    @patch.object(pwd_context, "hash", return_value="$2b$12$fakedempty")
    def test_empty_password(self, mock_hash):
        h = hash_password("")
        assert isinstance(h, str)
        assert len(h) > 0


class TestVerifyPassword:
    @patch.object(pwd_context, "verify", return_value=True)
    def test_correct_password(self, mock_verify):
        result = verify_password("mypassword", "$2b$12$hashed")
        assert result is True
        mock_verify.assert_called_once_with("mypassword", "$2b$12$hashed")

    @patch.object(pwd_context, "verify", return_value=False)
    def test_wrong_password(self, mock_verify):
        result = verify_password("wrongpassword", "$2b$12$hashed")
        assert result is False

    @patch.object(pwd_context, "verify", return_value=True)
    def test_empty_password_match(self, mock_verify):
        result = verify_password("", "$2b$12$hashed")
        assert result is True

    @patch.object(pwd_context, "verify", return_value=False)
    def test_empty_password_wrong(self, mock_verify):
        result = verify_password("password", "$2b$12$hashed")
        assert result is False

    @patch.object(pwd_context, "verify")
    def test_verify_after_hash(self, mock_verify):
        mock_verify.return_value = True
        passwords = ["abc", "hello world", "P@$$w0rd!", "1234567890"]
        for pw in passwords:
            result = verify_password(pw, f"$2b$12$hash_{pw}")
            assert result is True


class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        assert isinstance(token, str)

    def test_token_contains_valid_jwt(self):
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        from src.core.config import settings
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
        assert payload["sub"] == "1"
        assert payload["email"] == "admin@test.com"
        assert payload["role"] == "superadmin"

    def test_token_has_expiration(self):
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        from src.core.config import settings
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_different_tokens_for_different_admins(self):
        t1 = create_access_token(1, "a@test.com", AdminRole.superadmin)
        t2 = create_access_token(2, "b@test.com", AdminRole.moderator)
        assert t1 != t2

    def test_moderator_role(self):
        token = create_access_token(5, "mod@test.com", AdminRole.moderator)
        from src.core.config import settings
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
        assert payload["role"] == "moderator"

    def test_token_expiry_is_future(self):
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        from src.core.config import settings
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)


class TestDecodeToken:
    def test_decode_valid_token(self):
        token = create_access_token(42, "admin@test.com", AdminRole.superadmin)
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["email"] == "admin@test.com"
        assert payload["role"] == "superadmin"

    def test_decode_invalid_token_raises(self):
        try:
            decode_token("invalid.token.here")
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert "Invalid or expired token" in e.detail

    def test_decode_empty_string_raises(self):
        try:
            decode_token("")
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401

    def test_decode_tampered_token_raises(self):
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        tampered = token[:-5] + "XXXXX"
        try:
            decode_token(tampered)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401

    def test_decode_with_wrong_secret_raises(self):
        from src.core.config import settings
        original_secret = settings.admin_jwt_secret
        settings.admin_jwt_secret = "secret_a"
        token = create_access_token(1, "admin@test.com", AdminRole.superadmin)
        settings.admin_jwt_secret = "secret_b"
        try:
            decode_token(token)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
        finally:
            settings.admin_jwt_secret = original_secret

    def test_roundtrip_encode_decode(self):
        token = create_access_token(99, "round@test.com", AdminRole.moderator)
        payload = decode_token(token)
        assert int(payload["sub"]) == 99
        assert payload["email"] == "round@test.com"
        assert payload["role"] == "moderator"
