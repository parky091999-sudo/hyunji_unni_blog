"""
Pexels API로 키워드 관련 이미지 URL 수집
- 네이버 블로그 HTML에 <img src="..."> 로 직접 삽입
"""
import logging
import re

import requests

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"

# 키워드 → 영문 검색어 매핑 (Pexels 영문 검색)
_KO_TO_EN: list[tuple[re.Pattern, str]] = [
    (re.compile(r"청소|정리"), "home cleaning organization"),
    (re.compile(r"요리|레시피|밥|식단"), "cooking food kitchen"),
    (re.compile(r"인테리어|소품|꾸미"), "interior home decor"),
    (re.compile(r"수납|정리함"), "storage organization shelves"),
    (re.compile(r"냉장고"), "refrigerator kitchen"),
    (re.compile(r"세탁|빨래"), "laundry washing"),
    (re.compile(r"욕실|화장실"), "bathroom clean"),
    (re.compile(r"절약|생활비"), "saving money budget"),
    (re.compile(r"자취|1인 가구"), "cozy small apartment"),
    (re.compile(r"신혼|살림"), "newlywed couple home"),
]
_DEFAULT_QUERY = "cozy home living lifestyle"


def _keyword_to_en(keyword: str) -> str:
    for pattern, eng in _KO_TO_EN:
        if pattern.search(keyword):
            return eng
    return _DEFAULT_QUERY


def fetch_image_urls(keyword: str, count: int = 4, api_key: str = "") -> list[str]:
    """키워드 관련 Pexels 이미지 URL 목록 반환 (landscape 위주)"""
    if not api_key:
        logger.warning("PEXELS_API_KEY 없음 — 이미지 없이 진행")
        return []

    query = _keyword_to_en(keyword)
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={"query": query, "per_page": count, "orientation": "landscape"},
            timeout=10,
        )
        photos = r.json().get("photos", [])
        urls = [p["src"]["large"] for p in photos]
        logger.info(f"Pexels 이미지 {len(urls)}개 수집 (query={query!r})")
        return urls
    except Exception as e:
        logger.warning(f"Pexels 수집 실패: {e}")
        return []
