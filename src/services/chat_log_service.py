import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import ChatInteraction

logger = logging.getLogger(__name__)


class ChatLogService:
    """Persists every conversational turn with the retail receptionist so the
    assistant can be improved from real interactions."""

    @staticmethod
    def serialize_intents(intents: list) -> list[dict[str, Any]]:
        return [
            {
                "type": getattr(i, "type", "unknown"),
                "description": getattr(i, "description", ""),
                "entities": getattr(i, "entities", {}),
            }
            for i in intents
        ]

    @staticmethod
    def serialize_top_results(sections: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
        top: list[dict[str, Any]] = []
        for section in sections:
            for r in section.get("results", []):
                top.append(
                    {
                        "product_id": r.get("product_id"),
                        "name": r.get("name"),
                        "category": r.get("category"),
                        "score": r.get("score"),
                    }
                )
                if len(top) >= limit:
                    return top
        return top

    async def log(
        self,
        db: AsyncSession,
        *,
        user_id: int | None,
        phone_number: str,
        correlation_id: str | None,
        user_message_type: str,
        user_text: str | None,
        image_count: int,
        image_urls: list[str] | None,
        image_description: str | None,
        nlu_intents: list,
        text_topic: str | None,
        text_family: str | None,
        image_family: str | None,
        reply: dict[str, Any],
        latency_ms: int | None,
    ) -> None:
        row = ChatInteraction(
            user_id=user_id,
            phone_number=phone_number,
            correlation_id=correlation_id,
            user_message_type=user_message_type,
            user_text=user_text,
            image_count=image_count,
            image_urls=image_urls or [],
            image_description=image_description,
            nlu_intents=self.serialize_intents(nlu_intents),
            text_topic=text_topic,
            text_family=text_family,
            image_family=image_family,
            reply_type=reply.get("reply_type"),
            response_text=reply.get("response_text") or reply.get("text"),
            result_code=reply.get("result_code"),
            follow_up=reply.get("follow_up"),
            top_results=self.serialize_top_results(reply.get("sections", [])),
            latency_ms=latency_ms,
        )
        db.add(row)
        await db.commit()
        logger.info(
            "Logged chat interaction: phone=%s type=%s reply=%s",
            phone_number,
            user_message_type,
            reply.get("reply_type"),
        )
