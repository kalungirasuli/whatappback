from unittest.mock import AsyncMock, MagicMock

from src.services.postgres_service import (
    get_merchant_by_phone,
    create_merchant,
    create_buyer,
    get_buyer_by_phone,
    get_merchant_by_id,
    get_product_by_id,
)


def _mock_result(scalar_value=None, scalars_list=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    if scalars_list is not None:
        result.scalars.return_value.all.return_value = scalars_list
    return result


class TestGetMerchantByPhone:
    async def test_found(self):
        mock_merchant = MagicMock()
        mock_merchant.phone_number = "+256700000000"
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=mock_merchant)

        result = await get_merchant_by_phone(mock_db, "+256700000000")

        assert result is mock_merchant
        mock_db.execute.assert_awaited_once()

    async def test_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_merchant_by_phone(mock_db, "+256799999999")

        assert result is None


class TestGetMerchantById:
    async def test_found(self):
        mock_merchant = MagicMock()
        mock_merchant.id = 42
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=mock_merchant)

        result = await get_merchant_by_id(mock_db, 42)

        assert result is mock_merchant

    async def test_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_merchant_by_id(mock_db, 999)

        assert result is None


class TestGetBuyerByPhone:
    async def test_found(self):
        mock_buyer = MagicMock()
        mock_buyer.phone_number = "+256711111111"
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=mock_buyer)

        result = await get_buyer_by_phone(mock_db, "+256711111111")

        assert result is mock_buyer

    async def test_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_buyer_by_phone(mock_db, "+256799999999")

        assert result is None


class TestGetProductById:
    async def test_found(self):
        mock_product = MagicMock()
        mock_product.id = 7
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=mock_product)

        result = await get_product_by_id(mock_db, 7)

        assert result is mock_product

    async def test_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_product_by_id(mock_db, 999)

        assert result is None


class TestCreateMerchant:
    async def test_creates_merchant(self):
        mock_db = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 1

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await create_merchant(
            mock_db,
            phone="+256700000000",
            business_name="Test Shop",
            category="Electronics",
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        assert result.phone_number == "+256700000000"
        assert result.business_name == "Test Shop"
        assert result.category == "Electronics"

    async def test_creates_merchant_with_location(self):
        mock_db = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 2

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await create_merchant(
            mock_db,
            phone="+256700000001",
            business_name="Cafe",
            category="Food",
            lat=0.3476,
            lng=32.5825,
        )

        assert result.location_lat == 0.3476
        assert result.location_lng == 32.5825

    async def test_creates_merchant_without_location(self):
        mock_db = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 3

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await create_merchant(
            mock_db,
            phone="+256700000002",
            business_name="Shop",
            category="Clothing",
        )

        assert result.location_lat is None
        assert result.location_lng is None

    async def test_adds_to_db(self):
        mock_db = AsyncMock()
        mock_db.refresh = AsyncMock()

        await create_merchant(
            mock_db,
            phone="+256700000003",
            business_name="Store",
            category="Beauty",
        )

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.phone_number == "+256700000003"
        assert added_obj.business_name == "Store"
        assert added_obj.category == "Beauty"


class TestCreateBuyer:
    async def test_creates_buyer(self):
        mock_db = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 1

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await create_buyer(mock_db, phone="+256722222222")

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        assert result.phone_number == "+256722222222"

    async def test_buyer_defaults(self):
        mock_db = AsyncMock()

        async def fake_refresh(obj):
            obj.id = 1
            obj.is_banned = False

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await create_buyer(mock_db, phone="+256733333333")

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.phone_number == "+256733333333"
        assert added_obj.is_banned is False
