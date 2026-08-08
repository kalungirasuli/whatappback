import asyncio
import re
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.config import settings
from src.services.llm_nlu import LLMNLUService, SearchIntent
from src.services.whatsapp import send_text, download_media
from src.workers.search_pipeline import SearchPipeline

logger = logging.getLogger(__name__)


@dataclass
class NLUResult:
    intent: str = "unknown"
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    is_multi_intent: bool = False
    search_intents: list[SearchIntent] = field(default_factory=list)


_SEARCH_KEYWORDS = re.compile(
    r"\b(looking for|search|find|do you have|where can i get|need|want|sell me|any .+ available)\b",
    re.IGNORECASE,
)

_INTEREST_KEYWORDS = re.compile(
    r"\b(interested|want to buy|how much|price|cost|what is the price|tell me the price|buy)\b",
    re.IGNORECASE,
)

_HELP_KEYWORDS = re.compile(
    r"\b(help|how to|what can i do|how do i|instructions|guide)\b",
    re.IGNORECASE,
)

_GREETING_KEYWORDS = re.compile(
    r"\b(hello|hi|hey|morning|afternoon|evening|good day|yo|sup|how are you)\b",
    re.IGNORECASE,
)

_PRICE_REGEX = re.compile(
    r"(?<!\w)(\d[\d,]*(?:\.\d+)?)\s*(k|m|b|ugx|shs|shillings?|ug\s*shs?)?\b",
    re.IGNORECASE,
)

_COLOR_KEYWORDS = {
    "red", "blue", "green", "black", "white", "yellow", "orange", "pink",
    "purple", "brown", "grey", "gray", "silver", "gold", "navy", "teal",
    "beige", "maroon", "olive", "cyan", "magenta", "ivory", "tan", "coral",
    "salmon", "lavender", "indigo", "turquoise", "crimson", "charcoal",
}

_GENDER_RE = re.compile(r"\b(men(?:'s)?|women(?:'s)?|male|female|unisex|boys?|girls?)\b", re.IGNORECASE)
_SIZE_RE = re.compile(r"\bsize\s*[:#-]?\s*([a-z0-9][a-z0-9./+-]*)\b", re.IGNORECASE)
_BRAND_RE = re.compile(r"\b(?:brand|by|from)\s+([a-z0-9][a-z0-9&' -]{1,40})", re.IGNORECASE)
_MODEL_RE = re.compile(r"\bmodel\s+([a-z0-9][a-z0-9&' -]{1,40})", re.IGNORECASE)
_MATERIAL_RE = re.compile(r"\b(?:made of|material(?: is)?|fabric)\s+([a-z][a-z -]{1,30})", re.IGNORECASE)
_STYLE_RE = re.compile(r"\b(?:style|type|kind)\s+([a-z][a-z -]{1,30})", re.IGNORECASE)

_CATEGORY_KEYWORDS = {
    "electronics": ["phone", "laptop", "tablet", "headphone", "speaker", "charger", "cable", "camera", "tv", "monitor", "keyboard", "mouse", "earbuds", "powerbank"],
    "clothing": ["shirt", "dress", "pants", "jeans", "skirt", "jacket", "coat", "sweater", "hoodie", "tshirt", "t-shirt", "shorts", "suit", "blouse", "trousers", "sari", "kanzu"],
    "shoes": ["shoes", "sneakers", "boots", "sandals", "slippers", "heels", "loafers", "flats", " trainers"],
    "furniture": ["chair", "table", "sofa", "bed", "desk", "wardrobe", "shelf", "cabinet", "stool", "dresser"],
    "beauty": ["makeup", "lipstick", "cream", "lotion", "perfume", "shampoo", "soap", "skincare", "cosmetics"],
    "food": ["rice", "beans", "maize", "coffee", "tea", "sugar", "salt", "flour", "spices", "snack"],
    "accessories": ["watch", "ring", "necklace", "bracelet", "earrings", "bag", "wallet", "belt", "hat", "scarf", "sunglasses"],
    "groceries": ["grocery", "vegetable", "fruit", "meat", "fish", "chicken", "bread", "milk", "egg"],
}

# Families for cross-checking what an image shows vs. what the caption asks for.
FAMILY_ALIASES = {
    "vehicles": ["car", "truck", "suv", "van", "vehicle", "sedan", "motorbike", "bicycle", "jeep", "bus", "pickup",
                 "bmw", "toyota", "mercedes", "audi", "honda", "ford", "nissan", "volkswagen", "hyundai", "lexus",
                 "porsche", "subaru", "mazda", "kia", "chevrolet", "dodge", "ferrari", "lamborghini", "volvo", "bentley"],
    "electronics": ["iphone", "samsung", "nokia", "huawei", "tecno", "infinix", "itel", "oppo", "vivo", "xiaomi",
                    "redmi", "ipad", "kindle", "airpods"],
    "shoes": ["nike", "adidas", "puma", "reebok", "new balance", "converse", "vans", "sketchers", "crocs",
              "timberland", "asics", "fila", "heel", "loafer"],
    "clothing": ["kanzu", "gomesi", "shirt", "trouser", "jean", "dress", "skirt"],
    "accessories": ["watch", "sunglasses", "necklace", "bracelet", "ring", "belt", "bag"],
}


def detect_product_category(text: str) -> tuple[str | None, str | None]:
    """Return (matched_topic_keyword, category_family) for the strongest product mention in text.

    E.g. "I want shoes" -> ("shoes", "shoes"); "I need a phone" -> ("phone", "electronics");
    "I want a BMW" -> ("bmw", "vehicles"); "hello there" -> (None, None).
    """
    if not text:
        return (None, None)
    text_lower = text.lower()
    best = None
    for family, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw.strip())}\b", text_lower):
                if best is None or len(kw) > len(best[0]):
                    best = (kw.strip(), family)
    for family, keywords in FAMILY_ALIASES.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                if best is None or len(kw) > len(best[0]):
                    best = (kw, family)
    return (best[0], best[1]) if best else (None, None)


class RegexNLURouter:
    """Fallback regex-based NLU when Ollama is unavailable."""

    def _classify_intent(self, text: str, has_image: bool) -> list[SearchIntent]:
        intents: list[SearchIntent] = []
        found_greeting = bool(_GREETING_KEYWORDS.search(text)) if text else False
        found_help = bool(_HELP_KEYWORDS.search(text)) if text else False
        found_search = bool(_SEARCH_KEYWORDS.search(text)) if text else False
        found_interest = bool(_INTEREST_KEYWORDS.search(text)) if text else False

        if found_help:
            intents.append(SearchIntent(type="help", description="User needs help"))
            return intents

        if found_greeting and not found_search:
            intents.append(SearchIntent(type="greeting", description="User greeted"))
            return intents

        if has_image:
            intents.append(SearchIntent(
                type="visual_search",
                description="User uploaded an image to search",
                entities=self._extract_entities(text or ""),
            ))

        if text and (found_search or found_interest):
            intents.append(SearchIntent(
                type="product_search",
                entities=self._extract_entities(text),
            ))

        if not intents:
            if has_image:
                intents.append(SearchIntent(type="visual_search"))
            elif text:
                intents.append(SearchIntent(
                    type="product_search",
                    entities=self._extract_entities(text),
                ))
            else:
                intents.append(SearchIntent(type="unknown"))

        return intents

    def _extract_entities(self, text: str) -> dict[str, Any]:
        entities: dict[str, Any] = {}
        if not text:
            return entities

        words = text.split()
        prices: list[float] = []
        price_bounds: list[tuple[float, str]] = []
        for match in _PRICE_REGEX.finditer(text):
            raw = match.group(1)
            unit = (match.group(2) or "").lower().replace(" ", "")
            try:
                value = float(raw.replace(",", ""))
                if unit == "k":
                    value *= 1_000
                elif unit == "m":
                    value *= 1_000_000
                elif unit == "b":
                    value *= 1_000_000_000
                elif unit in {"ugx", "shs", "shilling", "shillings", "ugshs"}:
                    pass
                else:
                    before = text[max(0, match.start() - 18):match.start()].lower()
                    if (
                        float(raw.replace(",", "")) < 1000
                        and not re.search(r"\b(under|below|above|over|price|cost|budget|up to|maximum|minimum)\b", before)
                    ):
                        continue
                before = text[max(0, match.start() - 24):match.start()].lower()
                bound = "max" if re.search(r"\b(under|below|up to|maximum)\b", before) else "min" if re.search(r"\b(above|over|minimum)\b", before) else "exact"
                prices.append(value)
                price_bounds.append((value, bound))
            except ValueError:
                pass
        if prices:
            if len(prices) == 1 and price_bounds[0][1] == "max":
                entities["price_max"] = prices[0]
            elif len(prices) == 1 and price_bounds[0][1] == "min":
                entities["price_min"] = prices[0]
            elif len(prices) == 1:
                entities["price_min"] = prices[0]
                entities["price_max"] = prices[0]
            else:
                entities["price_min"] = min(prices)
                entities["price_max"] = max(prices)

        text_lower = text.lower()
        found_colors = [c for c in _COLOR_KEYWORDS if re.search(rf"\b{re.escape(c)}\b", text_lower)]
        if found_colors:
            entities["color"] = found_colors[0] if len(found_colors) == 1 else found_colors

        attributes: dict[str, Any] = {}
        if found_colors:
            attributes["color"] = entities["color"]
        gender = _GENDER_RE.search(text)
        if gender:
            attributes["gender"] = gender.group(1).lower().replace("'s", "")
            entities["gender"] = attributes["gender"]
        size = _SIZE_RE.search(text)
        if size:
            attributes["size"] = size.group(1)
            entities["size"] = size.group(1)
        for key, pattern in (("brand", _BRAND_RE), ("model", _MODEL_RE), ("material", _MATERIAL_RE), ("style", _STYLE_RE)):
            match = pattern.search(text)
            if match:
                value = match.group(1).strip(" ,.!?")
                attributes[key] = value
                entities[key] = value

        found_categories = []
        for category, keywords in _CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    found_categories.append(category)
                    break
        if found_categories:
            entities["category"] = found_categories[0] if len(found_categories) == 1 else found_categories

        stop_words = {
            "i", "am", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "shall", "can", "need",
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "it", "its", "this", "that",
            "looking", "find", "search", "want", "sell", "buy", "get",
            "how", "much", "what", "where", "do", "you", "have", "any",
            "please", "tell", "me", "about", "show", "give", "some",
            "very", "really", "nice", "good", "great", "best",
        }
        name_words = []
        for w in words:
            clean = re.sub(r"[^\w]", "", w).lower()
            if (
                clean
                and clean not in stop_words
                and not clean.isdigit()
                and clean not in _COLOR_KEYWORDS
                and clean not in {c for kws in _CATEGORY_KEYWORDS.values() for c in kws}
            ):
                name_words.append(w)
        if name_words:
            entities["product_name"] = " ".join(name_words)

        loc_match = re.search(r"\b(?:in|at|near|around)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", text)
        if loc_match:
            entities["location"] = loc_match.group(1)

        if attributes:
            entities["attributes"] = attributes
        if "price_min" in entities or "price_max" in entities:
            entities["constraints"] = {
                key: entities[key]
                for key in ("price_min", "price_max")
                if key in entities
            }

        return entities

    async def extract(
        self, message_text: str, has_image: bool = False, history: list[dict] | None = None
    ) -> NLUResult:
        intents = self._classify_intent(message_text, has_image)
        primary = intents[0] if intents else SearchIntent(type="unknown")
        is_multi = len(intents) > 1
        if history and primary.entities:
            primary.entities = self._merge_history_entities(primary.entities, history)
        return NLUResult(
            intent=primary.type,
            entities=primary.entities,
            confidence=0.5,
            is_multi_intent=is_multi,
            search_intents=intents,
        )

    # Sticky entities that may be carried across turns from earlier user messages.
    _STICKY_ENTITY_KEYS = (
        "color", "category", "brand", "model", "size", "gender",
        "material", "style", "price_min", "price_max", "location",
    )

    def _merge_history_entities(self, entities: dict, history: list[dict]) -> dict:
        """Carry forward entities from earlier user turns the current message lacks.

        E.g. "red shoes" → "under 100k" keeps {color: red, category: shoes} and
        adds the new price bound. The most recent user message wins for a key.
        """
        merged = dict(entities)

        for msg in reversed(history):
            if msg.get("role") not in ("user", "buyer"):
                continue
            content = str(msg.get("content") or "")
            if not content.strip():
                continue
            prior = self._extract_entities(content)
            for raw_key in self._STICKY_ENTITY_KEYS:
                value = prior.get(raw_key)
                if value is not None and merged.get(raw_key) is None:
                    merged[raw_key] = value

        attributes = merged.get("attributes") or {}
        for key in ("color", "gender", "size", "brand", "model", "material", "style"):
            if merged.get(key) is not None:
                attributes[key] = merged[key]
        if attributes:
            merged["attributes"] = attributes

        constraints = merged.get("constraints") or {}
        for key in ("price_min", "price_max"):
            if merged.get(key) is not None:
                constraints[key] = merged[key]
        if constraints:
            merged["constraints"] = constraints
        return merged

    def build_product_search_intent(self, text: str) -> SearchIntent | None:
        """Build a product_search intent from raw text, or None if the text isn't a product request.

        Used to recover a caption's product request that the LLM NLU may have dropped
        when an image is also present (so the customer's request is never lost).
        """
        if not text or not text.strip():
            return None
        entities = self._extract_entities(text)
        has_search = bool(_SEARCH_KEYWORDS.search(text))
        has_interest = bool(_INTEREST_KEYWORDS.search(text))
        has_product_words = bool(entities.get("category") or entities.get("product_name"))
        if has_search or has_interest or has_product_words:
            return SearchIntent(
                type="product_search",
                description=text.strip(),
                entities=entities,
            )
        return None


_llm_nlu = LLMNLUService()
_regex_nlu = RegexNLURouter()


async def extract_nlu(
    message_text: str,
    has_image: bool = False,
    history: list[dict] | None = None,
    context: dict | None = None,
) -> NLUResult:
    llm_result = await _llm_nlu.extract(
        message_text, has_image=has_image, history=history, context=context
    )

    if llm_result.intents:
        primary = llm_result.intents[0]
        is_multi = len(llm_result.intents) > 1
        return NLUResult(
            intent=primary.type,
            entities=primary.entities,
            confidence=0.85,
            is_multi_intent=is_multi,
            search_intents=llm_result.intents,
        )

    logger.info("LLM NLU unavailable, falling back to regex NLU")
    if not settings.nlu_fallback_to_regex:
        logger.info("Regex NLU fallback disabled by config; returning unknown")
        return NLUResult(intent="unknown")
    return await _regex_nlu.extract(message_text, has_image=has_image, history=history)


def _price_range_from_entities(entities: dict) -> tuple[float, float] | None:
    constraints = entities.get("constraints") or {}
    price_min = entities.get("price_min", constraints.get("price_min"))
    price_max = entities.get("price_max", constraints.get("price_max"))
    if price_min is not None and price_max is not None:
        return (float(price_min), float(price_max))
    if price_max is not None:
        return (0.0, float(price_max))
    return None


def _build_search_text(entities: dict, original_text: str) -> str:
    parts: list[str] = []
    for key in ("product_name", "item_type", "category", "brand", "model", "variant", "gender", "size", "color", "material", "style", "condition", "occasion"):
        value = entities.get(key)
        if value:
            parts.extend(value if isinstance(value, list) else [str(value)])
    for key, value in (entities.get("attributes") or {}).items():
        if value:
            parts.extend([str(key), *(value if isinstance(value, list) else [str(value)])])
    for key, value in (entities.get("specifications") or {}).items():
        parts.extend([str(key), str(value)])
    if parts:
        return " ".join(dict.fromkeys(p for p in parts if p)).strip()
    if entities.get("normalized_query"):
        return str(entities["normalized_query"]).strip()
    return original_text.strip()


async def execute_intent_searches(
    intents: list[SearchIntent],
    image_bytes: bytes | None = None,
    images_bytes: list[bytes] | None = None,
    buyer_location: tuple[float, float] | None = None,
) -> list[tuple[str, list]]:
    pipeline = SearchPipeline()
    results: list[tuple[str, list]] = []
    img_list = images_bytes if images_bytes else ([image_bytes] if image_bytes else [])
    img_idx = 0

    for intent in intents:
        if intent.type == "visual_search":
            current = img_list[img_idx] if img_idx < len(img_list) else None
            img_idx += 1
            if current:
                search_results = await pipeline.search_by_image(
                    image_bytes=current,
                    query_text=_build_search_text(intent.entities, "") if intent.entities else None,
                    query_entities=intent.entities,
                    buyer_location=buyer_location,
                    price_range=_price_range_from_entities(intent.entities),
                )
                desc = intent.description or "Products matching your image"
                results.append((desc, _within_min_score(search_results)))

        elif intent.type == "product_search":
            search_text = _build_search_text(intent.entities, intent.description)
            search_results = await pipeline.search_by_text(
                text=search_text,
                query_entities=intent.entities,
                buyer_location=buyer_location,
                price_range=_price_range_from_entities(intent.entities),
            )
            desc = intent.description or search_text
            results.append((desc, _within_min_score(search_results)))

    return results


async def compose_multi_intent_reply(
    search_results: list[tuple[str, list]],
) -> str:
    query = search_results[0][0] if search_results else None
    non_empty = [(desc, results) for desc, results in search_results if results]
    if not non_empty:
        return await compose_no_match_reply(query)

    sections: list[str] = []
    for desc, results in non_empty:
        reply = await SearchPipeline().format_reply(
            results, max_results=3, section_title=desc,
        )
        if reply:
            sections.append(reply)

    return "\n\n---\n\n".join(sections) if sections else await compose_no_match_reply(query)


MIN_MATCH_SCORE = 0.3
NO_MATCH_FALLBACK = "Sorry, I couldn't find matching products. Try different words, more detail, or send a photo!"
NO_MATCH_LLM_PROMPT = (
    "You are the customer-facing assistant of a WhatsApp marketplace called whatAppseller.\n"
    "A product search just returned NO matching items for the customer. Reply with a single,\n"
    "short, warm and human message (max 2 sentences) that acknowledges their request and\n"
    "suggests a small next step: different words, more detail, or sending a photo.\n"
    "Do not mention scores or the search system. Reply only with the message.\n"
)


def _within_min_score(results: list) -> list:
    """Absolute relevance floor: results scoring below MIN_MATCH_SCORE are
    treated as no match so the assistant says 'not found' instead of noise."""
    return [
        r for r in results
        if getattr(r, "score", None) is None or r.score >= MIN_MATCH_SCORE
    ]


async def compose_no_match_reply(query: str | None = None) -> str:
    """Human 'no match found' text generated by the LLM, with a warm fallback."""
    from src.llm_agent.agent import _call_llm

    user_content = (
        f"The customer was looking for: {query}" if query else
        "The customer was looking for something, but nothing matched."
    )
    reply = await _call_llm(
        NO_MATCH_LLM_PROMPT,
        [{"role": "user", "content": user_content}],
    )
    text = (reply or "").strip()
    return text[:300] if text else NO_MATCH_FALLBACK


async def process_batch(batch_payload: dict) -> str:
    """Process a batch of images + combined text and return a single reply."""
    images = batch_payload.get("images", [])
    combined_text = batch_payload.get("text", "")

    # Download all images in parallel
    download_tasks = [
        download_media(img["id"])
        for img in images
        if isinstance(img, dict) and img.get("id")
    ]
    raw = await asyncio.gather(*download_tasks, return_exceptions=True)
    image_bytes_list: list[bytes] = [b for b in raw if isinstance(b, bytes) and b]

    # Run NLU on combined text (no image — images are handled separately)
    nlu_result = await extract_nlu(combined_text, has_image=bool(images))

    # Greeting / help with no images → standalone response
    has_greeting = any(si.type == "greeting" for si in nlu_result.search_intents)
    has_help = any(si.type == "help" for si in nlu_result.search_intents)

    if has_help:
        return (
            "Here's what I can do:\n\n"
            "1. Send a photo of a product you want — I'll find similar items\n"
            "2. Type what you're looking for — e.g. 'Looking for red shoes under 100000'\n"
            "3. I'll show matching products from nearby sellers\n\n"
            "You can filter by:\n"
            "- Color: 'blue shirt'\n"
            "- Price: 'phone under 500000'\n"
            "- Category: 'electronics', 'clothing', 'shoes', etc."
        )

    if has_greeting and not images:
        return (
            "Hello! Welcome to whatAppseller.\n\n"
            "Send a photo or describe what you're looking for, "
            "and I'll find matching products from local sellers!"
        )

    # Build intents: one visual_search per image
    intents: list[SearchIntent] = []
    for i, img_data in enumerate(images):
        caption = (img_data.get("caption") or "").strip() if isinstance(img_data, dict) else ""
        description = caption or f"Image {i + 1}"
        intents.append(SearchIntent(type="visual_search", description=description))

    # Add text-only intents from NLU (product_search, general_question, chat)
    for si in nlu_result.search_intents:
        if si.type in ("product_search", "general_question", "chat", "unknown"):
            intents.append(si)

    # Filter down to only searchable intents
    search_intents = [si for si in intents if si.type in ("visual_search", "product_search")]

    if not search_intents:
        return await compose_no_match_reply(combined_text or None)

    results = await execute_intent_searches(search_intents, images_bytes=image_bytes_list)
    return await compose_multi_intent_reply(results)
