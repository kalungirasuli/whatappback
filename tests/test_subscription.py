import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.commands import COMMANDS, is_merchant_command, parse_command
from src.domain.enums import PlanSlug, SubscriptionStatus
from src.domain.models import MerchantSubscription, SubscriptionPlan
from src.services.postgres_service import (
    get_active_plan,
    get_active_subscription,
    get_all_active_plans,
    get_plan_by_slug,
    seed_default_plans,
    subscribe_merchant,
)
from src.shared.merchant_limits import check_listing_limit
from src.workers.merchant_commands import handle_plans, handle_subscribe, handle_wizard_step


def _mock_result(scalar_value=None, scalars_list=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    result.scalar.return_value = scalar_value
    if scalars_list is not None:
        result.scalars.return_value.all.return_value = scalars_list
    return result


# -- 1. Model Creation ----------------------------------------------------------


class TestSubscriptionModels:
    def test_subscription_plan_creation(self):
        plan = SubscriptionPlan(
            name="Starter",
            slug=PlanSlug.starter,
            description="Free tier",
            price=0.0,
            currency="UGX",
            max_products=5,
            max_images_per_product=1,
            features='["basic_search"]',
            is_active=True,
            sort_order=1,
        )
        assert plan.name == "Starter"
        assert plan.slug == PlanSlug.starter
        assert plan.price == 0.0
        assert plan.currency == "UGX"
        assert plan.max_products == 5
        assert plan.max_images_per_product == 1
        assert plan.features == '["basic_search"]'
        assert plan.is_active is True
        assert plan.sort_order == 1

    def test_subscription_plan_defaults(self):
        plan = SubscriptionPlan(name="Test", slug=PlanSlug.growth)
        assert plan.price is None
        assert plan.currency is None
        assert plan.max_products is None
        assert plan.max_images_per_product is None
        assert plan.description is None
        assert plan.features is None

    def test_merchant_subscription_creation(self):
        sub = MerchantSubscription(
            merchant_id=1,
            plan_id=2,
            status=SubscriptionStatus.active,
        )
        assert sub.merchant_id == 1
        assert sub.plan_id == 2
        assert sub.status == SubscriptionStatus.active
        assert sub.expires_at is None

    def test_merchant_subscription_default_status(self):
        sub = MerchantSubscription(merchant_id=1, plan_id=1)
        assert sub.status is None

    def test_plan_relationships_empty(self):
        plan = SubscriptionPlan(name="Pro", slug=PlanSlug.pro)
        assert plan.subscriptions == []

    def test_subscription_relationships_none(self):
        sub = MerchantSubscription(merchant_id=1, plan_id=1)
        assert sub.merchant is None
        assert sub.plan is None

    def test_plan_table_name(self):
        assert SubscriptionPlan.__tablename__ == "subscription_plans"

    def test_subscription_table_name(self):
        assert MerchantSubscription.__tablename__ == "merchant_subscriptions"


# -- 2. Enum Values -------------------------------------------------------------


class TestSubscriptionEnums:
    def test_subscription_status_values(self):
        assert SubscriptionStatus.active == "active"
        assert SubscriptionStatus.expired == "expired"
        assert SubscriptionStatus.cancelled == "cancelled"

    def test_subscription_status_members(self):
        assert set(SubscriptionStatus.__members__.keys()) == {
            "active",
            "expired",
            "cancelled",
        }

    def test_plan_slug_values(self):
        assert PlanSlug.starter == "starter"
        assert PlanSlug.growth == "growth"
        assert PlanSlug.pro == "pro"
        assert PlanSlug.enterprise == "enterprise"

    def test_plan_slug_members(self):
        assert set(PlanSlug.__members__.keys()) == {
            "starter",
            "growth",
            "pro",
            "enterprise",
        }

    def test_plan_slug_is_str_enum(self):
        assert isinstance(PlanSlug.starter, str)
        assert PlanSlug.starter == "starter"

    def test_subscription_status_is_str_enum(self):
        assert isinstance(SubscriptionStatus.active, str)
        assert SubscriptionStatus.active == "active"


# -- 3. Command Registration ----------------------------------------------------


class TestSubscriptionCommands:
    def test_plans_in_commands(self):
        assert "plans" in COMMANDS

    def test_subscribe_in_commands(self):
        assert "subscribe" in COMMANDS

    def test_plans_is_merchant_command(self):
        assert is_merchant_command("@plans") is True

    def test_subscribe_is_merchant_command(self):
        assert is_merchant_command("@subscribe 2") is True

    def test_subscribe_no_args_is_merchant_command(self):
        assert is_merchant_command("@subscribe") is True

    def test_parse_plans_no_args(self):
        result = parse_command("@plans")
        assert result == ("plans", "")

    def test_parse_plans_case_insensitive(self):
        result = parse_command("@PLANS")
        assert result == ("plans", "")

    def test_parse_subscribe_with_plan_number(self):
        result = parse_command("@subscribe 2")
        assert result == ("subscribe", "2")

    def test_parse_subscribe_no_args(self):
        result = parse_command("@subscribe")
        assert result == ("subscribe", "")

    def test_parse_subscribe_with_whitespace(self):
        result = parse_command("  @subscribe  3  ")
        assert result == ("subscribe", "3")


# -- 4. Service Functions -------------------------------------------------------


class TestSubscriptionService:
    async def test_get_all_active_plans(self):
        plan1 = MagicMock(sort_order=1)
        plan2 = MagicMock(sort_order=2)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[plan1, plan2])

        result = await get_all_active_plans(mock_db)

        assert len(result) == 2
        assert plan1 in result
        assert plan2 in result
        mock_db.execute.assert_awaited_once()

    async def test_get_all_active_plans_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])

        result = await get_all_active_plans(mock_db)

        assert result == []

    async def test_get_plan_by_slug_found(self):
        plan = MagicMock()
        plan.slug = "starter"
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=plan)

        result = await get_plan_by_slug(mock_db, "starter")

        assert result is plan

    async def test_get_plan_by_slug_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_plan_by_slug(mock_db, "nonexistent")

        assert result is None

    async def test_get_active_subscription_found(self):
        sub = MagicMock()
        sub.status = SubscriptionStatus.active
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=sub)

        result = await get_active_subscription(mock_db, 42)

        assert result is sub

    async def test_get_active_subscription_none(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_active_subscription(mock_db, 99)

        assert result is None

    async def test_get_active_plan_delegates(self):
        sub = MagicMock()
        sub.plan_id = 5
        plan = MagicMock()
        plan.name = "Growth"

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=sub),
            _mock_result(scalar_value=plan),
        ]

        result = await get_active_plan(mock_db, 10)

        assert result is plan

    async def test_get_active_plan_no_subscription(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        result = await get_active_plan(mock_db, 10)

        assert result is None

    async def test_subscribe_merchant_cancels_existing(self):
        existing_sub = MagicMock()
        existing_sub.status = SubscriptionStatus.active

        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=existing_sub)
        mock_db.refresh = AsyncMock()

        await subscribe_merchant(mock_db, 10, 2)

        assert existing_sub.status == SubscriptionStatus.cancelled
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    async def test_subscribe_merchant_no_existing(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        mock_db.refresh = AsyncMock()

        await subscribe_merchant(mock_db, 10, 2)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    async def test_seed_default_plans_skips_if_existing(self):
        existing_plan = MagicMock()
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=existing_plan)

        await seed_default_plans(mock_db)

        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_awaited()

    async def test_seed_default_plans_creates_plans(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        await seed_default_plans(mock_db)

        assert mock_db.add.call_count == 4
        mock_db.commit.assert_awaited_once()

    async def test_seed_default_plans_creates_correct_slugs(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)

        await seed_default_plans(mock_db)

        added_plans = [call.args[0] for call in mock_db.add.call_args_list]
        slugs = [p.slug for p in added_plans]
        assert slugs == [
            PlanSlug.starter,
            PlanSlug.growth,
            PlanSlug.pro,
            PlanSlug.enterprise,
        ]


# -- 5. handle_plans ------------------------------------------------------------


class TestHandlePlans:
    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_sends_formatted_plan_list(self, mock_send, mock_log):
        starter = SubscriptionPlan(
            name="Starter",
            slug=PlanSlug.starter,
            description="Free tier",
            price=0.0,
            currency="UGX",
            max_products=5,
            max_images_per_product=1,
            is_active=True,
            sort_order=1,
        )
        growth = SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            description="Growing business",
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
            is_active=True,
            sort_order=2,
        )

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[starter, growth]),
            _mock_result(scalar_value=None),
            _mock_result(scalar_value=None),
        ]

        await handle_plans(mock_db, "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Starter" in sent_text
        assert "Growth" in sent_text
        assert "Free" in sent_text
        assert "50,000 UGX" in sent_text
        assert "@subscribe" in sent_text

    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_no_plans_available(self, mock_send, mock_log):
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[]),
        ]

        await handle_plans(mock_db, "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "No subscription plans available" in sent_text

    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_marks_current_plan(self, mock_send, mock_log):
        plan = SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            description="For growing",
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
            is_active=True,
            sort_order=1,
        )

        merchant = MagicMock()
        merchant.id = 10

        current_plan = SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
        )

        sub = MagicMock()
        sub.plan_id = current_plan.id

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[plan]),
            _mock_result(scalar_value=merchant),
            _mock_result(scalar_value=sub),
            _mock_result(scalar_value=current_plan),
        ]

        await handle_plans(mock_db, "+256700000000")

        sent_text = mock_send.call_args[0][1]
        assert "your current plan" in sent_text


# -- 6. handle_subscribe --------------------------------------------------------


class TestHandleSubscribe:
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_not_registered(self, mock_send):
        mock_db = AsyncMock()

        await handle_subscribe(mock_db, None, "2", "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "register first" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_no_args(self, mock_send):
        merchant = MagicMock()
        merchant.id = 1
        mock_db = AsyncMock()

        await handle_subscribe(mock_db, merchant, "", "+256700000000")

        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_non_numeric_args(self, mock_send):
        merchant = MagicMock()
        merchant.id = 1
        mock_db = AsyncMock()

        await handle_subscribe(mock_db, merchant, "abc", "+256700000000")

        sent_text = mock_send.call_args[0][1]
        assert "Usage" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_invalid_plan_number_too_high(self, mock_send):
        merchant = MagicMock()
        merchant.id = 1
        mock_db = AsyncMock()

        await handle_subscribe(mock_db, merchant, "5", "+256700000000")

        sent_text = mock_send.call_args[0][1]
        assert "Invalid plan number" in sent_text

    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_valid_subscribe(self, mock_send, mock_log):
        merchant = MagicMock()
        merchant.id = 10

        plan = SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            description="Growing business",
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
            is_active=True,
            sort_order=2,
        )
        plan.id = 2

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[plan]),
            _mock_result(scalar_value=None),
            _mock_result(scalar_value=None),
        ]
        mock_db.refresh = AsyncMock()

        await handle_subscribe(mock_db, merchant, "1", "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Subscribed to" in sent_text
        assert "Growth" in sent_text
        assert "50,000 UGX" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_already_subscribed_to_same_plan(self, mock_send):
        merchant = MagicMock()
        merchant.id = 10

        plan = SubscriptionPlan(
            name="Starter",
            slug=PlanSlug.starter,
            price=0.0,
            currency="UGX",
            max_products=5,
            max_images_per_product=1,
            is_active=True,
            sort_order=1,
        )

        existing_sub = MagicMock()
        existing_sub.plan_id = plan.id

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[plan]),
            _mock_result(scalar_value=existing_sub),
        ]

        await handle_subscribe(mock_db, merchant, "1", "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "already subscribed" in sent_text
        assert "Starter" in sent_text

    @patch("src.workers.merchant_commands.log_whatsapp_outbound")
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    async def test_switches_from_different_plan(self, mock_send, mock_log):
        merchant = MagicMock()
        merchant.id = 10

        starter = SubscriptionPlan(
            name="Starter",
            slug=PlanSlug.starter,
            price=0.0,
            currency="UGX",
            max_products=5,
            max_images_per_product=1,
            is_active=True,
            sort_order=1,
        )
        starter.id = 1
        growth = SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
            is_active=True,
            sort_order=2,
        )
        growth.id = 2

        existing_sub = MagicMock()
        existing_sub.plan_id = starter.id

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [
            _mock_result(scalar_value=None),
            _mock_result(scalars_list=[starter, growth]),
            _mock_result(scalar_value=existing_sub),
            _mock_result(scalar_value=None),
        ]
        mock_db.refresh = AsyncMock()

        await handle_subscribe(mock_db, merchant, "2", "+256700000000")

        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Subscribed to" in sent_text
        assert "Growth" in sent_text


# -- 7. Merchant Limits Plan Enforcement ----------------------------------------


class TestMerchantLimitsPlan:
    @patch("src.shared.merchant_limits.get_total_product_count", new_callable=AsyncMock)
    @patch("src.shared.merchant_limits.get_active_plan", new_callable=AsyncMock)
    async def test_blocks_when_at_limit(self, mock_get_plan, mock_get_count):
        merchant = MagicMock()
        merchant.id = 1
        merchant.created_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)

        plan = MagicMock()
        plan.name = "Starter"
        plan.max_products = 5

        mock_get_plan.return_value = plan
        mock_get_count.return_value = 5

        mock_db = AsyncMock()

        can_post, reason = await check_listing_limit(mock_db, merchant)

        assert can_post is False
        assert "Starter" in reason
        assert "5" in reason
        assert "@plans" in reason

    @patch("src.shared.merchant_limits.get_total_product_count", new_callable=AsyncMock)
    @patch("src.shared.merchant_limits.get_active_plan", new_callable=AsyncMock)
    async def test_allows_when_under_limit(self, mock_get_plan, mock_get_count):
        merchant = MagicMock()
        merchant.id = 1
        merchant.created_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)

        plan = MagicMock()
        plan.name = "Starter"
        plan.max_products = 5

        mock_get_plan.return_value = plan
        mock_get_count.return_value = 3

        mock_db = AsyncMock()

        can_post, reason = await check_listing_limit(mock_db, merchant)

        assert can_post is True
        assert reason is None

    @patch("src.shared.merchant_limits.get_total_product_count", new_callable=AsyncMock)
    @patch("src.shared.merchant_limits.get_active_plan", new_callable=AsyncMock)
    async def test_allows_unlimited_enterprise_plan(self, mock_get_plan, mock_get_count):
        merchant = MagicMock()
        merchant.id = 1
        merchant.created_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)

        plan = MagicMock()
        plan.name = "Enterprise"
        plan.max_products = 999999

        mock_get_plan.return_value = plan
        mock_get_count.return_value = 50000

        mock_db = AsyncMock()

        can_post, reason = await check_listing_limit(mock_db, merchant)

        assert can_post is True
        assert reason is None
        mock_get_count.assert_not_awaited()

    @patch("src.shared.merchant_limits.is_new_merchant", new_callable=AsyncMock)
    @patch("src.shared.merchant_limits.get_active_plan", new_callable=AsyncMock)
    async def test_blocks_when_exactly_at_limit(self, mock_get_plan, mock_is_new):
        merchant = MagicMock()
        merchant.id = 1

        plan = MagicMock()
        plan.name = "Growth"
        plan.max_products = 50

        mock_get_plan.return_value = plan
        mock_is_new.return_value = False

        async def count_side_effect(db, mid):
            return 50

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        with patch(
            "src.shared.merchant_limits.get_total_product_count", side_effect=count_side_effect
        ):
            can_post, reason = await check_listing_limit(mock_db, merchant)

        assert can_post is False
        assert "Growth" in reason
        assert "50" in reason


# -- 8. Auto-assign Starter on Registration -------------------------------------


class TestAutoAssignStarter:
    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.clear_wizard", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.subscribe_merchant", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.seed_default_plans", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.create_merchant", new_callable=AsyncMock)
    async def test_confirm_assigns_starter_plan(
        self, mock_create, mock_seed, mock_subscribe, mock_clear, mock_send
    ):
        new_merchant = MagicMock()
        new_merchant.id = 42
        new_merchant.business_name = "Test Shop"
        mock_create.return_value = new_merchant

        starter_plan = MagicMock()
        starter_plan.id = 1
        starter_plan.name = "Starter"

        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=starter_plan)
        mock_redis = AsyncMock()

        wizard = {
            "step": "confirm",
            "data": {
                "business_name": "Test Shop",
                "category": "Electronics",
                "location": "Kampala",
            },
        }

        await handle_wizard_step(mock_db, mock_redis, "+256700000000", "yes", {}, wizard)

        mock_seed.assert_awaited_once_with(mock_db)
        mock_subscribe.assert_awaited_once_with(mock_db, 42, 1)
        mock_clear.assert_awaited_once_with(mock_redis, "+256700000000")
        mock_send.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "Starter" in sent_text
        assert "5 products" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.clear_wizard", new_callable=AsyncMock)
    async def test_confirm_no_rejects(self, mock_clear, mock_send):
        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        wizard = {
            "step": "confirm",
            "data": {"business_name": "X", "category": "Y", "location": "Z"},
        }

        await handle_wizard_step(mock_db, mock_redis, "+256700000000", "no", {}, wizard)

        mock_clear.assert_awaited_once_with(mock_redis, "+256700000000")
        sent_text = mock_send.call_args[0][1]
        assert "cancelled" in sent_text

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.set_wizard_step", new_callable=AsyncMock)
    async def test_business_name_step_advances(self, mock_set, mock_send):
        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        wizard = {"step": "business_name", "data": {}}

        await handle_wizard_step(
            mock_db, mock_redis, "+256700000000", "My Shop", {}, wizard
        )

        mock_set.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "category" in sent_text.lower()

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.set_wizard_step", new_callable=AsyncMock)
    async def test_category_step_advances(self, mock_set, mock_send):
        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        wizard = {"step": "category", "data": {"business_name": "Shop"}}

        await handle_wizard_step(
            mock_db, mock_redis, "+256700000000", "Electronics", {}, wizard
        )

        mock_set.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "location" in sent_text.lower()

    @patch("src.workers.merchant_commands.send_text", new_callable=AsyncMock)
    @patch("src.workers.merchant_commands.set_wizard_step", new_callable=AsyncMock)
    async def test_location_step_advances_to_confirm(self, mock_set, mock_send):
        mock_db = AsyncMock()
        mock_redis = AsyncMock()

        wizard = {
            "step": "location",
            "data": {"business_name": "Shop", "category": "Electronics"},
        }

        await handle_wizard_step(
            mock_db, mock_redis, "+256700000000", "Kampala", {}, wizard
        )

        mock_set.assert_awaited_once()
        sent_text = mock_send.call_args[0][1]
        assert "confirm" in sent_text.lower()
        assert "Shop" in sent_text
