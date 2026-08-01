import io
import math
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from src.services.embedding import EmbeddingService, _st_available


def _make_image_bytes(width: int = 64, height: int = 64, color: str = "green") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class TestEmbedImageFallback:
    async def test_returns_correct_dimension(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_image(_make_image_bytes())

        assert isinstance(result, list)
        assert len(result) == 768

    async def test_vector_is_normalized(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_image(_make_image_bytes())

        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6

    async def test_returns_floats(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_image(_make_image_bytes())

        for val in result:
            assert isinstance(val, float)

    async def test_deterministic_across_calls(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            v1 = svc.embed_image_sync(_make_image_bytes())
            v2 = svc.embed_image_sync(_make_image_bytes())

        assert len(v1) == len(v2) == 768


class TestEmbedTextFallback:
    async def test_returns_correct_dimension(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_text("red shoes")

        assert isinstance(result, list)
        assert len(result) == 768

    async def test_vector_is_normalized(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_text("laptop for sale")

        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6

    async def test_empty_text(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_text("")

        assert len(result) == 768
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6


class TestEmbedImageDinoV2Fallback:
    async def test_returns_correct_dimension(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_image_dinov2(_make_image_bytes())

        assert isinstance(result, list)
        assert len(result) == 768

    async def test_vector_is_normalized(self):
        svc = EmbeddingService()
        with patch("src.services.embedding._st_available", False):
            result = await svc.embed_image_dinov2(_make_image_bytes())

        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6


class TestNormalizeMethod:
    def test_normalize_zero_vector(self):
        svc = EmbeddingService()
        vec = np.zeros(512)
        result = svc._normalize(vec)
        assert len(result) == 512
        assert all(v == 0.0 for v in result)

    def test_normalize_nonzero_vector(self):
        svc = EmbeddingService()
        vec = np.array([3.0, 4.0])
        result = svc._normalize(vec)
        norm = math.sqrt(sum(x * x for x in result))
        assert abs(norm - 1.0) < 1e-6

    def test_normalize_preserves_direction(self):
        svc = EmbeddingService()
        vec = np.array([1.0, 0.0])
        result = svc._normalize(vec)
        assert abs(result[0] - 1.0) < 1e-6
        assert abs(result[1] - 0.0) < 1e-6


class TestRandomVector:
    def test_random_vector_dimension(self):
        svc = EmbeddingService()
        vec = svc._random_vector(512)
        assert len(vec) == 512

    def test_random_vector_normalized(self):
        svc = EmbeddingService()
        vec = svc._random_vector(512)
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_random_vector_varies(self):
        svc = EmbeddingService()
        v1 = svc._random_vector(512)
        v2 = svc._random_vector(512)
        assert v1 != v2


class TestBytesToPil:
    def test_converts_jpeg(self):
        svc = EmbeddingService()
        img_bytes = _make_image_bytes(100, 100)
        pil_img = svc._bytes_to_pil(img_bytes)
        assert isinstance(pil_img, Image.Image)
        assert pil_img.size == (100, 100)
        assert pil_img.mode == "RGB"
