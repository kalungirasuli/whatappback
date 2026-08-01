import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from src.shared.compliance import (
    ComplianceService,
    CONSENT_PREFIX,
    CONSENT_TTL,
    ANONYMIZED_PREFIX,
    ANONYMIZED_TTL,
)


def _make_service(redis_mock=None):
    svc = ComplianceService()
    if redis_mock:
        svc._redis = redis_mock
    return svc


# ---------------------------------------------------------------------------
# mask_phone
# ---------------------------------------------------------------------------

class TestMaskPhone:
    def test_masks_ugandan_number(self):
        result = ComplianceService.mask_phone("+256700123456")
        assert result.startswith("256")
        assert result.endswith("3456")
        assert "***" in result

    def test_masks_short_phone_returns_stars(self):
        result = ComplianceService.mask_phone("+123")
        assert result == "***"

    def test_masks_empty_returns_stars(self):
        result = ComplianceService.mask_phone("")
        assert result == "***"

    def test_masks_none_returns_stars(self):
        result = ComplianceService.mask_phone(None)
        assert result == "***"

    def test_masks_long_number(self):
        result = ComplianceService.mask_phone("+256789012345678")
        assert "***" in result
        assert result.startswith("256")
        assert result.endswith("678")

    def test_masks_exactly_7_chars(self):
        result = ComplianceService.mask_phone("1234567")
        assert "***" in result

    def test_no_plus_prefix_handled(self):
        result = ComplianceService.mask_phone("256700123456")
        assert "***" in result
        assert result.startswith("256")


# ---------------------------------------------------------------------------
# check_consent
# ---------------------------------------------------------------------------

class TestCheckConsent:
    @pytest.mark.asyncio
    async def test_returns_true_for_true_value(self):
        redis = AsyncMock()
        redis.get.return_value = "true"
        svc = _make_service(redis)
        result = await svc.check_consent("+256700000000")
        assert result is True
        redis.get.assert_awaited_once_with(f"{CONSENT_PREFIX}+256700000000")

    @pytest.mark.asyncio
    async def test_returns_true_for_1(self):
        redis = AsyncMock()
        redis.get.return_value = "1"
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is True

    @pytest.mark.asyncio
    async def test_returns_true_for_yes(self):
        redis = AsyncMock()
        redis.get.return_value = "yes"
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is True

    @pytest.mark.asyncio
    async def test_returns_true_for_granted(self):
        redis = AsyncMock()
        redis.get.return_value = "granted"
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_none(self):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is False

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_value(self):
        redis = AsyncMock()
        redis.get.return_value = "maybe"
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is False

    @pytest.mark.asyncio
    async def test_returns_false_for_revoked(self):
        redis = AsyncMock()
        redis.get.return_value = "revoked"
        svc = _make_service(redis)
        assert await svc.check_consent("+256700000000") is False


# ---------------------------------------------------------------------------
# record_consent
# ---------------------------------------------------------------------------

class TestRecordConsent:
    @pytest.mark.asyncio
    async def test_stores_consent_with_ttl(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.record_consent("+256700000000", "marketing")
        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args[0]
        assert call_args[0] == f"{CONSENT_PREFIX}+256700000000"
        assert call_args[1] == CONSENT_TTL
        assert "marketing" in call_args[2]

    @pytest.mark.asyncio
    async def test_default_consent_type(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.record_consent("+256700000000")
        call_args = redis.setex.call_args[0]
        assert "data_processing" in call_args[2]


# ---------------------------------------------------------------------------
# revoke_consent
# ---------------------------------------------------------------------------

class TestRevokeConsent:
    @pytest.mark.asyncio
    async def test_deletes_consent_key(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.revoke_consent("+256700000000")
        redis.delete.assert_awaited_once_with(f"{CONSENT_PREFIX}+256700000000")


# ---------------------------------------------------------------------------
# get_data_retention_info
# ---------------------------------------------------------------------------

class TestGetDataRetentionInfo:
    @pytest.mark.asyncio
    async def test_returns_consent_info(self):
        redis = AsyncMock()
        redis.get.return_value = "data_processing:2025-01-01T00:00:00+00:00"
        redis.ttl.return_value = 31000000
        svc = _make_service(redis)
        info = await svc.get_data_retention_info("+256700000000")
        assert info["has_consent"] is True
        assert "data_processing" in info["consent_record"]
        assert info["retention_ttl_seconds"] == 31000000
        assert info["data_minimization_enabled"] is True
        assert info["right_to_erasure_supported"] is True
        assert "***" in info["phone_masked"]

    @pytest.mark.asyncio
    async def test_returns_no_consent_info(self):
        redis = AsyncMock()
        redis.get.return_value = None
        redis.ttl.return_value = -2
        svc = _make_service(redis)
        info = await svc.get_data_retention_info("+256700000000")
        assert info["has_consent"] is False
        assert info["retention_expiry"] is None


# ---------------------------------------------------------------------------
# anonymize_buyer_data
# ---------------------------------------------------------------------------

class TestAnonymizeBuyerData:
    @pytest.mark.asyncio
    async def test_sets_anonymized_key(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        with patch("src.core.dependencies.async_session_factory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            await svc.anonymize_buyer_data(42)

        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args[0]
        assert call_args[0] == f"{ANONYMIZED_PREFIX}buyer:42"
        assert call_args[1] == ANONYMIZED_TTL

    @pytest.mark.asyncio
    async def test_does_not_crash_on_db_error(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        with patch("src.core.dependencies.async_session_factory") as mock_factory:
            mock_session = AsyncMock()
            mock_session.execute.side_effect = Exception("db down")
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            # Should not raise
            await svc.anonymize_buyer_data(42)

        redis.setex.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_data_processor_basis
# ---------------------------------------------------------------------------

class TestCheckDataProcessorBasis:
    @pytest.mark.asyncio
    async def test_with_consent(self):
        redis = AsyncMock()
        redis.get.return_value = "true"
        redis.keys.return_value = []
        svc = _make_service(redis)
        result = await svc.check_data_processor_basis("+256700000000")
        assert result["lawful_basis"] == "consent"
        assert result["has_consent"] is True
        assert result["is_anonymized"] is False
        assert result["data_minimized"] is True

    @pytest.mark.asyncio
    async def test_without_consent(self):
        redis = AsyncMock()
        redis.get.return_value = None
        redis.keys.return_value = []
        svc = _make_service(redis)
        result = await svc.check_data_processor_basis("+256700000000")
        assert result["lawful_basis"] == "none"
        assert result["has_consent"] is False

    @pytest.mark.asyncio
    async def test_anonymized_detected(self):
        redis = AsyncMock()
        redis.get.return_value = None
        redis.keys.return_value = [f"{ANONYMIZED_PREFIX}buyer:42"]
        svc = _make_service(redis)
        result = await svc.check_data_processor_basis("+256700000000")
        assert result["is_anonymized"] is True


# ---------------------------------------------------------------------------
# _check_anonymized
# ---------------------------------------------------------------------------

class TestCheckAnonymized:
    @pytest.mark.asyncio
    async def test_returns_true_when_keys_found(self):
        redis = AsyncMock()
        redis.keys.return_value = [f"{ANONYMIZED_PREFIX}buyer:5"]
        svc = _make_service(redis)
        result = await svc._check_anonymized("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_keys(self):
        redis = AsyncMock()
        redis.keys.return_value = []
        svc = _make_service(redis)
        result = await svc._check_anonymized("+256700000000")
        assert result is False
