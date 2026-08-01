from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from sqlalchemy import select

from src.domain.models import Merchant, Product, ProductImage, SubscriptionPlan, ResultCode
from src.domain.commands import parse_command, COMMANDS
from src.domain.enums import WizardStep, ProductStatus, ModerationStatus
from src.services.redis_service import get_wizard_step, set_wizard_step, clear_wizard
from src.services.postgres_service import (
    create_merchant,
    get_merchant_by_phone,
    get_product_by_id_and_merchant,
    update_product,
    delete_product,
    get_all_active_plans,
    get_active_plan,
    get_active_subscription,
    subscribe_merchant,
    seed_default_plans,
)
from src.services.whatsapp import send_text, download_media
from src.services.object_storage import upload_image
from src.shared.phone_utils import validate_phone, normalize_phone
from src.shared.rate_limiter import check_register_rate_limit
from src.shared.merchant_limits import check_listing_limit
from src.shared.logging import log_whatsapp_outbound
from src.core.config import settings


async def handle_merchant_command(
    db: AsyncSession,
    redis: Redis,
    merchant: Merchant,
    text: str,
    payload: dict,
) -> None:
    parsed = parse_command(text)
    if not parsed:
        return
    cmd, args = parsed
    from_number = payload.get("from", "")

    if cmd == "register":
        if merchant:
            await send_text(from_number, "You are already registered.")
            return
        normalized = normalize_phone(from_number)
        if not validate_phone(normalized):
            await send_text(from_number, "Invalid phone number. Please contact support.")
            return
        limited = await check_register_rate_limit(redis, normalized)
        if limited:
            await send_text(from_number, f"Registration is limited to {settings.register_rate_limit_per_number} attempts per {settings.register_rate_limit_window_hours} hours. Please try again later.")
            return
        await start_register_wizard(redis, from_number)

    elif cmd == "post":
        await handle_post(db, merchant, args, payload)

    elif cmd == "edit":
        await handle_edit(db, merchant, args, from_number)

    elif cmd == "stock":
        await handle_stock(db, merchant, args, from_number)

    elif cmd == "price":
        await handle_price(db, merchant, args, from_number)

    elif cmd == "delete":
        await handle_delete(db, merchant, args, from_number)

    elif cmd == "help":
        help_text = (
            "Available commands:\n"
            "@register - Register your business\n"
            "@plans - View subscription plans\n"
            "@subscribe [plan] - Subscribe to a plan (1-4)\n"
            "@post [image] [caption] - Post a new product\n"
            "@edit [product_id] [field] [value] - Edit a product\n"
            "@stock [product_id] [qty] - Update stock\n"
            "@price [product_id] [amount] - Update price\n"
            "@delete [product_id] - Remove a product\n"
            "@code [RS-XXXX] - Look up a customer's search result code\n"
            "@help - Show this message"
        )
        await send_text(from_number, help_text)

    elif cmd == "plans":
        await handle_plans(db, from_number)

    elif cmd == "subscribe":
        await handle_subscribe(db, merchant, args, from_number)

    elif cmd == "code":
        await handle_code(db, args, from_number)


async def start_register_wizard(redis: Redis, from_number: str) -> None:
    await set_wizard_step(redis, from_number, WizardStep.business_name.value)
    await send_text(from_number, "Welcome to whatAppseller! Let's set up your shop.\n\nWhat is your business name?")


async def handle_wizard_step(
    db: AsyncSession,
    redis: Redis,
    from_number: str,
    text: str,
    payload: dict,
    wizard: dict,
) -> None:
    step = wizard.get("step")
    data = wizard.get("data", {})

    if step == WizardStep.business_name.value:
        data["business_name"] = text
        await set_wizard_step(redis, from_number, WizardStep.category.value, data)
        await send_text(from_number, f"Great! What category best describes your business?\n\nExamples: Electronics, Clothing, Food, Furniture, Beauty, Other")

    elif step == WizardStep.category.value:
        data["category"] = text
        await set_wizard_step(redis, from_number, WizardStep.location.value, data)
        await send_text(from_number, "Please share your location.\n\nSend a WhatsApp location pin, or type your city/district name.")

    elif step == WizardStep.location.value:
        data["location"] = text
        await set_wizard_step(redis, from_number, WizardStep.confirm.value, data)
        confirm_text = (
            "Please confirm your details:\n\n"
            f"Business name: {data.get('business_name')}\n"
            f"Category: {data.get('category')}\n"
            f"Location: {data.get('location')}\n\n"
            "Reply 'yes' to confirm, or 'no' to start over."
        )
        await send_text(from_number, confirm_text)

    elif step == WizardStep.confirm.value:
        if text.lower() in ("yes", "y", "confirm"):
            merchant = await create_merchant(
                db,
                phone=from_number,
                business_name=data.get("business_name", ""),
                category=data.get("category", ""),
            )
            # Auto-assign Starter plan
            await seed_default_plans(db)
            from src.domain.enums import PlanSlug
            starter_plan = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.slug == PlanSlug.starter)
            )
            starter_plan = starter_plan.scalar_one_or_none()
            if starter_plan:
                await subscribe_merchant(db, merchant.id, starter_plan.id)

            await clear_wizard(redis, from_number)
            await send_text(
                from_number,
                f"Your shop '{merchant.business_name}' is now active!\n\n"
                "You've been assigned the *Starter* plan (Free, 5 products).\n"
                "Send @plans to see all available subscription plans.\n"
                "Type @help to see all available commands."
            )
        else:
            await clear_wizard(redis, from_number)
            await send_text(from_number, "Registration cancelled. Send @register to start over.")

    else:
        await clear_wizard(redis, from_number)
        await send_text(from_number, "Something went wrong. Please send @register to start over.")


async def handle_post(
    db: AsyncSession,
    merchant: Merchant,
    args: str,
    payload: dict,
) -> None:
    from_number = payload.get("from", "")
    image_data = payload.get("image")

    can_post, limit_reason = await check_listing_limit(db, merchant)
    if not can_post:
        await send_text(from_number, limit_reason)
        return

    if not image_data:
        await send_text(from_number, "To post a product, send a photo with a caption like:\n@post [name] [price]\n\nExample: @post Red Dress 50000")
        return

    media_id = image_data.get("id")
    if not media_id:
        await send_text(from_number, "Could not process the image. Please try again.")
        return

    image_bytes = await download_media(media_id)
    if not image_bytes:
        await send_text(from_number, "Could not download the image. Please try again.")
        return

    storage_url = await upload_image(image_bytes)

    name = "Product"
    price = 0.0

    if args:
        parts = args.rsplit(None, 1)
        if len(parts) == 2 and parts[1].replace(".", "").replace(",", "").isdigit():
            name = parts[0]
            price = float(parts[1].replace(",", ""))
        else:
            name = args

    product = Product(
        merchant_id=merchant.id,
        name=name,
        category=merchant.category,
        price=price,
        stock_qty=0,
        status=ProductStatus.active,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    product_image = ProductImage(
        product_id=product.id,
        storage_url=storage_url,
        is_primary=True,
    )
    db.add(product_image)
    await db.commit()

    await send_text(
        from_number,
        f"Product posted!\n\n"
        f"Name: {product.name}\n"
        f"Price: {price:,.0f} UGX\n"
        f"Image saved.\n\n"
        f"Use @edit {product.id} [field] [value] to update details.\n"
        f"Use @stock {product.id} [qty] to set stock quantity."
    )

    # Index product in Qdrant vector database
    try:
        from src.workers.vision_pipeline import VisionPipeline
        pipeline = VisionPipeline()
        result = await pipeline.process_product_image(
            product_id=product.id,
            image_bytes=image_bytes,
            merchant_id=merchant.id,
            product_name=product.name,
            product_category=product.category,
            product_brand=product.brand or "",
            product_price=product.price,
            merchant_lat=merchant.location_lat,
            merchant_lng=merchant.location_lng,
        )
        if result.get("indexed"):
            product.qdrant_point_id = str(product.id)
            await db.commit()
    except Exception:
        # Non-fatal: product is still listed, just not yet searchable by image
        pass


async def handle_edit(
    db: AsyncSession,
    merchant: Merchant,
    args: str,
    from_number: str,
) -> None:
    if not args:
        await send_text(
            from_number,
            "Usage: @edit [product_id] [field] [value]\n\n"
            "Fields: name, description, price, stock_qty\n"
            "Example: @edit 12 name Red Dress",
        )
        return

    parts = args.strip().split(None, 2)
    if len(parts) < 3:
        await send_text(
            from_number,
            "Usage: @edit [product_id] [field] [value]\n"
            "Example: @edit 12 name Red Dress",
        )
        return

    product_id_str, field, value = parts[0], parts[1].lower(), parts[2]

    if not product_id_str.isdigit():
        await send_text(from_number, "Invalid product ID. Use a number like: @edit 12 name Red Dress")
        return

    product_id = int(product_id_str)
    product = await get_product_by_id_and_merchant(db, product_id, merchant.id)

    if not product:
        await send_text(from_number, f"Product #{product_id} not found or doesn't belong to your shop.")
        return

    allowed_fields = {"name", "description", "price", "stock_qty"}
    if field not in allowed_fields:
        await send_text(
            from_number,
            f"Unknown field '{field}'. Allowed fields: {', '.join(sorted(allowed_fields))}",
        )
        return

    update_fields = {}

    if field == "name":
        if not value.strip():
            await send_text(from_number, "Product name cannot be empty.")
            return
        update_fields["name"] = value.strip()

    elif field == "description":
        update_fields["description"] = value.strip()

    elif field == "price":
        clean_price = value.strip().replace(",", "").replace("UGX", "").replace("ugx", "").strip()
        if not clean_price.replace(".", "").isdigit():
            await send_text(from_number, f"Invalid price '{value}'. Use a number like: @edit {product_id} price 50000")
            return
        price_val = float(clean_price)
        if price_val < 0:
            await send_text(from_number, "Price cannot be negative.")
            return
        update_fields["price"] = price_val

    elif field == "stock_qty":
        clean_qty = value.strip()
        if not clean_qty.isdigit():
            await send_text(from_number, f"Invalid quantity '{value}'. Use a whole number like: @edit {product_id} stock_qty 10")
            return
        qty_val = int(clean_qty)
        if qty_val < 0:
            await send_text(from_number, "Stock quantity cannot be negative.")
            return
        update_fields["stock_qty"] = qty_val

    updated = await update_product(db, product, **update_fields)

    field_display = field
    new_value_display = value.strip()
    if field == "price":
        price_clean = value.strip().upper().replace("UGX", "").replace("SHS", "").replace(",", "").strip()
        new_value_display = f"{float(price_clean):,.0f} UGX"
    elif field == "stock_qty":
        new_value_display = f"{int(value.strip())} units"

    await send_text(
        from_number,
        f"Product #{product.id} updated!\n\n"
        f"Field: {field_display}\n"
        f"New value: {new_value_display}\n"
        f"Product name: {updated.name}",
    )
    log_whatsapp_outbound(from_number, "text")


async def handle_stock(
    db: AsyncSession,
    merchant: Merchant,
    args: str,
    from_number: str,
) -> None:
    if not args:
        await send_text(
            from_number,
            "Usage: @stock [product_id] [qty]\n\n"
            "Example: @stock 12 50\n"
            "Sets the stock quantity for product #12 to 50 units.",
        )
        return

    parts = args.strip().split()
    if len(parts) != 2:
        await send_text(from_number, "Usage: @stock [product_id] [qty]\nExample: @stock 12 50")
        return

    product_id_str, qty_str = parts

    if not product_id_str.isdigit():
        await send_text(from_number, "Invalid product ID. Use a number like: @stock 12 50")
        return

    if not qty_str.isdigit():
        await send_text(from_number, f"Invalid quantity '{qty_str}'. Use a whole number.")
        return

    product_id = int(product_id_str)
    qty = int(qty_str)

    if qty < 0:
        await send_text(from_number, "Stock quantity cannot be negative.")
        return

    product = await get_product_by_id_and_merchant(db, product_id, merchant.id)

    if not product:
        await send_text(from_number, f"Product #{product_id} not found or doesn't belong to your shop.")
        return

    old_qty = product.stock_qty
    updated = await update_product(db, product, stock_qty=qty)

    status_msg = ""
    if old_qty == 0 and qty > 0:
        status_msg = "\n\nYour product is now back in stock!"
    elif qty == 0:
        status_msg = "\n\nNote: Your product is now marked as out of stock."

    await send_text(
        from_number,
        f"Stock updated for '{updated.name}' (#{product.id})\n\n"
        f"Previous: {old_qty} units\n"
        f"New: {qty} units"
        f"{status_msg}",
    )
    log_whatsapp_outbound(from_number, "text")


async def handle_price(
    db: AsyncSession,
    merchant: Merchant,
    args: str,
    from_number: str,
) -> None:
    if not args:
        await send_text(
            from_number,
            "Usage: @price [product_id] [amount]\n\n"
            "Example: @price 12 75000\n"
            "Sets the price of product #12 to 75,000 UGX.",
        )
        return

    parts = args.strip().split()
    if len(parts) != 2:
        await send_text(from_number, "Usage: @price [product_id] [amount]\nExample: @price 12 75000")
        return

    product_id_str, price_str = parts

    if not product_id_str.isdigit():
        await send_text(from_number, "Invalid product ID. Use a number like: @price 12 75000")
        return

    clean_price = price_str.replace(",", "").replace("UGX", "").replace("ugx", "").strip()
    if not clean_price.replace(".", "").isdigit():
        await send_text(from_number, f"Invalid price '{price_str}'. Use a number like: @price 12 75000")
        return

    product_id = int(product_id_str)
    new_price = float(clean_price)

    if new_price < 0:
        await send_text(from_number, "Price cannot be negative.")
        return

    product = await get_product_by_id_and_merchant(db, product_id, merchant.id)

    if not product:
        await send_text(from_number, f"Product #{product_id} not found or doesn't belong to your shop.")
        return

    old_price = product.price
    updated = await update_product(db, product, price=new_price)

    await send_text(
        from_number,
        f"Price updated for '{updated.name}' (#{product.id})\n\n"
        f"Previous: {old_price:,.0f} UGX\n"
        f"New: {new_price:,.0f} UGX",
    )
    log_whatsapp_outbound(from_number, "text")


async def handle_delete(
    db: AsyncSession,
    merchant: Merchant,
    args: str,
    from_number: str,
) -> None:
    if not args:
        await send_text(
            from_number,
            "Usage: @delete [product_id]\n\n"
            "Example: @delete 12\n"
            "Permanently removes product #12 from your shop.",
        )
        return

    product_id_str = args.strip().split()[0]

    if not product_id_str.isdigit():
        await send_text(from_number, "Invalid product ID. Use a number like: @delete 12")
        return

    product_id = int(product_id_str)
    product = await get_product_by_id_and_merchant(db, product_id, merchant.id)

    if not product:
        await send_text(from_number, f"Product #{product_id} not found or doesn't belong to your shop.")
        return

    product_name = product.name
    product_id = product.id

    # Delete from Qdrant first (product_id is the Qdrant point ID)
    try:
        from src.services.qdrant_service import QdrantService
        qdrant = QdrantService()
        await qdrant.delete_product(product_id)
    except Exception:
        pass

    await delete_product(db, product)

    await send_text(
        from_number,
        f"Product deleted!\n\n"
        f"Name: {product_name}\n"
        f"ID: #{product_id}\n\n"
        f"This action cannot be undone.",
    )
    log_whatsapp_outbound(from_number, "text")


# ─── Subscription Commands ─────────────────────────────────────────────────────


async def handle_plans(db: AsyncSession, from_number: str) -> None:
    await seed_default_plans(db)
    plans = await get_all_active_plans(db)

    if not plans:
        await send_text(from_number, "No subscription plans available at the moment. Please try again later.")
        return

    # Check current subscription for this phone
    from src.services.postgres_service import get_merchant_by_phone
    merchant = await get_merchant_by_phone(db, from_number)
    current_plan_slug = None
    if merchant:
        current_plan = await get_active_plan(db, merchant.id)
        if current_plan:
            current_plan_slug = current_plan.slug.value

    lines = ["*Subscription Plans*\n"]
    for i, plan in enumerate(plans, 1):
        price_str = "Free" if plan.price == 0 else f"{plan.price:,.0f} {plan.currency}"
        marker = " (your current plan)" if current_plan_slug == plan.slug.value else ""
        lines.append(
            f"*{i}. {plan.name}*{marker}\n"
            f"   Price: {price_str}/month\n"
            f"   Products: {plan.max_products if plan.max_products < 999999 else 'Unlimited'}\n"
            f"   Images per product: {plan.max_images_per_product}\n"
            f"   {plan.description}\n"
        )

    lines.append("To subscribe, send: @subscribe [plan number]\nExample: @subscribe 2")
    await send_text(from_number, "\n".join(lines))
    log_whatsapp_outbound(from_number, "text")


async def handle_code(
    db: AsyncSession,
    args: str,
    from_number: str,
) -> None:
    if not args or not args.strip():
        await send_text(
            from_number,
            "Usage: @code RS-XXXX\n\n"
            "Ask your customer to share their search result code (e.g. RS-A3K2).\n"
            "Enter it here to see what they're looking for.",
        )
        return

    code = args.strip().upper()
    result = await db.execute(
        select(ResultCode).where(ResultCode.code == code)
    )
    record = result.scalar_one_or_none()

    if not record:
        await send_text(from_number, f"No results found for code *{code}*. Ask the customer to double-check the code.")
        return

    lines = [f"*Customer is looking for:*"]
    if record.search_query:
        lines.append(f"\"{record.search_query}\"")
    if record.image_description:
        lines.append(f"Image: {record.image_description}")
    if record.category:
        lines.append(f"Category: {record.category}")
    if record.price_min is not None or record.price_max is not None:
        price_min = f"{record.price_min:,.0f}" if record.price_min else "?"
        price_max = f"{record.price_max:,.0f}" if record.price_max else "?"
        lines.append(f"Price range: {price_min} - {price_max} UGX")
    lines.append(f"Matching products found: {len(record.product_ids)}")
    if record.sample_products:
        names = [s.get("name", "Product") for s in record.sample_products]
        lines.append(f"Examples: {', '.join(names)}")
    lines.append(f"Searched: {record.created_at.strftime('%b %d, %Y at %H:%M') if record.created_at else 'recently'}")

    await send_text(from_number, "\n".join(lines))


async def handle_subscribe(
    db: AsyncSession,
    merchant: Merchant | None,
    args: str,
    from_number: str,
) -> None:
    if not merchant:
        await send_text(from_number, "You need to register first. Send @register to get started.")
        return

    if not args or not args.strip().isdigit():
        await send_text(
            from_number,
            "Usage: @subscribe [plan number]\n\n"
            "Send @plans to see available plans.\n"
            "Example: @subscribe 2",
        )
        return

    plan_number = int(args.strip())
    if plan_number < 1 or plan_number > 4:
        await send_text(from_number, "Invalid plan number. Send @plans to see available options (1-4).")
        return

    await seed_default_plans(db)
    plans = await get_all_active_plans(db)

    if plan_number > len(plans):
        await send_text(from_number, "Invalid plan number. Send @plans to see available options.")
        return

    target_plan = plans[plan_number - 1]

    # Check if already on this plan
    current_sub = await get_active_subscription(db, merchant.id)
    if current_sub and current_sub.plan_id == target_plan.id:
        await send_text(from_number, f"You are already subscribed to the *{target_plan.name}* plan.")
        return

    # Subscribe
    subscription = await subscribe_merchant(db, merchant.id, target_plan.id)

    price_str = "Free" if target_plan.price == 0 else f"{target_plan.price:,.0f} {target_plan.currency}"
    product_limit = target_plan.max_products if target_plan.max_products < 999999 else "Unlimited"

    await send_text(
        from_number,
        f"Subscribed to *{target_plan.name}*!\n\n"
        f"Price: {price_str}/month\n"
        f"Max products: {product_limit}\n"
        f"Images per product: {target_plan.max_images_per_product}\n\n"
        f"Your plan is now active. Happy selling!",
    )
    log_whatsapp_outbound(from_number, "text")
