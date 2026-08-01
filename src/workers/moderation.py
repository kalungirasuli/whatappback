import io
import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)

try:
    from src.core.config import settings as _settings
    _max_size_bytes = _settings.moderation_max_size_mb * 1024 * 1024
except Exception:
    _max_size_bytes = 10 * 1024 * 1024


@dataclass
class ModerationResult:
    is_approved: bool
    reason: str | None
    severity: str  # info | warning | block


class ModerationService:
    ALLOWED_TYPES = {"JPEG", "PNG", "WEBP"}

    async def check_image(self, image_bytes: bytes) -> ModerationResult:
        # Check 1: File size
        if len(image_bytes) > _max_size_bytes:
            max_mb = _max_size_bytes // (1024 * 1024)
            return ModerationResult(
                is_approved=False,
                reason=f"Image exceeds {max_mb}MB size limit",
                severity="block",
            )

        if len(image_bytes) == 0:
            return ModerationResult(
                is_approved=False,
                reason="Image file is empty",
                severity="block",
            )

        # Check 2: Valid format (JPEG/PNG/WebP) and not corrupted
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img.load()  # Force full decode to detect corruption

            fmt = (img.format or "").upper()
            if fmt not in self.ALLOWED_TYPES:
                return ModerationResult(
                    is_approved=False,
                    reason=f"Unsupported image format: {fmt}. Allowed: JPEG, PNG, WebP",
                    severity="block",
                )
        except Exception as e:
            return ModerationResult(
                is_approved=False,
                reason=f"Corrupted or unreadable image: {e}",
                severity="block",
            )

        # All checks passed
        return ModerationResult(
            is_approved=True,
            reason=None,
            severity="info",
        )
