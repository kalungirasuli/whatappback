import asyncio
import io
import logging
import math
import os
import random

import numpy as np
from PIL import Image

from src.core.config import settings

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer

    _st_available = True
except ImportError:
    _st_available = False
    logger.warning("sentence-transformers not installed — using random embeddings for testing")


class EmbeddingService:
    def __init__(self) -> None:
        self._siglip_model = None
        self._dinov2_model = None
        self._text_model = None
        self._siglip_model_name = os.getenv("SIGLIP_MODEL", settings.siglip_model)
        self._dinov2_model_name = os.getenv("DINOV2_MODEL", settings.dinov2_model)
        self._text_model_name = os.getenv("TEXT_EMBEDDING_MODEL", settings.text_embedding_model)
        self._siglip_dim = settings.siglip_dim
        self._dinov2_dim = settings.dinov2_dim
        self._text_dim = settings.text_embedding_dim

    def _get_siglip(self) -> "SentenceTransformer | None":
        if self._siglip_model is None and _st_available:
            try:
                self._siglip_model = SentenceTransformer(self._siglip_model_name)
                logger.info(f"Loaded SigLIP model: {self._siglip_model_name}")
            except Exception as e:
                logger.error(f"Failed to load SigLIP model: {e}")
                return None
        return self._siglip_model

    def _get_dinov2(self) -> "SentenceTransformer | None":
        if self._dinov2_model is None and _st_available:
            try:
                self._dinov2_model = SentenceTransformer(self._dinov2_model_name)
                logger.info(f"Loaded DINOv2 model: {self._dinov2_model_name}")
            except Exception as e:
                logger.error(f"Failed to load DINOv2 model: {e}")
                return None
        return self._dinov2_model

    def _get_text_model(self) -> "SentenceTransformer | None":
        if self._text_model is None and _st_available:
            try:
                self._text_model = SentenceTransformer(self._text_model_name)
                logger.info(f"Loaded text embedding model: {self._text_model_name}")
            except Exception as e:
                logger.error(f"Failed to load text embedding model: {e}")
                return None
        return self._text_model

    def _random_vector(self, dim: int) -> list[float]:
        vec = [random.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def _normalize(self, vec: np.ndarray) -> list[float]:
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def _bytes_to_pil(self, image_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def embed_image_sync(self, image_bytes: bytes) -> list[float]:
        model = self._get_siglip()
        if model is None:
            return self._random_vector(self._siglip_dim)

        img = self._bytes_to_pil(image_bytes)
        embedding = model.encode(img, normalize_embeddings=True)
        return self._normalize(embedding)

    async def embed_image(self, image_bytes: bytes) -> list[float]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self.embed_image_sync, image_bytes
        )

    def embed_text_sync(self, text: str) -> list[float]:
        model = self._get_text_model()
        if model is None:
            return self._random_vector(self._text_dim)

        embedding = model.encode(text, normalize_embeddings=True)
        return self._normalize(embedding)

    async def embed_text(self, text: str) -> list[float]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self.embed_text_sync, text
        )

    def embed_image_dinov2_sync(self, image_bytes: bytes) -> list[float]:
        model = self._get_dinov2()
        if model is None:
            return self._random_vector(self._dinov2_dim)

        img = self._bytes_to_pil(image_bytes)
        embedding = model.encode(img, normalize_embeddings=True)
        return self._normalize(embedding)

    async def embed_image_dinov2(self, image_bytes: bytes) -> list[float]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self.embed_image_dinov2_sync, image_bytes
        )
