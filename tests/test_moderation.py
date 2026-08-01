import io
from unittest.mock import patch

import pytest
from PIL import Image

from src.workers.moderation import ModerationService, ModerationResult, _max_size_bytes


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_png_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_webp_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


class TestModerationValidImage:
    async def test_valid_jpeg_approved(self):
        svc = ModerationService()
        result = await svc.check_image(_make_jpeg_bytes())

        assert isinstance(result, ModerationResult)
        assert result.is_approved is True
        assert result.reason is None
        assert result.severity == "info"

    async def test_valid_png_approved(self):
        svc = ModerationService()
        result = await svc.check_image(_make_png_bytes())

        assert result.is_approved is True
        assert result.severity == "info"

    async def test_valid_webp_approved(self):
        svc = ModerationService()
        result = await svc.check_image(_make_webp_bytes())

        assert result.is_approved is True
        assert result.severity == "info"


class TestModerationOversized:
    async def test_oversized_file_rejected(self):
        svc = ModerationService()
        huge_data = b"\x00" * (_max_size_bytes + 1)

        result = await svc.check_image(huge_data)

        assert result.is_approved is False
        assert "size limit" in result.reason.lower()
        assert result.severity == "block"

    async def test_exact_max_size_accepted(self):
        svc = ModerationService()
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg_data = buf.getvalue()

        if len(jpeg_data) <= _max_size_bytes:
            result = await svc.check_image(jpeg_data)
            assert result.is_approved is True


class TestModerationCorrupted:
    async def test_corrupted_jpeg(self):
        svc = ModerationService()
        corrupted = b"\xff\xd8\xff\xe0corrupted_jpeg_data"

        result = await svc.check_image(corrupted)

        assert result.is_approved is False
        assert "corrupted" in result.reason.lower()
        assert result.severity == "block"

    async def test_garbage_bytes(self):
        svc = ModerationService()
        garbage = b"this is just plain text not an image"

        result = await svc.check_image(garbage)

        assert result.is_approved is False
        assert result.severity == "block"


class TestModerationEmpty:
    async def test_empty_bytes(self):
        svc = ModerationService()
        result = await svc.check_image(b"")

        assert result.is_approved is False
        assert "empty" in result.reason.lower()
        assert result.severity == "block"


class TestModerationInvalidFormat:
    async def test_bmp_format_rejected(self):
        svc = ModerationService()
        img = Image.new("RGB", (10, 10), color="yellow")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        bmp_data = buf.getvalue()

        result = await svc.check_image(bmp_data)

        assert result.is_approved is False
        assert "unsupported" in result.reason.lower()
        assert result.severity == "block"

    async def test_gif_format_rejected(self):
        svc = ModerationService()
        img = Image.new("RGB", (10, 10), color="pink")
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        gif_data = buf.getvalue()

        result = await svc.check_image(gif_data)

        assert result.is_approved is False
        assert "unsupported" in result.reason.lower()


class TestModerationAllowedTypes:
    def test_allowed_types_set(self):
        assert "JPEG" in ModerationService.ALLOWED_TYPES
        assert "PNG" in ModerationService.ALLOWED_TYPES
        assert "WEBP" in ModerationService.ALLOWED_TYPES
        assert len(ModerationService.ALLOWED_TYPES) == 3


class TestModerationResult:
    def test_moderation_result_fields(self):
        r = ModerationResult(is_approved=True, reason=None, severity="info")
        assert r.is_approved is True
        assert r.reason is None
        assert r.severity == "info"

    def test_moderation_result_blocked(self):
        r = ModerationResult(is_approved=False, reason="bad", severity="block")
        assert r.is_approved is False
        assert r.reason == "bad"
        assert r.severity == "block"
