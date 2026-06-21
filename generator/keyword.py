"""
포스팅 키워드 선정
- 상시 에버그린 키워드 풀 + 시즌 보정
- Google News RSS 트렌딩 보조 활용
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

# 에버그린 키워드 — 살림/1인가구/신혼 주제
_EVERGREEN: list[str] = [
    "자취 살림 꿀팁",
    "1인 가구 필수템",
    "신혼 살림 체크리스트",
    "자취방 청소 루틴",
    "소형 냉장고 정리법",
    "욕실 곰팡이 제거",
    "주방 냄새 제거 방법",
    "세탁기 청소 주기",
    "자취생 냉동식품 추천",
    "생활비 절약 방법",
    "다이소 살림템",
    "이케아 수납 아이디어",
    "주방 수납 꿀팁",
    "옷장 정리 방법",
    "샤워실 청소 꿀팁",
    "전기세 절약 방법",
    "식비 절약 일주일 식단",
    "간단한 아침 밥상",
    "자취 요리 초보 레시피",
    "냉파 요리 아이디어",
    "청소 동선 루틴",
    "베란다 정리 수납",
    "자취 인테리어 소품",
    "무드등 추천",
    "공기청정기 필터 청소",
]

# 시즌 키워드 (월별)
_SEASON: dict[int, list[str]] = {
    1:  ["겨울 난방비 절약", "신년 집 정리", "방한 꿀템"],
    2:  ["봄맞이 대청소", "설날 집 준비", "봄 인테리어"],
    3:  ["봄 대청소 루틴", "황사 미세먼지 대비", "봄옷 정리"],
    4:  ["봄 인테리어 소품", "꽃가루 알레르기 집 관리", "창문 청소"],
    5:  ["가정의 달 선물", "초여름 집 꾸미기", "에어컨 청소 시기"],
    6:  ["여름 에어컨 관리", "냉방비 절약", "여름 냄새 제거"],
    7:  ["여름 집 습기 관리", "곰팡이 예방", "여름 정리"],
    8:  ["피서 대신 집꾸미기", "여름 인테리어", "냉방 꿀팁"],
    9:  ["가을 이불 교체", "환절기 집 관리", "김장 준비"],
    10: ["가을 인테리어", "단열 점검", "겨울 준비"],
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


def pick_keyword() -> str:
    """오늘 포스팅할 키워드 1개 선택 — 최근 30일 중복 방지"""
    month = datetime.now(KST).month
    pool = _EVERGREEN + _SEASON.get(month, [])
    recent = _get_recent_keywords(days=30)
    fresh = [k for k in pool if k not in recent]
    if not fresh:
        logger.warning(f"모든 키워드가 최근 30일 내 사용됨 — 전체 풀에서 선택")
        fresh = pool
    keyword = random.choice(fresh)
    logger.info(f"키워드 선택: {keyword!r} (신규 후보 {len(fresh)}/{len(pool)}개)")
    return keyword


def get_trending_bonus(limit: int = 5) -> list[str]:
    """Google News RSS에서 생활 관련 트렌딩 키워드 보조 수집"""
    _SKIP = re.compile(r"북한|무기|전쟁|핵|테러|사망|사고|화재|범죄|살인|마약|자살")
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
