import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

from src.workers.merchant_commands import (
    handle_edit,
    handle_stock,
    handle_price,
    handle_delete,
    handle_merchant_command,
)
from src.domain.enums import ProductStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeMerchant:
    id: int = 1
    phone_number: str = "+256700000000"
    business_name: str = "Test Shop"
    category: str = "Electronics"
    status: str = "approved"


@dataclass
class FakeProduct:
    id: int = 10
    merchant_id: int = 1
    name: str = "Red Dress"
    price: float = 50000.0
    stock_qty: int = 5
    description: str | None = None
    qdrant_point_id: str | None = None


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_send_text():
    return AsyncMock()


# ---------------------------------------------------------------------------
# @edit command
# ---------------------------------------------------------------------------

class TestHandleEdit:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_name(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_edit(_mock_db(), FakeMerchant(), "10 name Blue Dress", "+256700000000")

        mock_update.assert_awaited_once()
        assert mock_update.call_args[1]["name"] == "Blue Dress"
        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Blue Dress" in sent_text
        assert "updated" in sent_text.lower()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_price(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_edit(_mock_db(), FakeMerchant(), "10 price 75000", "+256700000000")

        assert mock_update.call_args[1]["price"] == 75000.0
        sent_text = mock_send.call_args[0][1]
        assert "75,000" in sent_text
        assert "UGX" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_price_with_commas(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(price=50000)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_edit(_mock_db(), FakeMerchant(), "10 price 80,000", "+256700000000")
        assert mock_update.call_args[1]["price"] == 80000.0
        sent_text = mock_send.call_args[0][1]
        assert "80,000" in sent_text
        assert "UGX" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_stock_qty(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_edit(_mock_db(), FakeMerchant(), "10 stock_qty 20", "+256700000000")
        assert mock_update.call_args[1]["stock_qty"] == 20
        sent_text = mock_send.call_args[0][1]
        assert "20 units" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_description(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_edit(_mock_db(), FakeMerchant(), "10 description A nice dress", "+256700000000")
        assert mock_update.call_args[1]["description"] == "A nice dress"

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_edit_no_args_shows_usage(self, mock_send):
        await handle_edit(_mock_db(), FakeMerchant(), "", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_edit_insufficient_args(self, mock_send):
        await handle_edit(_mock_db(), FakeMerchant(), "10 name", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_edit_invalid_product_id(self, mock_send):
        await handle_edit(_mock_db(), FakeMerchant(), "abc name value", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid product ID" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock, return_value=None)
    async def test_edit_product_not_found(self, mock_get, mock_send):
        await handle_edit(_mock_db(), FakeMerchant(), "999 name value", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "not found" in sent_text.lower()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_unknown_field(self, mock_get, mock_send):
        mock_get.return_value = FakeProduct()
        await handle_edit(_mock_db(), FakeMerchant(), "10 unknown_field value", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Unknown field" in sent_text
        assert "unknown_field" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_empty_name_rejected(self, mock_get, mock_send):
        mock_get.return_value = FakeProduct()
        await handle_edit(_mock_db(), FakeMerchant(), "10 name \t", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_invalid_price_rejected(self, mock_get, mock_send):
        mock_get.return_value = FakeProduct()
        await handle_edit(_mock_db(), FakeMerchant(), "10 price abc", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid price" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_edit_invalid_stock_qty_rejected(self, mock_get, mock_send):
        mock_get.return_value = FakeProduct()
        await handle_edit(_mock_db(), FakeMerchant(), "10 stock_qty abc", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid quantity" in sent_text


# ---------------------------------------------------------------------------
# @stock command
# ---------------------------------------------------------------------------

class TestHandleStock:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_update_stock(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(stock_qty=5)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_stock(_mock_db(), FakeMerchant(), "10 50", "+256700000000")

        mock_update.assert_awaited_once()
        assert mock_update.call_args[1]["stock_qty"] == 50
        sent_text = mock_send.call_args[0][1]
        assert "50 units" in sent_text
        assert "5 units" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_restock_message_when_going_from_zero(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(stock_qty=0)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_stock(_mock_db(), FakeMerchant(), "10 10", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "back in stock" in sent_text.lower()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_out_of_stock_message_when_set_to_zero(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(stock_qty=10)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_stock(_mock_db(), FakeMerchant(), "10 0", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "out of stock" in sent_text.lower()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_no_args_shows_usage(self, mock_send):
        await handle_stock(_mock_db(), FakeMerchant(), "", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_wrong_arg_count(self, mock_send):
        await handle_stock(_mock_db(), FakeMerchant(), "10", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_product_id(self, mock_send):
        await handle_stock(_mock_db(), FakeMerchant(), "abc 10", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid product ID" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_quantity(self, mock_send):
        await handle_stock(_mock_db(), FakeMerchant(), "10 abc", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid quantity" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock, return_value=None)
    async def test_product_not_found(self, mock_get, mock_send):
        await handle_stock(_mock_db(), FakeMerchant(), "999 10", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "not found" in sent_text.lower()


# ---------------------------------------------------------------------------
# @price command
# ---------------------------------------------------------------------------

class TestHandlePrice:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_update_price(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(price=50000)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_price(_mock_db(), FakeMerchant(), "10 75000", "+256700000000")

        mock_update.assert_awaited_once()
        assert mock_update.call_args[1]["price"] == 75000.0
        sent_text = mock_send.call_args[0][1]
        assert "50,000" in sent_text
        assert "75,000" in sent_text
        assert "UGX" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_price_with_commas_and_ugx(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(price=50000)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_price(_mock_db(), FakeMerchant(), "10 100,000UGX", "+256700000000")
        assert mock_update.call_args[1]["price"] == 100000.0

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_price_zero(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct(price=50000)
        mock_get.return_value = product
        mock_update.return_value = product

        await handle_price(_mock_db(), FakeMerchant(), "10 0", "+256700000000")
        assert mock_update.call_args[1]["price"] == 0.0

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_no_args_shows_usage(self, mock_send):
        await handle_price(_mock_db(), FakeMerchant(), "", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_wrong_arg_count(self, mock_send):
        await handle_price(_mock_db(), FakeMerchant(), "10", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_product_id(self, mock_send):
        await handle_price(_mock_db(), FakeMerchant(), "abc 50000", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid product ID" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_price(self, mock_send):
        await handle_price(_mock_db(), FakeMerchant(), "10 abc", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid price" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock, return_value=None)
    async def test_product_not_found(self, mock_get, mock_send):
        await handle_price(_mock_db(), FakeMerchant(), "999 50000", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "not found" in sent_text.lower()


# ---------------------------------------------------------------------------
# @delete command
# ---------------------------------------------------------------------------

class TestHandleDelete:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.delete_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_delete_product(self, mock_get, mock_delete, mock_log, mock_send):
        product = FakeProduct(name="Red Dress")
        mock_get.return_value = product

        await handle_delete(_mock_db(), FakeMerchant(), "10", "+256700000000")

        mock_delete.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Red Dress" in sent_text
        assert "#10" in sent_text
        assert "cannot be undone" in sent_text.lower()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.delete_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_delete_tries_to_remove_qdrant_point(self, mock_get, mock_delete, mock_log, mock_send):
        product = FakeProduct(qdrant_point_id="10")
        mock_get.return_value = product

        with patch("src.services.qdrant_service.QdrantService") as MockQdrant:
            mock_qdrant = AsyncMock()
            MockQdrant.return_value = mock_qdrant
            await handle_delete(_mock_db(), FakeMerchant(), "10", "+256700000000")
            mock_qdrant.delete_product.assert_awaited_once_with(10)

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.delete_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_delete_without_qdrant_point_does_not_crash(self, mock_get, mock_delete, mock_log, mock_send):
        product = FakeProduct(qdrant_point_id=None)
        mock_get.return_value = product

        await handle_delete(_mock_db(), FakeMerchant(), "10", "+256700000000")
        mock_delete.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_no_args_shows_usage(self, mock_send):
        await handle_delete(_mock_db(), FakeMerchant(), "", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_product_id(self, mock_send):
        await handle_delete(_mock_db(), FakeMerchant(), "abc", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "Invalid product ID" in sent_text

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock, return_value=None)
    async def test_product_not_found(self, mock_get, mock_send):
        await handle_delete(_mock_db(), FakeMerchant(), "999", "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "not found" in sent_text.lower()


# ---------------------------------------------------------------------------
# @help command via handle_merchant_command
# ---------------------------------------------------------------------------

class TestHandleMerchantCommandHelp:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_help_sends_all_commands(self, mock_send):
        await handle_merchant_command(
            _mock_db(), AsyncMock(), FakeMerchant(), "@help", {"from": "+256700000000"}
        )
        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "@register" in sent_text
        assert "@post" in sent_text
        assert "@edit" in sent_text
        assert "@stock" in sent_text
        assert "@price" in sent_text
        assert "@delete" in sent_text
        assert "@help" in sent_text


# ---------------------------------------------------------------------------
# handle_edit – log_whatsapp_outbound called
# ---------------------------------------------------------------------------

class TestEditLogging:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_logs_after_successful_edit(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product
        await handle_edit(_mock_db(), FakeMerchant(), "10 name New Name", "+256700000000")
        mock_log.assert_called_once_with("+256700000000", "text")

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_no_log_when_edit_fails_validation(self, mock_get, mock_update, mock_log, mock_send):
        await handle_edit(_mock_db(), FakeMerchant(), "abc name val", "+256700000000")
        mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# handle_stock – log_whatsapp_outbound called
# ---------------------------------------------------------------------------

class TestStockLogging:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_logs_after_successful_stock(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product
        await handle_stock(_mock_db(), FakeMerchant(), "10 100", "+256700000000")
        mock_log.assert_called_once_with("+256700000000", "text")


# ---------------------------------------------------------------------------
# handle_price – log_whatsapp_outbound called
# ---------------------------------------------------------------------------

class TestPriceLogging:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.update_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_logs_after_successful_price(self, mock_get, mock_update, mock_log, mock_send):
        product = FakeProduct()
        mock_get.return_value = product
        mock_update.return_value = product
        await handle_price(_mock_db(), FakeMerchant(), "10 30000", "+256700000000")
        mock_log.assert_called_once_with("+256700000000", "text")


# ---------------------------------------------------------------------------
# handle_delete – log_whatsapp_outbound called
# ---------------------------------------------------------------------------

class TestDeleteLogging:
    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.delete_product", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock)
    async def test_logs_after_successful_delete(self, mock_get, mock_delete, mock_log, mock_send):
        mock_get.return_value = FakeProduct()
        await handle_delete(_mock_db(), FakeMerchant(), "10", "+256700000000")
        mock_log.assert_called_once_with("+256700000000", "text")

    @pytest.mark.asyncio
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.get_product_by_id_and_merchant", new_callable=AsyncMock, return_value=None)
    async def test_no_log_when_product_not_found(self, mock_get, mock_log, mock_send):
        await handle_delete(_mock_db(), FakeMerchant(), "999", "+256700000000")
        mock_log.assert_not_called()
