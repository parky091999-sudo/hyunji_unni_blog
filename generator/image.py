"""
Pexels API로 키워드 관련 이미지 URL 수집
카테고리별 한국어 → 영어 검색어 매핑 강화
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"

# 카테고리/키워드 → 영문 검색어 매핑 (우선순위순)
_KO_TO_EN: list[tuple[re.Pattern, str]] = [
    # 청소/정리
    (re.compile(r"욕실|화장실|샤워"), "bathroom cleaning sparkling"),
    (re.compile(r"주방|부엌|싱크대"), "kitchen cleaning cooking"),
    (re.compile(r"세탁기|빨래"), "laundry washing machine"),
    (re.compile(r"청소|정리|루틴"), "home cleaning organization"),
    (re.compile(r"곰팡이|습기"), "mold prevention bathroom"),
    # 요리/식비
    (re.compile(r"요리|레시피|밥|식단|냉파"), "cooking food kitchen meal"),
    (re.compile(r"도시락|아침\s*메뉴"), "lunch box meal prep bento"),
    (re.compile(r"식비\s*절약"), "budget meal planning grocery"),
    # 인테리어/수납
    (re.compile(r"인테리어|꾸미|홈\s*데코"), "interior home decor cozy"),
    (re.compile(r"수납|정리함|선반"), "storage organization shelves"),
    (re.compile(r"옷장|드레스룸"), "closet wardrobe organization"),
    (re.compile(r"냉장고"), "refrigerator organized kitchen"),
    (re.compile(r"베란다|발코니"), "balcony terrace cozy"),
    (re.compile(r"무드등|조명"), "mood lighting cozy bedroom"),
    # 절약/재테크
    (re.compile(r"절약|생활비|가계부"), "saving money budget planning"),
    (re.compile(r"전기세|난방비|냉방비"), "energy saving electricity"),
    # 쇼핑/제품
    (re.compile(r"다이소"), "affordable home goods storage"),
    (re.compile(r"이케아"), "ikea furniture home organization"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner"),
    (re.compile(r"공기청정기"), "air purifier home"),
    # 살림/신혼
    (re.compile(r"신혼|살림"), "newlywed couple home living"),
    (re.compile(r"자취|1인\s*가구"), "cozy small apartment single"),
    (re.compile(r"혼수|결혼\s*준비"), "wedding home preparation"),
]
_DEFAULT_QUERY = "cozy Korean home lifestyle"


def _keyword_to_en(keyword: str) -> str:
    """한국어 키워드를 Pexels 검색용 영어 쿼리로 변환"""
    for pattern, eng in _KO_TO_EN:
        if pattern.search(keyword):
            return eng
    return _DEFAULT_QUERY


def get_post_images(
    keyword: str,
    api_key: str,
    count: int = 3,
    category: str = "",
) -> list[dict]:
    """
    키워드 기반 Pexels 이미지 검색.
    카테고리 정보가 있으면 검색 품질 향상.

    반환: [{"url": str, "alt_text": str, "photographer": str}, ...]
    """
    if not api_key:
        logger.warning("PEXELS_API_KEY 없음 — 이미지 없이 진행")
        return []

    # 카테고리 힌트가 있으면 쿼리 보정
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
                "per_page": count + 2,  # 여유 수집 후 필터링
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        results = []
        for p in photos[:count]:
            results.append({
                "url": p["src"]["large"],
                "alt_text": f"{keyword} 관련 이미지",
                "photographer": p.get("photographer", ""),
                "pexels_url": p.get("url", ""),
            })
        logger.info(f"Pexels 이미지 {len(results)}개 수집 (query={query!r})")
        return results
    except Exception as e:
        logger.warning(f"Pexels 수집 실패: {e}")
        return []


# 하위 호환성 — 기존 fetch_image_urls() 호출 코드 지원
def fetch_image_urls(keyword: str, count: int = 4, api_key: str = "") -> list[str]:
    """기존 인터페이스 호환용 래퍼 — URL 목록만 반환"""
    images = get_post_images(keyword=keyword, api_key=api_key, count=count)
    return [img["url"] for img in images]
