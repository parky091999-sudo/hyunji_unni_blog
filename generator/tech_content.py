"""
형수의테크공장 — IT/테크 뉴스 자동 포스트 생성 (프로토타입).

핵심 설계:
  · 뉴스 = 트래픽 엔진 → Naver 뉴스 검색 API로 최근 N일 기사만 팩트로 사용(pubDate 필터)
  · 글 형식 4종 로테이션 → 매 발행 형식 순환(지루함 방지 + 깔때기 단계별 독자)
  · 출력 포맷은 gov/health와 동일 → generator.content._parse_response 그대로 재사용
  · 이미지: 판매제품=쇼핑API 실사진 / 루머=인포그래픽 (본 모듈은 마커만 배치, poster가 처리)

형식(fmt):
  breaking  ① 속보·루머   — 홈피드 유입 (이미지=인포그래픽)
  explain   ② 쉬운 해설   — 검색·신뢰   (이미지=AI 일러스트/개념도)
  pick      ③ 꿀템 큐레이터 — 쇼핑커넥트 전환 (이미지=쇼핑API 실사진)
  compare   ④ 비교·논란   — 체류시간   (이미지=인포그래픽+쇼핑API)
"""
import logging
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER
from generator.info_collector import _fetch_naver_news

logger = logging.getLogger("tech_content")

KST = timezone(timedelta(hours=9))
TECH_BODY_MIN = 1300  # 하한은 안전망, 목표 길이(1700~2400)는 프롬프트로 유도

# 종합 테크 시드 — ★구체적 소비자 '제품/모델'로 한정(추상 키워드는 산업·이벤트 뉴스를 물어와 트래픽 저조).
# 실제 글감은 시드로 최신 뉴스를 조회해 그 헤드라인/맥락에서 결정(뉴스 주도 = 항상 신선).
TECH_SEEDS = [
    # 스마트폰 (구체 모델)
    "아이폰 18", "갤럭시 S26", "갤럭시 Z 폴드", "갤럭시 Z 플립", "아이폰 에어",
    "픽셀 스마트폰", "갤럭시 AI",
    # 웨어러블·오디오
    "갤럭시 워치", "애플워치", "에어팟", "갤럭시 버즈", "무선이어폰 신제품",
    # PC·부품
    "게이밍 노트북", "RTX 그래픽카드", "맥북", "게이밍 모니터",
    # 가전·디지털
    "로봇청소기", "에어프라이어", "삼성 TV 신제품", "무선청소기", "공기청정기", "제습기",
    # 자동차 (소비자 관심 신차/전기차)
    "아이오닉", "기아 EV", "테슬라 모델", "전기차 신차 출시",
    # AI 소비자 서비스
    "챗GPT 신기능", "AI 스마트폰",
]

# 시드 → 블로그 카테고리 매핑 (hyungsutech에 생성된 주제별 카테고리로 자동 분류)
SEED_CATEGORY = {
    "아이폰 18": "스마트폰·모바일", "갤럭시 S26": "스마트폰·모바일", "갤럭시 Z 폴드": "스마트폰·모바일",
    "갤럭시 Z 플립": "스마트폰·모바일", "아이폰 에어": "스마트폰·모바일", "픽셀 스마트폰": "스마트폰·모바일",
    "갤럭시 AI": "스마트폰·모바일", "갤럭시 워치": "스마트폰·모바일", "애플워치": "스마트폰·모바일",
    "에어팟": "스마트폰·모바일", "갤럭시 버즈": "스마트폰·모바일", "무선이어폰 신제품": "스마트폰·모바일",
    "게이밍 노트북": "PC·노트북", "RTX 그래픽카드": "PC·노트북", "맥북": "PC·노트북", "게이밍 모니터": "PC·노트북",
    "로봇청소기": "가전·디지털", "에어프라이어": "가전·디지털", "삼성 TV 신제품": "가전·디지털",
    "무선청소기": "가전·디지털", "공기청정기": "가전·디지털", "제습기": "가전·디지털",
    "아이오닉": "자동차·모빌리티", "기아 EV": "자동차·모빌리티", "테슬라 모델": "자동차·모빌리티",
    "전기차 신차 출시": "자동차·모빌리티",
    "챗GPT 신기능": "AI·IT", "AI 스마트폰": "AI·IT",
}


def category_for_seed(seed: str) -> str:
    return SEED_CATEGORY.get(seed, "스마트폰·모바일")


# 형식별 이미지 전략(라벨용) — poster 연동은 다음 단계. 지금은 헤더 [사진1]만 사용.
FMT_IMAGE = {
    "breaking": "infographic",
    "explain": "illustration",
    "pick": "shopping",
    "compare": "infographic",
}

_COMMON_RULES = """\
너는 '형수의테크공장' 블로그 작가 '형수'다. 어려운 최신 테크 소식을 누구나 5분 안에
이해하도록 쉽고 정확하게 풀어준다. (현지언니의 손윗동서 격 — 친근하지만 팩트에 엄격)

[절대 원칙]
1. 아래 [최신 뉴스] 팩트에 있는 사실만 단정. 없는 스펙·가격·일정은 지어내지 마라.
2. 확정 안 된 소식은 반드시 "~로 알려졌다 / ~로 전망된다 / 유출됐다" 톤. 단정 금지.
3. 낡은 정보 금지 — 뉴스 날짜 기준 최신만. 본문 어딘가에 기준일("2026년 7월 기준") 표기.
4. 금지어: 안녕하세요/이처럼/이로써/혁신적인/탁월한/극대화/마크다운(**#)/이모지
5. 소제목 텍스트 맨 앞에 번호(1./①) 붙이지 마라 — 회색바+볼드로 구분됨.
6. 목록/장점/대상 나열의 모든 항목 줄은 반드시 '· '(가운뎃점+공백)로 시작. '라벨: 설명' 형태여도 앞에 · 필수. 단계 번호는 ①②③.
7. 단락은 2~3줄 이내. 한 문장 = 한 줄 지향(모바일 스캔형).
8. 2단 계층: 상위 분류는 [[분류명]] 볼드 라벨(글머리 · 없이 한 줄), 세부만 그 아래 · 불릿. 부모·자식 같은 글머리 금지.
9. ★초점 엄수: 오직 주어진 주제와 '직접' 관련된 사실만 써라. 무관한 다른 제품·행사·지역·기업 소식은 절대 섞지 마라(초점 흐려짐).
10. ★표 규칙: 각 셀은 짧게(20자 이내). 한 셀 안에 여러 줄·여러 불릿(·) 절대 금지 — 항목이 많으면 셀에 몰아넣지 말고 행을 나눠라. (예: 칩셋/RAM/배터리/가격을 각각 다른 행으로. 한 셀에 스펙 5개 나열 금지)

[출력 형식 — 반드시 정확히]
TITLE: {후킹 제목 35자 이내 — 궁금증/결론약속/수치 중 하나. 과장·낚시 금지}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6}
IMAGE_KEYWORDS: tech header
IMAGE_LABELS: {키워드 한글}
---
{본문 — 아래 구조 그대로}
"""

# ── 형식별 구조 — 현지언니 정보성 포맷(✔요약박스·FAQ) 탈피, 테크 블로그 네이티브 구조 ──
# [사진1] = 발행 스크립트가 뉴스 실사진(og:image)을 자동 삽입하는 홈판 대표 썸네일 자리.
#           카드형 인포그래픽 아님 → 도입부에서 이미지를 설명하려 들지 마라(사진은 그냥 얹힌다).
_FMT_PROMPTS = {
    # ① 속보·루머 — 뉴스형(두괄식 리드). 홈피드 유입.
    "breaking": _COMMON_RULES + """
[구조 — 뉴스형(두괄식)]
[사진1]
(리드 2~3줄. 첫 문장에 핵심 소식을 즉시 — "무엇이 공개/유출됐다"를 두괄식으로. 낚시 금지.)

[소제목] 무슨 일이 있었나
(유출·발표 내용을 서술형 3~5줄. 출처 성격 명시: "업계에 따르면", "유출 정보로는". 확정 안 된 건 단정 금지.)

[소제목] 핵심 스펙·일정
(팩트가 있으면 아래 표로, 없으면 서술로. 표는 2~3열, 각 셀 12자 이내, 빈칸 금지.)
[표시작]
항목 | 내용
칩셋 | ~
출시 예상 | ~
[표끝]

[소제목] 왜 중요한가
(이 소식이 소비자·시장에 주는 의미 3~5줄. 이전 세대·경쟁 제품과의 맥락을 구체적으로. 단정 금지.)

(마무리 2줄: "공식 발표 전이라 변동 가능" 류 한 줄 + 기준일.)
""",
    # ② 쉬운 해설 — 해설형(비유·개념). 검색·신뢰.
    "explain": _COMMON_RULES + """
[구조 — 해설형]
[사진1]
(리드 2~3줄. 독자가 궁금해할 지점을 질문처럼 던지고, 결론을 살짝 먼저 흘리며 쉽게 풀어주겠다 예고.)

[소제목] 한마디로 이게 뭐냐면
(핵심 개념을 첫 1~2문장에 결론부터 정의. 그다음 풀어서 3~5줄. 두괄식 필수.)

[소제목] 쉽게 비유하면
(어려운 원리를 일상 비유로. 3~4줄.)

[소제목] 뭐가 좋아지나
(체감되는 변화·장점을 · 불릿으로. 각 항목에 구체 팩트·수치.)

[소제목] 이런 사람에게 특히 좋다
(실제 사용 시나리오 3~4줄.)

(마무리 2줄 + 기준일.)
""",
    # ③ 꿀템 큐레이터 — 리뷰/스펙형. 쇼핑커넥트 전환.
    "pick": _COMMON_RULES + """
[구조 — 리뷰/스펙형]
[사진1]
(한줄평 리드 2~3줄. 어떤 니즈의 제품을 왜 추천하는지, 가격·가성비로 후킹.)

[소제목] 어떤 제품인가
(제품 성격·핵심 특징 3~5줄. 실제 스펙 팩트만.)

[소제목] 스펙·가격 한눈에
(★항목마다 행을 나눠라. 한 셀에 스펙 여러 개·불릿 몰아넣기 금지. 각 셀 20자 이내.)
[표시작]
항목 | 내용
칩셋 | ~
RAM·저장 | ~
배터리 | ~
가격 | ~
[표끝]
(출처: 가격·스펙은 판매처 기준, 변동 가능 — 1줄)

[소제목] 좋은 점 / 아쉬운 점
(· 불릿으로 장점과 단점을 균형 있게. 단점도 솔직하게 — 광고티 금지.)

[소제목] 이런 분께 추천
(구매 적합 대상을 · 불릿으로. 3~4개.)

[쇼핑추천]
(※ 쇼핑커넥트 링크 자리 — 발급 후 삽입)

(마무리 2줄 + 기준일.)
""",
    # ④ 비교·논란 — 비교형(표 중심). 체류시간.
    "compare": _COMMON_RULES + """
[구조 — 비교형(표 중심)]
[사진1]
(리드 2~3줄. 무엇이 논란/비교 대상인지 쟁점을 즉시.)

[소제목] 무엇이 쟁점인가
(비교 포인트·논란을 서술형 3~5줄으로. 양쪽 입장을 균형 있게.)

[소제목] 항목별 비교
(비교가 핵심이니 표를 충실히 — 4~5개 항목 행. 각 셀 15자 이내, 빈칸 금지.)
[표시작]
항목 | A | B
가격 | ~ | ~
성능 | ~ | ~
[표끝]

[소제목] 그래서 뭘 골라야 하나
(용도·예산별 결론을 · 불릿으로. 단정보다 "~라면 A" 조건부로.)

(마무리 2줄 + 기준일.)
""",
}


def _recent_tech_news(keyword: str, days: int = 7, display: int = 8) -> list[dict]:
    """Naver 뉴스에서 keyword 최근 기사 → pubDate로 days일 이내만 필터(낡은 자료 배제)."""
    raw = _fetch_naver_news(keyword, display=display)
    if not raw:
        return []
    cutoff = datetime.now(KST) - timedelta(days=days)
    fresh = []
    for n in raw:
        try:
            dt = parsedate_to_datetime(n.get("date", ""))
            if dt and dt.astimezone(KST) >= cutoff:
                fresh.append(n)
        except Exception:
            fresh.append(n)  # 날짜 파싱 실패 시 보존(하드 배제 안 함)
    logger.info(f"테크 뉴스 필터: {keyword!r} {len(raw)}건 → 최근 {days}일 {len(fresh)}건")
    return fresh


# 소비자 관심 신호 — 헤드라인에 있으면 가점(출시·가격·비교 등 트래픽 되는 소비자 제품 주제)
_CONSUMER_SIGNALS = (
    "출시", "출시일", "가격", "공개", "스펙", "신제품", "리뷰", "성능",
    "할인", "예약", "사전예약", "언박싱", "배터리", "카메라", "디스플레이",
    "업데이트", "탑재", "유출", "렌더링", "체험", "써보니", "직접", "후기",
)
# 트래픽 약한 뉴스 — 강한 감점. 학술/B2B/지역/행정 + 비즈니스/노조/증시/법률 노이즈까지 배제.
_NONCONSUMER_SIGNALS = (
    # 학술·B2B·지역·행정
    "대학", "연구진", "연구소", "논문", "학회", "포럼", "세미나", "컨퍼런스",
    "수상", "우승", "선정", "협약", "MOU", "산학", "특허", "장관", "지자체",
    "시장", "도지사", "군수", "구청", "박람회", "설명회", "간담회", "위원회",
    "채용", "공모전", "육성", "지원사업", "정책", "규제", "국회", "부처", "행사",
    # 비즈니스·노조·증시·법률 (소비자 무관)
    "파업", "노조", "노사", "실적", "주가", "매출", "영업이익", "증권", "투자",
    "리콜", "소송", "담합", "공정위", "인수", "합병", "CEO", "임원", "인사",
    "컨센서스", "목표주가", "배당", "지분", "적자", "흑자", "수출", "관세",
    # 개발자·B2B 이벤트 (컨퍼런스/전시 = 트래픽 저조)
    "페스트", "세션", "개발자", "언리얼", "엔진", "간담회", "쇼케이스",
    "웨비나", "밋업", "해커톤", "SDK", "API", "오픈소스", "출품", "전시회",
)


def _score_headline(title: str) -> int:
    """헤드라인 소비자 관심도 점수. 소비자 신호 +, 학술/B2B/지역 신호 강한 -."""
    score = 0
    for kw in _CONSUMER_SIGNALS:
        if kw in title:
            score += 2
    for kw in _NONCONSUMER_SIGNALS:
        if kw in title:
            score -= 5
    return score


def pick_tech_topic(days: int = 7, exclude: set | None = None) -> dict | None:
    """여러 시드의 최신 뉴스를 모아 '소비자 관심도' 최고 헤드라인을 글감으로 선정.
    학술/B2B/지역 뉴스는 감점으로 배제 → 트래픽 되는 소비자 주제로 편향.
    반환: {seed, headline, news:[...]} — headline이 실제 글 주제.
    """
    exclude = exclude or set()
    seeds = [s for s in TECH_SEEDS if s not in exclude]
    random.shuffle(seeds)
    candidates = []  # (score, seed, news_item, news_list)
    for seed in seeds[:10]:
        news = _recent_tech_news(seed, days=days)
        for n in news:
            candidates.append((_score_headline(n["title"]), seed, n, news))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_score, seed, item, news = candidates[0]
    if best_score <= 0:
        logger.warning(f"소비자 관심 신호 약함(최고점 {best_score}) — 그래도 최상위 채택: {item['title'][:30]}")
    logger.info(f"주제 선정: [{seed}] {item['title'][:40]} (점수 {best_score})")
    # 선정 헤드라인과 같은 시드의 뉴스만 맥락으로 전달(초점 유지)
    return {"seed": seed, "headline": item["title"], "news": news}


def _build_news_block(topic: dict) -> str:
    lines = [f"[최신 뉴스 — {datetime.now(KST).strftime('%Y년 %m월 %d일')} 기준, 최근 7일 기사만]"]
    lines.append(f"주제 시드: {topic['seed']}")
    for n in topic["news"][:6]:
        lines.append(f"  · {n['date'][:16]} | {n['title']}")
        if n.get("desc"):
            lines.append(f"    → {n['desc'][:100]}")
    lines.append("\n위 뉴스 팩트에 있는 사실만 사용해라. 없는 스펙·가격·일정은 지어내지 말 것.\n")
    return "\n".join(lines)


def generate_tech_post(api_key: str, fmt: str = "breaking", topic: dict | None = None) -> dict | None:
    """테크 포스트 생성. fmt: breaking/explain/pick/compare. topic 없으면 자동 선정."""
    if fmt not in _FMT_PROMPTS:
        fmt = "breaking"
    if topic is None:
        topic = pick_tech_topic()
        if topic is None:
            logger.error("최신 테크 뉴스 없음 — 생성 중단")
            return None

    news_block = _build_news_block(topic)
    system = _FMT_PROMPTS[fmt]
    user_msg = news_block + (
        f"\n위 뉴스 중 가장 화제성 있는 '{topic['headline']}' 관련 내용을 중심으로 "
        f"'{fmt}' 형식의 테크 글을 작성해라.\n"
        "- ★본문 1,700~2,400자. 각 소제목마다 3~5줄로 충실히 — 배경·맥락·소비자 영향·구체 예시를 담아 밀도를 채워라(빈약한 한두 줄 금지).\n"
        "- ★구체 팩트 필수: 모델명·수치·가격대·이전 세대나 경쟁 제품과의 비교를 뉴스 팩트 범위에서 최대한 담아라(막연한 서술 금지).\n"
        "- 확정 안 된 건 '~로 알려졌다' 톤, 기준일 표기 필수.\n"
        "- 맨 위 [사진1]은 발행 스크립트가 뉴스 실사진을 자동으로 얹는 자리다. 마커는 [사진1] 하나만 두고, 도입부에서 '사진을 보면' 식으로 이미지를 설명하지 마라."
    )

    waits = [10, 30]
    for attempt in range(1, len(waits) + 2):
        try:
            # 실시간성 강화: Google Search Grounding 활성화(뉴스 팩트 보강)
            raw = _gen_text(api_key, user_msg, system, 8192, 0.85, use_search=True)
            if not raw:
                logger.warning(f"테크글 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"테크글 파싱 실패 (시도 {attempt})")
                continue
            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            if body_len < TECH_BODY_MIN:
                logger.warning(f"테크글 본문 짧음 ({body_len}자, 최소 {TECH_BODY_MIN}) — 재생성")
                continue
            parsed["fmt"] = fmt
            parsed["seed"] = topic["seed"]
            parsed["image_strategy"] = FMT_IMAGE[fmt]
            logger.info(
                f"테크글 생성 완료 [{fmt}]: {parsed.get('title')!r} "
                f"(본문 {body_len}자, 표={bool(parsed.get('table_str'))}, "
                f"FAQ={bool(parsed.get('faq_str'))}, 요약={bool(parsed.get('summary_text'))})"
            )
            return parsed
        except Exception as e:
            logger.error(f"테크글 생성 실패 (시도 {attempt}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])
    return None


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    from config import GOOGLE_API_KEY

    fmt_arg = sys.argv[1] if len(sys.argv) > 1 else "breaking"
    post = generate_tech_post(GOOGLE_API_KEY, fmt=fmt_arg)
    if not post:
        print("생성 실패")
        sys.exit(1)
    print("\n" + "=" * 70)
    print(f"[형식] {post['fmt']}  |  [이미지전략] {post['image_strategy']}  |  [시드] {post['seed']}")
    print(f"[제목] {post['title']}")
    print(f"[태그] {', '.join(post.get('tags', []))}")
    print(f"[소제목] {post.get('subheadings')}")
    print("=" * 70)
    print(post["body"])
    print("=" * 70)
    if post.get("table_strs"):
        print("[표]", post["table_strs"])
    if post.get("faq_pairs"):
        print("[FAQ]", post["faq_pairs"])
