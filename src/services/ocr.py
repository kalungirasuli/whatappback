import io
import logging

import numpy as np
from PIL import Image

from src.core.config import settings

logger = logging.getLogger(__name__)

try:
    from rapidocr_onnxruntime import RapidOCR

    _ocr_available = True
except ImportError:
    _ocr_available = False
    logger.warning("rapidocr-onnxruntime not installed — OCR disabled")


class OcrService:
    def __init__(self) -> None:
        self._engine = None

    def _get_engine(self):
        if self._engine is None and _ocr_available:
            self._engine = RapidOCR()
        return self._engine

    def extract_sync(self, image_bytes: bytes) -> str:
        engine = self._get_engine()
        if engine is None:
            return ""
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            arr = np.array(img)
            result, _ = engine(arr)
            if not result:
                return ""
            texts = [line[1] for line in result if line[1]]
            return " ".join(texts).strip()
        except Exception as e:
            logger.debug(f"OCR extraction failed: {e}")
            return ""
