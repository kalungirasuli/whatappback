import logging
import sys

from src.core.config import settings
from src.shared.correlation import get_correlation_id


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


class WhatsAppCostFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "whatsapp_direction"):
            record.whatsapp_direction = "-"
        if not hasattr(record, "whatsapp_phone"):
            record.whatsapp_phone = "-"
        if not hasattr(record, "whatsapp_msg_type"):
            record.whatsapp_msg_type = "-"
        if not hasattr(record, "whatsapp_cost"):
            record.whatsapp_cost = 0.0
        return True


def setup_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(correlation_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationFilter())
    handler.addFilter(WhatsAppCostFilter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)


_whatsapp_logger = logging.getLogger("whatsapp.costs")


def log_whatsapp_message(
    direction: str,
    phone_number: str,
    message_type: str,
    cost: float = 0.0,
) -> None:
    masked = phone_number[:4] + "***" + phone_number[-3:] if len(phone_number) > 7 else "***"

    extra = {
        "whatsapp_direction": direction,
        "whatsapp_phone": masked,
        "whatsapp_msg_type": message_type,
        "whatsapp_cost": cost,
    }

    _whatsapp_logger.info(
        "WhatsApp %s | phone=%s | type=%s | cost=%.4f",
        direction,
        masked,
        message_type,
        cost,
        extra=extra,
    )


def log_whatsapp_inbound(phone_number: str, message_type: str = "text") -> None:
    log_whatsapp_message(direction="inbound", phone_number=phone_number, message_type=message_type, cost=0.0)


def log_whatsapp_outbound(phone_number: str, message_type: str = "text", cost: float = 0.005) -> None:
    log_whatsapp_message(direction="outbound", phone_number=phone_number, message_type=message_type, cost=cost)
