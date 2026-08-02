"""Product category -> broad family mappings shared across search, NLU and chat.

Broad "families" let us enforce category consistency: a car search must never
surface phones or shoes, even when raw embedding scores are close.
"""

PRODUCT_FAMILY = {
    "cars": "vehicles",
    "automotive": "vehicles",
    "vehicles": "vehicles",
    "motorcycles": "vehicles",
    "trucks": "vehicles",
    "phone": "electronics",
    "phones": "electronics",
    "electronics": "electronics",
    "laptops": "electronics",
    "computers": "electronics",
    "shoes": "shoes",
    "footwear": "shoes",
    "clothing": "clothing",
    "apparel": "clothing",
    "furniture": "furniture",
    "home": "furniture",
    "beauty": "beauty",
    "cosmetics": "beauty",
    "food": "food",
    "accessories": "accessories",
    "groceries": "groceries",
}

# YOLO (COCO) detector label -> broad family.
DETECTOR_LABEL_FAMILY = {
    "car": "vehicles",
    "truck": "vehicles",
    "bus": "vehicles",
    "motorcycle": "vehicles",
    "bicycle": "vehicles",
    "train": "vehicles",
    "boat": "vehicles",
    "airplane": "vehicles",
    "cell phone": "electronics",
    "laptop": "electronics",
    "tv": "electronics",
    "remote": "electronics",
    "keyboard": "electronics",
    "mouse": "electronics",
    "handbag": "accessories",
    "backpack": "accessories",
    "suitcase": "accessories",
    "umbrella": "accessories",
    "clock": "accessories",
    "book": "accessories",
    "bottle": "accessories",
    "cup": "accessories",
    "vase": "accessories",
}

# Keep only results scoring at least this fraction of the top score.
SCORE_BAND_RATIO = 0.35


def family_for_category(category: str | None) -> str | None:
    if not category:
        return None
    return PRODUCT_FAMILY.get(str(category).strip().lower())


def family_for_detector_labels(labels: list[str]) -> str | None:
    for label in labels or []:
        family = DETECTOR_LABEL_FAMILY.get((label or "").strip().lower())
        if family:
            return family
    return None
