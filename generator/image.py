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
    (re.compile(r"욕실|화장실|샤워"), "bathroom cleaning sparkling"),
    (re.compile(r"주방|부엌|싱크대"), "kitchen cleaning cooking"),
    (re.compile(r"세탁기|빨래"), "laundry washing machine"),
    (re.compile(r"청소|정리|루틴"), "home cleaning organization"),
    (re.compile(r"곰팡이|습기"), "mold prevention bathroom"),
    (re.compile(r"요리|레시피|밥|식단|냉파"), "cooking food kitchen meal"),
    (re.compile(r"도시락|아침\s*메뉴"), "lunch box meal prep bento"),
    (re.compile(r"식비\s*절약"), "budget meal planning grocery"),
    (re.compile(r"인테리어|꾸미|홈\s*데코"), "interior home decor cozy"),
    (re.compile(r"수납|정리함|선반"), "storage organization shelves"),
    (re.compile(r"옷장|드레스룸"), "closet wardrobe organization"),
    (re.compile(r"냉장고"), "refrigerator organized kitchen"),
    (re.compile(r"베란다|발코니"), "balcony terrace cozy"),
    (re.compile(r"무드등|조명"), "mood lighting cozy bedroom"),
    (re.compile(r"절약|생활비|가계부"), "saving money budget planning"),
    (re.compile(r"전기세|난방비|냉방비"), "energy saving electricity"),
    (re.compile(r"에어컨"), "air conditioner home cooling"),
    (re.compile(r"다이소"), "affordable home goods storage"),
    (re.compile(r"이케아"), "ikea furniture home organization"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner"),
    (re.compile(r"공기청정기"), "air purifier home"),
    (re.compile(r"신혼|살림"), "newlywed couple home living"),
    (re.compile(r"자취|1인\s*가구"), "cozy small apartment single"),
    (re.compile(r"혼수|결혼\s*준비"), "wedding home preparation"),
]
_DEFAULT_QUERY = "cozy Korean home lifestyle"


def _keyword_to_en(keyword: str) -> str:
    """한국어 키워드를 Pexels 검색용 영어 쿼리로 변환"""
    # 영어가 이미 포함된 경우 그대로 사용
    if re.search(r"[a-zA-Z]{3,}", keyword):
        return keyword
    for pattern, eng in _KO_TO_EN:
        if pattern.search(keyword):
            return eng
    return _DEFAULT_QUERY


def _fetch_one_image(query: str, api_key: str, exclude_ids: set | None = None) -> dict | None:
    """단일 쿼리로 이미지 1장 수집 (중복 제외)"""
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 5,
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
            return {
                "url": p["src"]["large"],
                "alt_text": query,
                "photographer": p.get("photographer", ""),
                "pexels_id": p["id"],
            }
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
