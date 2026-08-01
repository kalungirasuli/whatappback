import io
from unittest.mock import patch

import pytest
from PIL import Image

from src.services.detector import ObjectDetector, CroppedObject, _yolo_available


def _make_image_bytes(width: int = 200, height: int = 200, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestDetectAndCropValidImage:
    async def test_returns_crop_list(self):
        detector = ObjectDetector()
        image_bytes = _make_image_bytes(300, 300)
        result = await detector.detect_and_crop(image_bytes)

        assert isinstance(result, list)
        assert len(result) >= 1

    async def test_cropped_object_fields(self):
        detector = ObjectDetector()
        image_bytes = _make_image_bytes(400, 300)
        result = await detector.detect_and_crop(image_bytes)

        crop = result[0]
        assert isinstance(crop, CroppedObject)
        assert isinstance(crop.image_bytes, bytes)
        assert len(crop.image_bytes) > 0
        assert isinstance(crop.bbox, tuple)
        assert len(crop.bbox) == 4
        assert isinstance(crop.confidence, float)
        assert isinstance(crop.label, str)

    async def test_cropped_image_is_valid_jpeg(self):
        detector = ObjectDetector()
        image_bytes = _make_image_bytes(200, 200)
        result = await detector.detect_and_crop(image_bytes)

        cropped = Image.open(io.BytesIO(result[0].image_bytes))
        assert cropped.format == "JPEG"
        assert cropped.mode == "RGB"

    async def test_center_crop_dimensions_ratio(self):
        detector = ObjectDetector()
        width, height = 500, 400
        image_bytes = _make_image_bytes(width, height)
        result = await detector.detect_and_crop(image_bytes)

        crop = result[0]
        x1, y1, x2, y2 = crop.bbox
        crop_w = x2 - x1
        crop_h = y2 - y1
        expected_w = int(width * 0.8)
        expected_h = int(height * 0.8)
        assert crop_w == expected_w
        assert crop_h == expected_h

    async def test_center_crop_symmetric(self):
        detector = ObjectDetector()
        width, height = 600, 600
        image_bytes = _make_image_bytes(width, height)
        result = await detector.detect_and_crop(image_bytes)

        crop = result[0]
        x1, y1, x2, y2 = crop.bbox
        margin_x = x1
        margin_y = y1
        assert margin_x == (width - x2)
        assert margin_y == (height - y2)

    async def test_center_crop_label_and_confidence(self):
        detector = ObjectDetector()
        image_bytes = _make_image_bytes()
        result = await detector.detect_and_crop(image_bytes)

        crop = result[0]
        assert crop.label == "full_image"
        assert crop.confidence == 1.0


class TestDetectAndCropFallback:
    async def test_yolo_unavailable_uses_center_crop(self):
        detector = ObjectDetector()
        with patch("src.services.detector._yolo_available", False):
            result = await detector.detect_and_crop(_make_image_bytes())

        assert len(result) == 1
        assert result[0].label == "full_image"

    async def test_yolo_model_returns_no_objects(self):
        detector = ObjectDetector()
        with (
            patch("src.services.detector._yolo_available", True),
            patch.object(detector, "_get_model", return_value=None),
        ):
            result = await detector.detect_and_crop(_make_image_bytes())

        assert len(result) == 1
        assert result[0].label == "full_image"


class TestDetectAndCropCorrupted:
    async def test_corrupted_jpeg_data(self):
        detector = ObjectDetector()
        corrupted = b"\xff\xd8\xff\xe0corrupted_image_data_not_valid"

        with pytest.raises(Exception):
            await detector.detect_and_crop(corrupted)

    async def test_garbage_bytes(self):
        detector = ObjectDetector()
        garbage = b"this is not image data at all"

        with pytest.raises(Exception):
            await detector.detect_and_crop(garbage)


class TestDetectAndCropSync:
    def test_sync_returns_list(self):
        detector = ObjectDetector()
        result = detector.detect_and_crop_sync(_make_image_bytes())

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_sync_crop_is_cropped_object(self):
        detector = ObjectDetector()
        result = detector.detect_and_crop_sync(_make_image_bytes(300, 250))

        assert isinstance(result[0], CroppedObject)
        assert len(result[0].image_bytes) > 0


class TestDetectAndCropPNG:
    async def test_png_input_works(self):
        detector = ObjectDetector()
        png_bytes = _make_png_bytes(200, 200)
        result = await detector.detect_and_crop(png_bytes)

        assert len(result) >= 1
        img = Image.open(io.BytesIO(result[0].image_bytes))
        assert img.format == "JPEG"


class TestConfidenceThreshold:
    def test_custom_threshold(self):
        detector = ObjectDetector(confidence_threshold=0.9)
        assert detector._confidence == 0.9

    def test_default_threshold(self):
        detector = ObjectDetector()
        assert detector._confidence == 0.5
