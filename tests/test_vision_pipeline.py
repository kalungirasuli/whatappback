import io
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from PIL import Image

from src.services.detector import CroppedObject
from src.workers.vision_pipeline import VisionPipeline


def _make_image_bytes() -> bytes:
    img = Image.new("RGB", (200, 200), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_cropped() -> CroppedObject:
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return CroppedObject(
        image_bytes=buf.getvalue(),
        bbox=(50, 50, 150, 150),
        confidence=0.95,
        label="shirt",
    )


class TestProcessModerationReject:
    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_rejected_image(self, mock_mod, mock_emb, mock_det, mock_qdr):
        mock_mod.check_image = AsyncMock(return_value=MagicMock(
            is_approved=False, reason="Oversized", severity="block"
        ))
        mock_det.detect_and_crop = AsyncMock()
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        result = await pipeline.process_product_image(
            product_id=1, image_bytes=_make_image_bytes(), merchant_id=10
        )

        assert result["indexed"] is False
        assert result["moderation_rejected"] is True
        assert result["moderation_reason"] == "Oversized"
        assert result["crops_count"] == 0
        mock_det.detect_and_crop.assert_not_awaited()
        mock_qdr.upsert_product.assert_not_awaited()


class TestProcessHappyPath:
    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_approved_image_full_pipeline(self, mock_mod, mock_emb, mock_det, mock_qdr):
        mock_mod.check_image = AsyncMock(return_value=MagicMock(
            is_approved=True, reason=None, severity="info"
        ))
        mock_det.detect_and_crop = AsyncMock(return_value=[_make_cropped()])
        mock_emb.embed_image = AsyncMock(return_value=[0.1] * 512)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.2] * 768)
        mock_emb.embed_text = AsyncMock(return_value=[0.3] * 768)
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        result = await pipeline.process_product_image(
            product_id=42,
            image_bytes=_make_image_bytes(),
            merchant_id=10,
            product_name="Test Product",
            product_category="clothing",
            product_brand="BrandX",
            product_price=75000.0,
            merchant_lat=0.3136,
            merchant_lng=32.5811,
        )

        assert result["indexed"] is True
        assert result["product_id"] == 42
        assert result["crops_count"] == 1
        assert result["embedding_dim"] == 512

    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_upsert_receives_correct_metadata(self, mock_mod, mock_emb, mock_det, mock_qdr):
        mock_mod.check_image = AsyncMock(return_value=MagicMock(is_approved=True))
        mock_det.detect_and_crop = AsyncMock(return_value=[_make_cropped()])
        mock_emb.embed_image = AsyncMock(return_value=[0.1] * 512)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.2] * 768)
        mock_emb.embed_text = AsyncMock(return_value=[0.3] * 768)
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        await pipeline.process_product_image(
            product_id=7,
            image_bytes=_make_image_bytes(),
            merchant_id=3,
            product_name="Shoes",
            product_category="shoes",
            product_brand="Nike",
            product_price=120000.0,
            merchant_lat=1.0,
            merchant_lng=2.0,
        )

        call_kwargs = mock_qdr.upsert_product.call_args.kwargs
        assert call_kwargs["product_id"] == 7
        meta = call_kwargs["metadata"]
        assert meta["merchant_id"] == 3
        assert meta["product_name"] == "Shoes"
        assert meta["category"] == "shoes"
        assert meta["brand"] == "Nike"
        assert meta["price"] == 120000.0
        assert meta["merchant_lat"] == 1.0
        assert meta["merchant_lng"] == 2.0

    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_embedding_uses_first_crop(self, mock_mod, mock_emb, mock_det, mock_qdr):
        crop1 = CroppedObject(image_bytes=b"first_crop", bbox=(0, 0, 10, 10), confidence=0.9, label="a")
        crop2 = CroppedObject(image_bytes=b"second_crop", bbox=(20, 20, 30, 30), confidence=0.8, label="b")

        mock_mod.check_image = AsyncMock(return_value=MagicMock(is_approved=True))
        mock_det.detect_and_crop = AsyncMock(return_value=[crop1, crop2])
        mock_emb.embed_image = AsyncMock(return_value=[0.0] * 512)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.0] * 768)
        mock_emb.embed_text = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        await pipeline.process_product_image(
            product_id=1, image_bytes=_make_image_bytes(), merchant_id=1
        )

        mock_emb.embed_image.assert_awaited_once_with(b"first_crop")


class TestProcessNoCrops:
    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_no_crops_uses_original_image(self, mock_mod, mock_emb, mock_det, mock_qdr):
        image_bytes = _make_image_bytes()
        mock_mod.check_image = AsyncMock(return_value=MagicMock(is_approved=True))
        mock_det.detect_and_crop = AsyncMock(return_value=[])
        mock_emb.embed_image = AsyncMock(return_value=[0.0] * 512)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.0] * 768)
        mock_emb.embed_text = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        result = await pipeline.process_product_image(
            product_id=5, image_bytes=image_bytes, merchant_id=2
        )

        mock_emb.embed_image.assert_awaited_once_with(image_bytes)
        assert result["crops_count"] == 0
        assert result["indexed"] is True

    @patch("src.workers.vision_pipeline._qdrant")
    @patch("src.workers.vision_pipeline._detector")
    @patch("src.workers.vision_pipeline._embedding")
    @patch("src.workers.vision_pipeline._moderation")
    async def test_upsert_vector_dimensions(self, mock_mod, mock_emb, mock_det, mock_qdr):
        mock_mod.check_image = AsyncMock(return_value=MagicMock(is_approved=True))
        mock_det.detect_and_crop = AsyncMock(return_value=[])
        mock_emb.embed_image = AsyncMock(return_value=[0.1] * 512)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.2] * 768)
        mock_emb.embed_text = AsyncMock(return_value=[0.3] * 768)
        mock_qdr.upsert_product = AsyncMock()

        pipeline = VisionPipeline()
        await pipeline.process_product_image(
            product_id=1, image_bytes=_make_image_bytes(), merchant_id=1
        )

        call_kwargs = mock_qdr.upsert_product.call_args.kwargs
        assert len(call_kwargs["siglip_vector"]) == 512
        assert len(call_kwargs["dinov2_vector"]) == 768
        assert len(call_kwargs["text_vector"]) == 768
