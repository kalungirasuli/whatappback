import re

UGANDA_PREFIXES = {"256", "0"}
VALID_MIN_LENGTH = 10
VALID_MAX_LENGTH = 15


def validate_phone(phone: str) -> bool:
    cleaned = re.sub(r"[\s\+\-\(\)]", "", phone)
    if not cleaned.isdigit():
        return False
    if len(cleaned) < VALID_MIN_LENGTH or len(cleaned) > VALID_MAX_LENGTH:
        return False
    return True


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\+\-\(\)]", "", phone)
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if cleaned.startswith("0") and not cleaned.startswith("256"):
        cleaned = "256" + cleaned[1:]
    return cleaned
