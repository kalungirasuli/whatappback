import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import async_session_factory, get_redis
from src.domain.commands import is_merchant_command
from src.services.redis_service import get_session, get_wizard_step
from src.services.postgres_service import (
    create_buyer,
    ensure_whatsapp_user,
    get_buyer_by_phone,
    get_merchant_by_phone,
)
from src.domain.enums import MessageRole, UserRole
from src.services.conversation_context import ConversationContext
from src.workers.queue import register_handler, process_queue
from src.workers.nlu_router import extract_nlu, execute_intent_searches, compose_multi_intent_reply, process_batch
from src.services.whatsapp import send_text, download_media
from src.llm_agent.agent import SalesAgent


_context = ConversationContext()


async def _room(
    db: AsyncSession, from_number: str, role: MessageRole, merchant_id: int | None = None
):
    return await _context.ensure_conversation(db, from_number, role, merchant_id)


async def _reply(
    db: AsyncSession, redis, conversation_id: int, from_number: str, user_turn: str, reply: str
) -> None:
    await _context.append(db, redis, conversation_id, "user", user_turn)
    await _context.append(db, redis, conversation_id, "assistant", reply)
    await send_text(from_number, reply)


async def route_message(payload: dict) -> None:
    from_number = payload.get("from", "")
    msg_type = payload.get("type", "")
    text = ""
    image = None

    if msg_type == "text" and payload.get("text"):
        text = (payload["text"].get("body") or "").strip()
    elif msg_type == "image" and payload.get("image"):
        image = payload["image"]
        caption = (image.get("caption") or "").strip()
        if caption and caption.startswith("@"):
            text = caption

    if not text and not image:
        return

    async with async_session_factory() as db:
        redis = await get_redis()
        merchant = await get_merchant_by_phone(db, from_number)
        buyer = await get_buyer_by_phone(db, from_number)

        # WhatsApp phone numbers are already verified by the channel. Create the
        # application identity on first contact without asking for OTP.
        await ensure_whatsapp_user(
            db,
            from_number,
            UserRole.merchant if merchant else UserRole.client,
        )
        if not merchant and buyer is None:
            buyer = await create_buyer(db, from_number)

        if buyer and buyer.is_banned:
            return

        # Precedence rule [0]: active wizard → continues wizard
        wizard = await get_wizard_step(redis, from_number)
        if wizard:
            from src.workers.merchant_commands import handle_wizard_step
            await handle_wizard_step(db, redis, from_number, text, payload, wizard)
            return

        # Precedence rule [1]: merchant + @command → merchant_commands
        if merchant and merchant.status == "approved" and text and is_merchant_command(text):
            from src.workers.merchant_commands import handle_merchant_command
            await handle_merchant_command(db, redis, merchant, text, payload)
            return

# Precedence rule [2]: buyer text/image → NLU with multi-intent support
        if not merchant and (text or image):
            conversation = await _room(db, from_number, MessageRole.buyer)
            room = await _context.load_context(db, redis, conversation.id)
            user_turn = text or ("[image]" if image else "")

            nlu_result = await extract_nlu(
                text or "", has_image=image is not None, history=room["messages"]
            )

            has_search_intent = any(
                si.type in ("visual_search", "product_search")
                for si in nlu_result.search_intents
            )

            has_greeting = any(si.type == "greeting" for si in nlu_result.search_intents)
            has_help = any(si.type == "help" for si in nlu_result.search_intents)

            if has_greeting and not has_search_intent:
                await _reply(
                    db, redis, conversation.id, from_number, user_turn,
                    "Hello! Welcome to whatAppseller.\n\n"
                    "Send a photo or describe what you're looking for, "
                    "and I'll find matching products from local sellers!",
                )
                return

            if has_help:
                await _reply(
                    db, redis, conversation.id, from_number, user_turn,
                    "Here's what I can do:\n\n"
                    "1. Send a photo of a product you want - I'll find similar items\n"
                    "2. Type what you're looking for - e.g. 'Looking for red shoes under 100000'\n"
                    "3. I'll show matching products from nearby sellers\n\n"
                    "You can filter by:\n"
                    "- Color: 'blue shirt'\n"
                    "- Price: 'phone under 500000'\n"
                    "- Category: 'electronics', 'clothing', 'shoes', etc.",
                )
                return

            if has_search_intent:
                has_visual = any(si.type == "visual_search" for si in nlu_result.search_intents)
                image_bytes = None

                if has_visual and image:
                    media_id = image.get("id")
                    if media_id:
                        image_bytes = await download_media(media_id)

                search_intents = [
                    si for si in nlu_result.search_intents
                    if si.type in ("visual_search", "product_search")
                ]

                if search_intents:
                    results = await execute_intent_searches(search_intents, image_bytes)
                    reply = await compose_multi_intent_reply(results)
                    await _reply(db, redis, conversation.id, from_number, user_turn, reply)
                    return

            # Fall through to LLM agent for general questions / chat
            agent = SalesAgent()
            reply = await agent.compose_reply(
                nlu_result, from_number, conversation_history=room["messages"]
            )
            await _reply(db, redis, conversation.id, from_number, user_turn, reply)
            return

        # Precedence rule [3]: merchant without @command or free text → LLM help-desk
        if text:
            conversation = await _room(db, from_number, MessageRole.merchant,
                                       merchant.id if merchant else None)
            room = await _context.load_context(db, redis, conversation.id)
            agent = SalesAgent()
            reply = await agent.compose_merchant_reply(
                text, from_number, conversation_history=room["messages"]
            )
            await _reply(db, redis, conversation.id, from_number, text, reply)


async def route_batch(payload: dict) -> None:
    from_number = payload.get("from", "")
    reply = await process_batch(payload)
    from src.services.whatsapp import send_text
    await send_text(from_number, reply)


register_handler("incoming_message", route_message)
register_handler("batch", route_batch)


async def start_worker() -> None:
    await process_queue()


if __name__ == "__main__":
    asyncio.run(start_worker())
