import asyncio
import io
import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO

    _yolo_available = True
except ImportError:
    _yolo_available = False
    logger.warning("ultralytics not installed — using Pillow center-crop fallback")


@dataclass
class CroppedObject:
    image_bytes: bytes
    bbox: tuple[int, int, int, int]
    confidence: float
    label: str


class ObjectDetector:
    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self._confidence = confidence_threshold
        self._model = None

    def _get_model(self):
        if self._model is None and _yolo_available:
            self._model = YOLO("yolo11n.pt")
        return self._model

    def _yolo_detect(self, image_bytes: bytes) -> list[CroppedObject]:
        model = self._get_model()
        if model is None:
            return []

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        results = model(img, verbose=False)

        crops: list[CroppedObject] = []
        if not results:
            return crops

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                conf = float(box.conf[0])
                if conf < self._confidence:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                # Clamp to image bounds
                w, h = img.size
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w, x2)
                y2 = min(h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                cropped = img.crop((x1, y1, x2, y2))
                buf = io.BytesIO()
                cropped.save(buf, format="JPEG", quality=90)
                label = result.names.get(int(box.cls[0]), "object") if result.names else "object"

                crops.append(CroppedObject(
                    image_bytes=buf.getvalue(),
                    bbox=(x1, y1, x2, y2),
                    confidence=conf,
                    label=label,
                ))
        return crops

    def _center_crop(self, image_bytes: bytes) -> list[CroppedObject]:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size

        # Crop center 80% of image
        crop_ratio = 0.8
        cw = int(w * crop_ratio)
        ch = int(h * crop_ratio)
        left = (w - cw) // 2
        top = (h - ch) // 2
        right = left + cw
        bottom = top + ch

        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)

        return [CroppedObject(
            image_bytes=buf.getvalue(),
            bbox=(left, top, right, bottom),
            confidence=1.0,
            label="full_image",
        )]

    def detect_and_crop_sync(self, image_bytes: bytes) -> list[CroppedObject]:
        if _yolo_available:
            try:
                crops = self._yolo_detect(image_bytes)
                if crops:
                    logger.info("YOLO detected %d objects: %s", len(crops), ", ".join(f"{c.label} {c.confidence:.0%}" for c in crops))
                    return crops
                logger.info("YOLO detected no objects, falling back to center crop")
            except Exception as e:
                logger.warning(f"YOLO detection failed, using center crop: {e}")

        return self._center_crop(image_bytes)

    async def detect_and_crop(self, image_bytes: bytes) -> list[CroppedObject]:
        return await asyncio.get_event_loop().run_in_executor(
            None, self.detect_and_crop_sync, image_bytes
        )
