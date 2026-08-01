import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from src.workers.notification import (
    NotificationService,
    MESSAGING_WINDOW_PREFIX,
    MESSAGING_WINDOW_TTL,
    INTEREST_NOTIFICATION_PREFIX,
    INTEREST_NOTIFICATION_TTL,
)
from src.shared.templates import INTEREST_BODY, RESTOCK_BODY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(redis_mock=None):
    svc = NotificationService()
    if redis_mock:
        svc._redis = redis_mock
    return svc


# ---------------------------------------------------------------------------
# check_messaging_window
# ---------------------------------------------------------------------------

class TestCheckMessagingWindow:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_last_outbound(self):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        result = await svc.check_messaging_window("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_within_24h(self):
        redis = AsyncMock()
        now = datetime.now(timezone.utc)
        redis.get.return_value = now.isoformat()
        svc = _make_service(redis)
        result = await svc.check_messaging_window("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_outside_24h(self):
        redis = AsyncMock()
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        redis.get.return_value = old.isoformat()
        svc = _make_service(redis)
        result = await svc.check_messaging_window("+256700000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_invalid_timestamp(self):
        redis = AsyncMock()
        redis.get.return_value = "not-a-timestamp"
        svc = _make_service(redis)
        result = await svc.check_messaging_window("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_naive_timestamp_within_window(self):
        redis = AsyncMock()
        naive = datetime(2025, 1, 1, 12, 0, 0)
        redis.get.return_value = naive.isoformat()
        svc = _make_service(redis)
        with patch("src.workers.notification.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
            mock_dt.fromisoformat = datetime.fromisoformat
            result = await svc.check_messaging_window("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_correct_redis_key(self):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        await svc.check_messaging_window("+256700000000")
        redis.get.assert_awaited_once_with(f"{MESSAGING_WINDOW_PREFIX}+256700000000")


# ---------------------------------------------------------------------------
# record_outbound_message
# ---------------------------------------------------------------------------

class TestRecordOutboundMessage:
    @pytest.mark.asyncio
    async def test_stores_timestamp_with_ttl(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.record_outbound_message("+256700000000")
        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args[0]
        assert call_args[0] == f"{MESSAGING_WINDOW_PREFIX}+256700000000"
        assert call_args[1] == MESSAGING_WINDOW_TTL
        # third arg is ISO timestamp string
        ts = datetime.fromisoformat(call_args[2])
        assert ts.tzinfo is not None


# ---------------------------------------------------------------------------
# record_inbound_message
# ---------------------------------------------------------------------------

class TestRecordInboundMessage:
    @pytest.mark.asyncio
    async def test_stores_in_inbound_window(self):
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.record_inbound_message("+256700000000")
        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args[0]
        assert call_args[0] == "inbound_window:+256700000000"
        assert call_args[1] == MESSAGING_WINDOW_TTL


# ---------------------------------------------------------------------------
# check_buyer_window
# ---------------------------------------------------------------------------

class TestCheckBuyerWindow:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_inbound(self):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        result = await svc.check_buyer_window("+256700000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_within_24h(self):
        redis = AsyncMock()
        now = datetime.now(timezone.utc)
        redis.get.return_value = now.isoformat()
        svc = _make_service(redis)
        result = await svc.check_buyer_window("+256700000000")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_outside_24h(self):
        redis = AsyncMock()
        old = datetime.now(timezone.utc) - timedelta(hours=30)
        redis.get.return_value = old.isoformat()
        svc = _make_service(redis)
        result = await svc.check_buyer_window("+256700000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_invalid_timestamp(self):
        redis = AsyncMock()
        redis.get.return_value = "garbage"
        svc = _make_service(redis)
        result = await svc.check_buyer_window("+256700000000")
        assert result is False


# ---------------------------------------------------------------------------
# send_interest_notification
# ---------------------------------------------------------------------------

class TestSendInterestNotification:
    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value={"id": "msg1"})
    async def test_sends_notification_and_sets_dedup(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None  # not already notified
        svc = _make_service(redis)

        result = await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
            product_name="Red Dress",
            price=50000,
        )
        assert result is True
        mock_send.assert_awaited_once()
        sent_body = mock_send.call_args[0][1]
        assert "Red Dress" in sent_body
        assert "50,000" in sent_body

        # dedup key set
        redis.setex.assert_awaited()
        dedup_call = redis.setex.call_args_list[0]
        expected_key = f"{INTEREST_NOTIFICATION_PREFIX}+256700000000:42:+256711111111"
        assert dedup_call[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_skips_when_already_notified(self):
        redis = AsyncMock()
        redis.get.return_value = "sent"
        svc = _make_service(redis)

        result = await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock)
    async def test_skips_when_messaging_window_expired(self, mock_send):
        redis = AsyncMock()
        # First get call is dedup check, second is window check
        redis.get.side_effect = [None, None]
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        # Override for window check
        call_count = 0

        original_get = redis.get.async_side_effect

        async def fake_get(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # dedup
            return old.isoformat()  # window expired

        redis.get.side_effect = None
        redis.get = AsyncMock(side_effect=fake_get)

        svc = _make_service(redis)
        result = await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
        )
        assert result is False
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value=None)
    async def test_returns_false_when_send_returns_none(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None  # dedup check
        svc = _make_service(redis)
        result = await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, side_effect=Exception("api down"))
    async def test_returns_false_on_send_exception(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        result = await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value={"id": "m"})
    async def test_records_outbound_message_on_success(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=42,
            buyer_phone="+256711111111",
        )
        # Should have two setex calls: dedup + outbound window
        assert redis.setex.await_count == 2


# ---------------------------------------------------------------------------
# send_restock_notification
# ---------------------------------------------------------------------------

class TestSendRestockNotification:
    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value={"id": "msg2"})
    async def test_sends_restock_and_sets_dedup(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)

        result = await svc.send_restock_notification(
            buyer_phone="+256711111111",
            product_id=7,
            product_name="Blue Shirt",
            price=25000,
        )
        assert result is True
        sent_body = mock_send.call_args[0][1]
        assert "Blue Shirt" in sent_body
        assert "25,000" in sent_body

        redis.setex.assert_awaited_once()
        dedup_call = redis.setex.call_args[0]
        assert dedup_call[0] == "restock_notif:+256711111111:7"

    @pytest.mark.asyncio
    async def test_skips_when_already_notified(self):
        redis = AsyncMock()
        redis.get.return_value = "sent"
        svc = _make_service(redis)
        result = await svc.send_restock_notification(
            buyer_phone="+256711111111",
            product_id=7,
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value=None)
    async def test_returns_false_when_send_returns_none(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        result = await svc.send_restock_notification(
            buyer_phone="+256711111111",
            product_id=7,
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, side_effect=Exception("down"))
    async def test_returns_false_on_exception(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        result = await svc.send_restock_notification(
            buyer_phone="+256711111111",
            product_id=7,
        )
        assert result is False


# ---------------------------------------------------------------------------
# Template format tests
# ---------------------------------------------------------------------------

class TestNotificationTemplates:
    def test_interest_body_format(self):
        body = INTEREST_BODY.format(product_name="Shoes", price=50000, currency="UGX")
        assert "Shoes" in body
        assert "50,000" in body
        assert "UGX" in body

    def test_restock_body_format(self):
        body = RESTOCK_BODY.format(product_name="Hat", price=10000, currency="UGX")
        assert "Hat" in body
        assert "10,000" in body
        assert "UGX" in body


# ---------------------------------------------------------------------------
# Dedup key construction
# ---------------------------------------------------------------------------

class TestDedupKeyConstruction:
    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value={"id": "x"})
    async def test_interest_dedup_key_includes_all_parts(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        await svc.send_interest_notification(
            merchant_phone="+256700000000",
            product_id=99,
            buyer_phone="+256722222222",
        )
        key = redis.setex.call_args_list[0][0][0]
        assert "+256700000000" in key
        assert "99" in key
        assert "+256722222222" in key

    @pytest.mark.asyncio
    @patch("src.workers.notification.send_text", new_callable=AsyncMock, return_value={"id": "y"})
    async def test_restock_dedup_key_includes_buyer_and_product(self, mock_send):
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        await svc.send_restock_notification(
            buyer_phone="+256733333333",
            product_id=55,
        )
        key = redis.setex.call_args[0][0]
        assert "+256733333333" in key
        assert "55" in key
