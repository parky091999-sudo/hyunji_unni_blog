"""
포스팅 키워드 선정
- 카테고리 기반 요일별 로테이션
- 에버그린 키워드 풀 + 시즌 보정
- 최근 30일 사용 키워드 중복 방지
"""
import json
import logging
import os
import random
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

# 카테고리 정의 — 요일별 포스팅 타겟 (0=월, 1=화, ..., 6=일)
CATEGORIES: dict[str, dict] = {
    "신혼살림기초": {
        "name": "신혼살림 기초",
        "keywords": [
            "신혼 살림 체크리스트",
            "신혼 필수템 목록",
            "혼수 준비 리스트",
            "신혼집 장만 순서",
            "신혼 살림 예산 짜는 법",
            "결혼 준비 살림 뭐부터",
            "신혼집 첫 살림 필수품",
            "혼수 적게 쓰는 방법",
            "신혼 살림 다이소로 완성",
            "신혼 이불 세탁 주기",
        ],
        "posting_days": [1, 4],  # 화, 금
    },
    "청소정리": {
        "name": "청소&정리",
        "keywords": [
            "욕실 청소 꿀팁",
            "주방 기름때 제거",
            "세탁기 청소 주기",
            "욕실 곰팡이 제거",
            "청소 루틴 만들기",
            "환기구 청소 방법",
            "싱크대 배수구 냄새 제거",
            "베란다 청소 꿀팁",
            "샤워실 물때 제거",
            "냉장고 청소 방법",
            "에어컨 필터 청소",
            "공기청정기 필터 교체 주기",
        ],
        "posting_days": [2, 5],  # 수, 토
    },
    "요리식비": {
        "name": "요리&식비절약",
        "keywords": [
            "냉파 요리 아이디어",
            "식비 절약 일주일 식단",
            "간단한 아침 메뉴",
            "자취 요리 초보 레시피",
            "일주일 반찬 만들기",
            "냉동식품 활용 요리",
            "식비 한 달 20만원",
            "간단 도시락 메뉴",
            "주말 요리 일주일 치",
            "칼로리 낮은 간단 요리",
        ],
        "posting_days": [3, 6],  # 목, 일
    },
    "절약재테크": {
        "name": "절약&재테크",
        "keywords": [
            "생활비 절약 방법",
            "관리비 줄이는 법",
            "전기세 절약 방법",
            "가계부 쓰는 법",
            "신혼 생활비 얼마",
            "체크카드 vs 신용카드",
            "생활비 통장 쪼개기",
            "공과금 자동이체 혜택",
            "알뜰폰으로 바꾸기",
            "구독서비스 정리하기",
            "난방비 절약 꿀팁",
            "냉방비 절약 방법",
        ],
        "posting_days": [1, 3],  # 월(0), 화(1), 수(2) -> 화(1), 목(3)
    },
    "인테리어": {
        "name": "인테리어&소품",
        "keywords": [
            "자취 인테리어 소품",
            "원룸 꾸미기 꿀팁",
            "다이소 인테리어 소품",
            "신혼집 인테리어 저렴하게",
            "옷장 정리 방법",
            "주방 수납 꿀팁",
            "베란다 정리 수납",
            "소형 냉장고 정리법",
            "무드등 추천",
            "화장대 정리 방법",
            "이케아 수납 아이디어",
            "드레스룸 없는 집 옷 정리",
        ],
        "posting_days": [2, 5],  # 수, 토
    },
    "쇼핑정보": {
        "name": "쇼핑&제품추천",
        "keywords": [
            "다이소 추천템",
            "이케아 추천 제품",
            "주방용품 추천",
            "신혼 살림 추천 제품",
            "다이소 청소 용품",
            "쿠팡 생활용품 추천",
            "이케아 수납 추천",
            "로봇청소기 추천",
            "스팀 청소기 추천",
            "공기청정기 추천",
            "전기밥솥 추천",
            "식기세척기 추천",
        ],
        "posting_days": [0, 4],  # 월, 금
    },
    "신혼일상": {
        "name": "신혼일상",
        "keywords": [
            "신혼일기 주말 데이트 요리",
            "퇴근 후 남편이랑 저녁 차려먹기",
            "주말에 신혼집 대청소한 날",
            "다이소 쇼핑 2만원의 행복",
            "남편이랑 가계부 점검일기",
            "여름맞이 이불 세탁하고 코인빨래방 다녀옴",
            "신혼부부 식비 절약 냉장고 털기 일상",
            "초보 주부의 하루 살림 일기",
            "수원 신혼 아파트 첫 집들이 날",
            "주말 이케아 다녀온 후기",
        ],
        "posting_days": [0, 1, 2, 3, 4, 5, 6],
    },
}

# 시즌 키워드 (월별 보정)
_SEASON: dict[int, list[str]] = {
    1:  ["겨울 난방비 절약", "신년 집 정리", "방한 꿀템"],
    2:  ["봄맞이 대청소 준비", "설날 집 준비", "봄 인테리어 미리 준비"],
    3:  ["봄 대청소 루틴", "황사 미세먼지 대비", "봄옷 정리 수납"],
    4:  ["봄 인테리어 소품", "꽃가루 알레르기 집 관리", "창문 청소 방법"],
    5:  ["가정의 달 선물 추천", "초여름 집 꾸미기", "에어컨 청소 시기"],
    6:  ["여름 에어컨 관리", "냉방비 절약", "여름 냄새 제거"],
    7:  ["여름 집 습기 관리", "여름 곰팡이 예방", "여름 정리 정돈"],
    8:  ["피서 대신 집꾸미기", "여름 인테리어", "선풍기 청소 방법"],
    9:  ["가을 이불 교체", "환절기 집 관리", "김장 준비 용품"],
    10: ["가을 인테리어", "단열 점검 방법", "겨울 준비 시작"],
    11: ["김장 도구 추천", "겨울 이불 수납", "난방기기 점검"],
    12: ["연말 집 정리", "크리스마스 홈 데코", "겨울 살림 필수템"],
}

_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "post_history.json"
)


def _get_recent_keywords(days: int = 30) -> set[str]:
    """최근 N일 이내 사용한 키워드 반환"""
    try:
        if not os.path.exists(_HISTORY_PATH):
            return set()
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
        cutoff = datetime.now(KST) - timedelta(days=days)
        recent = set()
        for h in history:
            try:
                ts = datetime.fromisoformat(h.get("timestamp", ""))
                if ts >= cutoff and h.get("keyword"):
                    recent.add(h["keyword"])
            except Exception:
                continue
        return recent
    except Exception as e:
        logger.warning(f"이력 키워드 로드 실패: {e}")
        return set()


def _get_today_category() -> tuple[str, dict]:
    """오늘 요일에 맞는 카테고리 선택. 복수 카테고리 해당 시 랜덤 선택."""
    weekday = datetime.now(KST).weekday()  # 0=월, 1=화, ..., 6=일
    matched = [
        (cat_id, cat_info)
        for cat_id, cat_info in CATEGORIES.items()
        if weekday in cat_info["posting_days"]
    ]
    if matched:
        chosen = random.choice(matched)
        return chosen
    # 해당 요일 카테고리 없으면 전체에서 랜덤
    cat_id = random.choice(list(CATEGORIES.keys()))
    return cat_id, CATEGORIES[cat_id]


def pick_keyword() -> dict:
    """
    오늘 포스팅할 키워드 1개 선택.
    반환: {"keyword": str, "category": str, "category_name": str}
    최근 30일 중복 방지 + 요일별 카테고리 로테이션
    """
    month = datetime.now(KST).month
    recent = _get_recent_keywords(days=30)

    # 오늘 카테고리 선정
    cat_id, cat_info = _get_today_category()
    cat_pool = cat_info["keywords"] + _SEASON.get(month, [])

    # 카테고리 내 미사용 키워드 우선
    fresh = [k for k in cat_pool if k not in recent]
    if not fresh:
        logger.warning(f"카테고리 {cat_info['name']} 키워드 소진 — 전체 풀에서 선택")
        # 전체 카테고리 키워드에서 찾기
        all_keywords = []
        for ci in CATEGORIES.values():
            all_keywords.extend(ci["keywords"])
        all_keywords.extend(_SEASON.get(month, []))
        fresh = [k for k in all_keywords if k not in recent]
        if not fresh:
            logger.warning("전체 키워드 소진 — 카테고리 풀에서 재사용")
            fresh = cat_pool

    keyword = random.choice(fresh)
    logger.info(
        f"키워드 선택: {keyword!r} | 카테고리: {cat_info['name']} "
        f"(신규 후보 {len(fresh)}/{len(cat_pool)}개)"
    )
    return {
        "keyword": keyword,
        "category": cat_id,
        "category_name": cat_info["name"],
    }


def get_trending_bonus(limit: int = 5) -> list[str]:
    """Google News RSS에서 생활 관련 트렌딩 키워드 보조 수집"""
    _SKIP = re.compile(
        r"북한|무기|전쟁|핵|테러|사망|사고|화재|범죄|살인|마약|자살|부고|피해|사건|정치|선거|"
        r"트럼프|바이든|푸틴|시진핑|총리|의원|여당|야당|검찰|기소|법원|판결|외교|국방|"
        r"대통령|국회|정당|총선|대선|장관|수석|참모|의혹|비리|부패|탄핵"
    )
    try:
        r = requests.get(
            "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"},
        )
        root = ElementTree.fromstring(r.content)
        topics = []
        for item in root.findall(".//item/title"):
            title = (item.text or "").strip()
            if not title or _SKIP.search(title):
                continue
            title = re.sub(r"\s+-\s+\S+$", "", title).strip()
            if len(title) > 4:
                topics.append(title)
            if len(topics) >= limit:
                break
        return topics
    except Exception as e:
        logger.warning(f"트렌딩 수집 실패: {e}")
        return []


def pick_keyword_for_blog_category(blog_category: str) -> dict:
    """
    특정 블로그 카테고리에 적합한 키워드를 선정하여 반환.
    최근 30일 중복 방지 반영.
    """
    # 블로그 카테고리별 매핑
    mapping = {
        "알뜰 살림 꿀팁": ["청소정리", "절약재테크", "신혼살림기초"],
        "살림템 비교·추천": ["인테리어", "쇼핑정보"],
        "일상": ["신혼일상"],
    }
    
    keyword_cats = mapping.get(blog_category, ["청소정리"])
    chosen_cat_id = random.choice(keyword_cats)
    cat_info = CATEGORIES[chosen_cat_id]
    
    month = datetime.now(KST).month
    recent = _get_recent_keywords(days=30)
    
    cat_pool = cat_info["keywords"]
    if chosen_cat_id == "청소정리":
        cat_pool = cat_pool + _SEASON.get(month, [])
        
    fresh = [k for k in cat_pool if k not in recent]
    if not fresh:
        logger.warning(f"카테고리 {cat_info['name']} 키워드 소진 — 전체 풀에서 재사용")
        fresh = cat_pool
        
    keyword = random.choice(fresh)
    logger.info(
        f"블로그 카테고리 '{blog_category}' -> 키워드 선택: {keyword!r} | "
        f"키워드 카테고리: {cat_info['name']}"
    )
    return {
        "keyword": keyword,
        "category": chosen_cat_id,
        "category_name": cat_info["name"],
    }

