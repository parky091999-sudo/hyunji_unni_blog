"""
Pexels API로 키워드 관련 이미지 URL 수집
image_keywords (content.py에서 생성된 7개 키워드) 사용 시 각 위치별 적합한 이미지 수집
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"

# 카테고리/키워드 → 영문 검색어 매핑
_KO_TO_EN: list[tuple[re.Pattern, str]] = [
    (re.compile(r"욕실|화장실|샤워"), "clean bathroom interior aesthetic no people"),
    (re.compile(r"주방|부엌|싱크대"), "cozy kitchen counter still life aesthetic no people"),
    (re.compile(r"세탁기|빨래"), "laundry room aesthetic details no people"),
    (re.compile(r"청소|정리|루틴"), "home interior organization aesthetic minimalist no people"),
    (re.compile(r"곰팡이|습기"), "bathroom tiles clean detail still life"),
    (re.compile(r"요리|레시피|밥|식단|냉파"), "korean food table setting cozy aesthetic no people"),
    (re.compile(r"도시락|아침\s*메뉴"), "bento box lunch box still life cozy"),
    (re.compile(r"식비\s*절약"), "cozy study desk notebook coffee still life"),
    (re.compile(r"인테리어|꾸미|홈\s*데코"), "cozy home interior aesthetic minimalist no people"),
    (re.compile(r"수납|정리함|선반"), "organized storage shelves aesthetic details no people"),
    (re.compile(r"옷장|드레스룸"), "organized closet wardrobe aesthetic minimalist no people"),
    (re.compile(r"냉장고"), "organized refrigerator shelves inside close up no people"),
    (re.compile(r"베란다|발코니"), "balcony terrace cozy plants aesthetic no people"),
    (re.compile(r"무드등|조명"), "cozy bedroom mood lighting aesthetic no people"),
    (re.compile(r"절약|생활비|가계부"), "cozy study desk piggy bank still life"),
    (re.compile(r"전기세|난방비|냉방비"), "cozy home warm lighting detail"),
    (re.compile(r"에어컨"), "air conditioner clean minimalist white no people"),
    (re.compile(r"다이소"), "cozy home organizer aesthetic design no people"),
    (re.compile(r"이케아"), "ikea home organization shelves aesthetic no people"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner minimalist home no people"),
    (re.compile(r"공기청정기"), "home air purifier close up minimalist no people"),
    (re.compile(r"필터|교체"), "clean home appliance minimalist details"),
    (re.compile(r"신혼|살림"), "cozy new home living room aesthetic no people"),
    (re.compile(r"자취|1인\s*가구"), "cozy small apartment interior aesthetic no people"),
    (re.compile(r"혼수|결혼\s*준비"), "cozy bridal room decoration aesthetic details"),
]
_DEFAULT_QUERY = "cozy Korean home interior aesthetic no people"

# 살림/생활 블로그에 '뜬금없는' 스톡사진 제외용 (alt 텍스트 기준)
# 달러사진, 인물, 자동차, 방독면, 스마트폰, 보석 등 뜬금없는 사물 차단
_OFFTOPIC_RE = re.compile(
    r"\b(money|dollar|cash|currency|coin|finance|financial|banking|invest|investment|"
    r"stock\s*market|business|office|meeting|conference|corporate|suit|handshake|"
    r"graph|chart|mountain|beach|forest|ocean|sunset|sky|desert|wildlife|animal|"
    r"abstract|texture|pattern|gradient|wedding\s*dress|model\s*pose|"
    r"person|people|man|woman|model|face|hand|finger|arm|leg|body|portrait|couple|family|"
    r"human|girl|boy|guy|lady|male|female|"
    # 유저 피드백 반영: 차량용 필터, 방독면, 스마트폰, 반지/액세서리 등 원천 배제
    r"car|auto|vehicle|automotive|engine|gas\s*mask|respirator|mask|phone|smartphone|mobile|ring|jewelry|necklace|bracelet|earring)\b",
    re.I,
)


def _keyword_to_en(keyword: str) -> str:
    """한국어 키워드를 Pexels 검색용 영어 쿼리로 변환"""
    # 영어가 이미 포함된 경우 그대로 사용
    query = keyword
    if not re.search(r"[a-zA-Z]{3,}", keyword):
        found = False
        for pattern, eng in _KO_TO_EN:
            if pattern.search(keyword):
                query = eng
                found = True
                break
        if not found:
            query = _DEFAULT_QUERY

    # 모든 쿼리에 대해 people-free 필터링 및 감성 톤 강화
    if "no people" not in query.lower() and "people" not in query.lower():
        query = f"{query} no people"
    if "aesthetic" not in query.lower():
        query = f"{query} aesthetic"

    # 레시피/요리 관련 영어 키워드에 대해 korean 묵시적 접두사 부여 (양식/스톡 사진 방지)
    food_kws = ["food", "dish", "cooking", "meal", "recipe", "stew", "soup", "vegetable", "kitchen"]
    if any(fw in query.lower() for fw in food_kws) and "korean" not in query.lower():
        query = f"korean {query}"

    return query


def _fetch_one_image(query: str, api_key: str, exclude_ids: set | None = None) -> dict | None:
    """단일 쿼리로 이미지 1장 수집 (중복 제외 + 관련성 필터로 뜬금없는 사진 제외)"""
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 12,  # 후보 넉넉히 받아 필터링
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        for p in photos:
            if exclude_ids and p["id"] in exclude_ids:
                continue
            cand = {
                "url": p["src"]["large"],
                "alt_text": query,
                "photographer": p.get("photographer", ""),
                "pexels_id": p["id"],
            }
            alt = p.get("alt") or ""
            if _OFFTOPIC_RE.search(alt):
                logger.info(f"관련성 필터: 뜬금없는 사진 제외 (alt={alt[:45]!r}, query={query!r})")
                continue
            return cand
        # 후보가 전부 off-topic(사람 노출 등)이면 억지로 첫 후보를 쓰지 않고 None 반환
        return None
    except Exception as e:
        logger.warning(f"Pexels 단일 수집 실패 (query={query!r}): {e}")
    return None


def get_post_images(
    keyword: str,
    api_key: str,
    count: int = 7,
    category: str = "",
    image_keywords: list[str] | None = None,
) -> list[dict]:
    """
    Pexels 이미지 수집.
    image_keywords (content.py에서 생성된 7개)가 있으면 각 키워드별로 1장씩 수집.
    없으면 기존 방식(키워드 → 영어 변환)으로 count장 수집.
    """
    if not api_key:
        logger.warning("PEXELS_API_KEY 없음 — 이미지 없이 진행")
        return []

    # image_keywords가 있으면 각 위치별 맞춤 이미지 수집
    if image_keywords and len(image_keywords) >= 1:
        results = []
        used_ids: set = set()
        for i, img_kw in enumerate(image_keywords[:count]):
            query = _keyword_to_en(img_kw)
            img = _fetch_one_image(query, api_key, exclude_ids=used_ids)
            if img:
                used_ids.add(img["pexels_id"])
                img["alt_text"] = img_kw  # 원본 키워드를 alt_text로 보존
                results.append(img)
            else:
                # fallback: 기본 키워드로 시도
                fallback_query = _keyword_to_en(keyword)
                img = _fetch_one_image(fallback_query, api_key, exclude_ids=used_ids)
                if img:
                    used_ids.add(img["pexels_id"])
                    img["alt_text"] = keyword
                    results.append(img)
        logger.info(f"Pexels 이미지 {len(results)}개 수집 (image_keywords 방식, {len(image_keywords)}개 키워드)")
        return results

    # 기존 방식: 단일 쿼리로 count장 수집
    search_keyword = keyword
    if category:
        cat_hints = {
            "신혼살림기초": "newlywed home",
            "청소정리": "cleaning organization",
            "요리식비": "cooking food",
            "절약재테크": "budget saving",
            "인테리어": "interior decor",
            "쇼핑정보": "home goods",
        }
        if category in cat_hints:
            search_keyword = f"{keyword} {cat_hints[category]}"

    query = _keyword_to_en(search_keyword)
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": count + 3,
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        results = []
        used_ids: set = set()
        for p in photos:
            if len(results) >= count:
                break
            if p["id"] not in used_ids:
                used_ids.add(p["id"])
                results.append({
                    "url": p["src"]["large"],
                    "alt_text": f"{keyword} 관련 이미지",
                    "photographer": p.get("photographer", ""),
                    "pexels_id": p["id"],
                })
        logger.info(f"Pexels 이미지 {len(results)}개 수집 (query={query!r})")
        return results
    except Exception as e:
        logger.warning(f"Pexels 수집 실패: {e}")
        return []


def fetch_image_urls(keyword: str, count: int = 4, api_key: str = "") -> list[str]:
    """기존 인터페이스 호환용 래퍼"""
    images = get_post_images(keyword=keyword, api_key=api_key, count=count)
    return [img["url"] for img in images]
