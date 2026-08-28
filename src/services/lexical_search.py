import logging
import re

from sqlalchemy import text

from src.core.dependencies import async_session_factory
from src.services.reranker import RerankedResult

logger = logging.getLogger(__name__)

NAME_PHRASE_EXACT = 0.90
NAME_TOKEN_ILIKE = 0.70
NAME_TRIGRAM_HIGH = 0.65
NAME_TRIGRAM_LOW = 0.50
BRAND_TOKEN_ILIKE = 0.60
BRAND_TRIGRAM_HIGH = 0.55
BRAND_TRIGRAM_LOW = 0.40
ATTRIBUTE_TRIGRAM_LOW = 0.35

_TRIGRAM_HIGH = 0.55
_TRIGRAM_LOW = 0.30

_SELECT_COLS = (
    "p.id, p.name, p.brand, p.category, p.attributes, p.price, p.currency,"
    " m.business_name AS merchant_name"
)
_BASE_FROM = " FROM products p LEFT JOIN merchants m ON m.id = p.merchant_id"


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _tokens(value: str) -> list[str]:
    return re.findall(r"\w+", value.lower())


def _trigrams(word: str) -> set[str]:
    padded = f"  {word.strip().lower()} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    left = _trigrams(a)
    if not left:
        return 0.0
    right = _trigrams(b)
    if not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _row_to_result(row) -> RerankedResult:
    return RerankedResult(
        product_id=row.id,
        score=0.0,
        rank=0,
        match_label="",
        metadata={
            "product_name": row.name,
            "brand": row.brand or "",
            "category": row.category,
            "price": row.price,
            "currency": row.currency,
            "merchant_name": row.merchant_name or "",
            "product_id": row.id,
        },
    )


def _seed(scored: dict[int, RerankedResult], row, score: float) -> None:
    existing = scored.get(row.id)
    if existing is None or score > existing.score:
        result = _row_to_result(row)
        result.score = score
        scored[row.id] = result


async def _pg_trgm_available(session) -> bool:
    try:
        result = await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        )
        return result.scalar() is not None
    except Exception:
        logger.warning("pg_trgm availability check failed; treating as unavailable")
        return False


async def _phrase_exact(session, phrase: str, limit: int) -> list:
    result = await session.execute(
        text(f"SELECT {_SELECT_COLS}{_BASE_FROM} WHERE LOWER(p.name) = :phrase ORDER BY p.id LIMIT :limit"),
        {"phrase": phrase, "limit": limit},
    )
    return result.mappings().all()


async def _name_token_ilike(session, query: str, limit: int) -> list:
    rows: list = []
    seen: set[int] = set()
    for token in _tokens(query):
        result = await session.execute(
            text(
                f"SELECT {_SELECT_COLS}{_BASE_FROM} WHERE p.name ILIKE '%' || :token || '%'"
                " ORDER BY p.id LIMIT :limit"
            ),
            {"token": token, "limit": limit},
        )
        for row in result.mappings().all():
            if row.id not in seen:
                seen.add(row.id)
                rows.append(row)
    return rows


async def _name_trigram(session, query: str, limit: int) -> list:
    result = await session.execute(
        text(
            f"SELECT {_SELECT_COLS}, similarity(p.name, :q) AS sim{_BASE_FROM}"
            " WHERE p.name % :q"
            " ORDER BY sim DESC, p.id LIMIT :limit"
        ),
        {"q": query, "limit": limit},
    )
    return result.mappings().all()


async def _brand_token_ilike(session, query: str, limit: int) -> list:
    rows: list = []
    seen: set[int] = set()
    for token in _tokens(query):
        result = await session.execute(
            text(
                f"SELECT {_SELECT_COLS}{_BASE_FROM} WHERE p.brand ILIKE '%' || :token || '%'"
                " ORDER BY p.id LIMIT :limit"
            ),
            {"token": token, "limit": limit},
        )
        for row in result.mappings().all():
            if row.id not in seen:
                seen.add(row.id)
                rows.append(row)
    return rows


async def _brand_trigram(session, query: str, limit: int) -> list:
    result = await session.execute(
        text(
            f"SELECT {_SELECT_COLS}, similarity(p.brand, :q) AS sim{_BASE_FROM}"
            " WHERE p.brand % :q"
            " ORDER BY sim DESC, p.id LIMIT :limit"
        ),
        {"q": query, "limit": limit},
    )
    return result.mappings().all()


async def _attribute_rows(session, query: str, limit: int) -> list:
    clauses = []
    params: dict = {"limit": limit}
    for i, token in enumerate(_tokens(query)):
        clauses.append(f"p.attributes::text ILIKE '%' || :token{i} || '%'")
        params[f"token{i}"] = token
    if not clauses:
        return []
    where = " OR ".join(clauses)
    result = await session.execute(
        text(f"SELECT {_SELECT_COLS}{_BASE_FROM} WHERE {where} ORDER BY p.id LIMIT :limit"),
        params,
    )
    return result.mappings().all()


def _attribute_score(row, query: str) -> float:
    attributes = row.attributes or {}
    best = 0.0
    for key, value in attributes.items():
        text_value = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        sim = _trigram_similarity(f"{key} {text_value}", query)
        if sim > best:
            best = sim
    return best


async def lexical_fallback(query: str, limit: int = 5) -> list[RerankedResult]:
    """Name-first lexical fallback for text search.

    Tries, in order: exact name phrase, name token ILIKE, name trigram, brand
    token ILIKE, brand trigram, then attribute trigram — but only while nothing
    has matched yet. No status filtering: any visible product can be returned.
    """
    clean = _norm(query)
    if not clean:
        return []

    scored: dict[int, RerankedResult] = {}

    async with async_session_factory() as session:
        has_trgm = await _pg_trgm_available(session)

        try:
            for row in await _phrase_exact(session, clean, limit):
                _seed(scored, row, NAME_PHRASE_EXACT)

            if not scored:
                for row in await _name_token_ilike(session, clean, limit):
                    _seed(scored, row, NAME_TOKEN_ILIKE)

            if not scored and has_trgm:
                for row in await _name_trigram(session, clean, limit):
                    score = NAME_TRIGRAM_HIGH if row.sim >= _TRIGRAM_HIGH else NAME_TRIGRAM_LOW
                    _seed(scored, row, score)

            if not scored:
                for row in await _brand_token_ilike(session, clean, limit):
                    _seed(scored, row, BRAND_TOKEN_ILIKE)

            if not scored and has_trgm:
                for row in await _brand_trigram(session, clean, limit):
                    score = BRAND_TRIGRAM_HIGH if row.sim >= _TRIGRAM_HIGH else BRAND_TRIGRAM_LOW
                    _seed(scored, row, score)

            if not scored:
                for row in await _attribute_rows(session, clean, limit):
                    if _attribute_score(row, clean) >= _TRIGRAM_LOW:
                        _seed(scored, row, ATTRIBUTE_TRIGRAM_LOW)
        except Exception:
            logger.exception("Lexical fallback query failed")
            return []

    results = sorted(scored.values(), key=lambda r: (-r.score, r.product_id))
    for i, r in enumerate(results, start=1):
        r.rank = i
        r.match_label = "Exact match" if r.score >= 0.90 else "Related"
    return results[:limit]
