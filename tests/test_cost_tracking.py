import pytest
import logging
from unittest.mock import patch, MagicMock

from src.shared.logging import (
    log_whatsapp_message,
    log_whatsapp_inbound,
    log_whatsapp_outbound,
    WhatsAppCostFilter,
    CorrelationFilter,
)
from src.shared.correlation import (
    get_correlation_id,
    set_correlation_id,
    reset_correlation_id,
)


# ---------------------------------------------------------------------------
# log_whatsapp_message
# ---------------------------------------------------------------------------

class TestLogWhatsAppMessage:
    def test_logs_inbound_message(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_message("inbound", "+256700123456", "text", cost=0.0)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "inbound" in record.getMessage()
        assert record.whatsapp_direction == "inbound"
        assert record.whatsapp_msg_type == "text"
        assert record.whatsapp_cost == 0.0

    def test_logs_outbound_message(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_message("outbound", "+256700123456", "image", cost=0.05)

        record = caplog.records[0]
        assert record.whatsapp_direction == "outbound"
        assert record.whatsapp_msg_type == "image"
        assert record.whatsapp_cost == 0.05

    def test_masks_phone_number(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_message("inbound", "+256700123456", "text")

        msg = caplog.records[0].getMessage()
        assert "+256700123456" not in msg
        assert "***" in msg

    def test_masks_short_phone(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_message("inbound", "123", "text")

        record = caplog.records[0]
        assert record.whatsapp_phone == "***"

    def test_extra_fields_present(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_message("inbound", "+256700123456", "template", cost=0.01)

        record = caplog.records[0]
        assert hasattr(record, "whatsapp_direction")
        assert hasattr(record, "whatsapp_phone")
        assert hasattr(record, "whatsapp_msg_type")
        assert hasattr(record, "whatsapp_cost")


# ---------------------------------------------------------------------------
# log_whatsapp_inbound
# ---------------------------------------------------------------------------

class TestLogWhatsAppInbound:
    def test_calls_log_whatsapp_message_with_inbound(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_inbound("+256700123456", "image")

        record = caplog.records[0]
        assert record.whatsapp_direction == "inbound"
        assert record.whatsapp_msg_type == "image"
        assert record.whatsapp_cost == 0.0

    def test_defaults_to_text(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_inbound("+256700123456")

        record = caplog.records[0]
        assert record.whatsapp_msg_type == "text"


# ---------------------------------------------------------------------------
# log_whatsapp_outbound
# ---------------------------------------------------------------------------

class TestLogWhatsAppOutbound:
    def test_calls_log_whatsapp_message_with_outbound(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_outbound("+256700123456", "template", cost=0.02)

        record = caplog.records[0]
        assert record.whatsapp_direction == "outbound"
        assert record.whatsapp_msg_type == "template"
        assert record.whatsapp_cost == 0.02

    def test_default_cost(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_outbound("+256700123456")

        record = caplog.records[0]
        assert record.whatsapp_cost == 0.005

    def test_default_message_type(self, caplog):
        with caplog.at_level(logging.INFO, logger="whatsapp.costs"):
            log_whatsapp_outbound("+256700123456")

        record = caplog.records[0]
        assert record.whatsapp_msg_type == "text"


# ---------------------------------------------------------------------------
# WhatsAppCostFilter
# ---------------------------------------------------------------------------

class TestWhatsAppCostFilter:
    def test_adds_missing_attrs(self):
        f = WhatsAppCostFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        result = f.filter(record)
        assert result is True
        assert record.whatsapp_direction == "-"
        assert record.whatsapp_phone == "-"
        assert record.whatsapp_msg_type == "-"
        assert record.whatsapp_cost == 0.0

    def test_preserves_existing_attrs(self):
        f = WhatsAppCostFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        record.whatsapp_direction = "inbound"
        record.whatsapp_phone = "masked"
        record.whatsapp_msg_type = "text"
        record.whatsapp_cost = 0.05
        result = f.filter(record)
        assert result is True
        assert record.whatsapp_direction == "inbound"
        assert record.whatsapp_cost == 0.05


# ---------------------------------------------------------------------------
# CorrelationFilter
# ---------------------------------------------------------------------------

class TestCorrelationFilter:
    def test_adds_correlation_id_from_context(self):
        set_correlation_id("test-corr-id")
        try:
            f = CorrelationFilter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            result = f.filter(record)
            assert result is True
            assert record.correlation_id == "test-corr-id"
        finally:
            reset_correlation_id()

    def test_adds_dash_when_no_correlation(self):
        reset_correlation_id()
        f = CorrelationFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        result = f.filter(record)
        assert result is True
        assert record.correlation_id == "-"


# ---------------------------------------------------------------------------
# Correlation ID context var
# ---------------------------------------------------------------------------

class TestCorrelationID:
    def test_set_and_get(self):
        cid = set_correlation_id("abc123")
        assert cid == "abc123"
        assert get_correlation_id() == "abc123"
        reset_correlation_id()

    def test_generates_uuid_when_none(self):
        cid = set_correlation_id(None)
        assert len(cid) == 16
        reset_correlation_id()

    def test_generate_empty_arg(self):
        cid = set_correlation_id("")
        assert len(cid) == 16
        reset_correlation_id()
