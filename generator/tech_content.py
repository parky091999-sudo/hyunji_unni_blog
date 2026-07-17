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
    # AI 소비자 서비스 (카테고리별 하루 1편 전환으로 AI·IT 시드 보강, 2026-07-17)
    "챗GPT 신기능", "AI 스마트폰", "제미나이", "AI 노트북",
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
    "챗GPT 신기능": "AI·IT", "AI 스마트폰": "AI·IT", "제미나이": "AI·IT", "AI 노트북": "AI·IT",
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
이해하도록 쉽고 정확하게 풀어준다. 친근하지만 팩트에 엄격하다.

[글쓰기 태도 — ★재미없으면 실패다. 정보 나열은 아무도 안 읽는다]
· 독자 관점이 먼저다. 이 소식에서 독자가 '진짜 궁금해할 것'과 '나한테 무슨 이득·손해인지'를
  중심으로 써라. 스펙·수치를 나열만 하지 말고 "그래서 이게 왜 좋은지/아쉬운지/나한테 뭔지"를
  꼭 해석해줘라.
· 도입부(리드)는 뻔한 배경설명 금지. 궁금증·의외성·손해회피("이거 모르면 손해") 중 하나로
  첫 두 줄에서 확 잡아라.
· ★문체를 섞어라. '~습니다'로 끝나는 문장을 3연속 이상 쓰지 마라. 짧은 단정("가격이 문제죠."),
  독자에게 던지는 질문("그럼 지금 사도 될까요?"), 대비("싸 보이지만, 함정이 있습니다") 를
  자연스럽게 섞어 리듬을 만들어라.
· 구체 장면·비유로 와닿게. 추상적 설명 대신 실제 사용 상황·숫자·비교로.
· 과장·낚시는 금지하되, 밋밋함도 금지. 팩트 위에서 흥미를 얹어라.

[절대 원칙]
0. ★독자에게 '존댓말(~습니다/~해요)'로 쓴다. 반말(~이야/~했어/~보여) 금지. 그리고 '현지언니'
   등 다른 블로그·사람·계정을 본문에 절대 언급하지 마라(이 블로그 독자는 모른다).
1. 아래 [최신 뉴스] 팩트에 있는 사실만 단정. 없는 스펙·가격·일정은 지어내지 마라.
2. 확정 안 된 소식은 반드시 "~로 알려졌다 / ~로 전망된다 / 유출됐다" 톤. 단정 금지.
3. 낡은 정보 금지 — 뉴스 날짜 기준 최신만. ★기준일 표기 문구("2026년 7월 기준" 등)는 쓰지 마라 — 불릿 끝에 잔재로 남아 글을 어색하게 만든다(2026-07-16 사용자 피드백).
4. 금지어: 안녕하세요/이처럼/이로써/혁신적인/탁월한/극대화/마크다운(**#)/이모지. ★HTML 태그(<div>,<b>,<span>,<br> 등) 절대 쓰지 마라 — 소제목은 반드시 [소제목] 마커만 사용.
5. 소제목 텍스트 맨 앞에 번호(1./①) 붙이지 마라 — 회색바+볼드로 구분됨.
6. 목록/장점/대상 나열의 모든 항목 줄은 반드시 '· '(가운뎃점+공백)로 시작. '라벨: 설명' 형태여도 앞에 · 필수. 단계 번호는 ①②③.
7. 단락은 2~3줄 이내. 한 문장 = 한 줄 지향(모바일 스캔형).
8. 2단 계층: 상위 분류는 [[분류명]] 볼드 라벨(글머리 · 없이 한 줄), 세부만 그 아래 · 불릿. 부모·자식 같은 글머리 금지.
9. ★초점 엄수: 오직 주어진 주제와 '직접' 관련된 사실만 써라. 무관한 다른 제품·행사·지역·기업 소식은 절대 섞지 마라(초점 흐려짐).
9-1. ★소제목 중 최소 2개에는 주제의 제품·기술명을 그대로 넣어라 — 소제목만 훑어도 무슨 글인지
   보여야 한다("쉽게 말하면 이런 겁니다"처럼 주제 없는 소제목만 나열 금지, 2026-07-16 사용자 피드백).
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
# 벤치마크(테크티노)식 공통 뼈대 — 대화체 훅 → 핵심요약 → 질문형 소제목(데이터·1인칭 해석) →
# 마무리 한마디 → 참여 유도 질문. 형식별로 소제목의 '각도'만 다르게.
_BENCH_OPEN = """[사진1]
(도입 2~3문단. ★대화체·실생활 훅으로 시작하라 — 예: "얼마 전 회사 동료와 ~ 얘기를 하다가 '정말 그럴까?' 싶어 찾아봤습니다." 처럼 독자가 '어 나도 궁금했는데' 하게. 그리고 이 글에서 무엇을 알게 될지 살짝 예고. 뻔한 배경설명·사전적 정의로 시작하지 마라.)

[소제목] 핵심 요약 3줄
· (이 글의 결론/핵심 숫자 1 — 구체 수치로)
· (핵심 2)
· (핵심 3)
"""
# ※목차 섹션은 제거(2026-07-16 사용자 피드백: 소제목 3~4개짜리 글에 목차는 군더더기)
_BENCH_CLOSE = """
[소제목] 총평
(전체를 아우르는 정리 2~3줄. 핵심을 다시 짚되 '그래서 독자는 어떻게 하면 되는지' 개인 인사이트 한 스푼. 앞 내용 단순 반복 금지.)

(마무리 한마디: 기억에 남는 한 줄로 여운을 줘라. 예: "좋은 폰은 스펙이 만들지만, 오래 쓰는 폰은 결국 관리가 만듭니다." 진부한 요약 금지.)

(★참여 유도 질문 1줄: 독자에게 의견을 물어 댓글을 유도하라. 예: "여러분이라면 성능을 먼저 보시나요, 가격을 먼저 보시나요?")
"""

_FMT_PROMPTS = {
    # ① 속보·루머 — 뉴스형. 홈피드 유입.
    "breaking": _COMMON_RULES + "\n[구조 — 속보/뉴스 분석형]\n" + _BENCH_OPEN + """
[소제목] 무슨 일이 벌어졌나
(유출·발표 내용을 숫자·팩트와 함께. '그래서 왜 화제인지' 해석까지. 출처 성격 명시.)

[소제목] 스펙·일정, 뭐가 달라지나
(핵심 팩트를 표로 — ★반드시 3열(항목|내용|의미), 각 셀 12자 이내, 빈칸 금지. '의미' 열엔 그 수치가 소비자에게 뭘 뜻하는지 짧게 해석해 넣어라.)
[표시작]
항목 | 내용 | 의미
칩셋 | ~ | ~
출시 예상 | ~ | ~
[표끝]

[소제목] 그래서 나한테 뭐가 좋아지나
(소비자 체감 영향·이전 세대/경쟁 제품 비교. "제가 보기엔~" 같은 1인칭 관점 한 스푼.)
""" + _BENCH_CLOSE,
    # ② 쉬운 해설 — 해설형(비유·개념).
    "explain": _COMMON_RULES + "\n[구조 — 쉬운 해설형]\n" + _BENCH_OPEN + """
[소제목] 이게 왜 어렵게 느껴질까
(독자가 헷갈리는 지점을 콕 집고, 핵심 개념을 결론부터 한 줄로.)

[소제목] 쉽게 말하면 이런 겁니다
(어려운 원리를 일상 비유로. 구체 장면으로 와닿게 3~4줄.)

[소제목] 그래서 나한테 좋은 건
(체감 변화·장점을 · 불릿으로. 각 항목에 구체 수치·예시와 '왜 좋은지' 해석.)
""" + _BENCH_CLOSE,
    # ③ 꿀템 큐레이터 — 리뷰/스펙형.
    "pick": _COMMON_RULES + "\n[구조 — 리뷰/스펙형]\n" + _BENCH_OPEN + """
[소제목] 어떤 제품이길래
(제품 성격·핵심 특징을 실제 스펙과 함께. '어떤 사람의 어떤 고민'을 풀어주는지 관점으로.)

[소제목] 스펙·가격 한눈에
(★반드시 3열(항목|스펙|한줄평), 각 셀 20자 이내, 빈칸 금지. '한줄평' 열엔 그 스펙이 좋은지/아쉬운지 짧게. 항목마다 행을 나눠라 — 한 셀에 여러 스펙 몰아넣기 금지.)
[표시작]
항목 | 스펙 | 한줄평
칩셋 | ~ | ~
RAM·저장 | ~ | ~
배터리 | ~ | ~
가격 | ~ | ~
[표끝]
(가격·스펙은 판매처 기준, 변동 가능 — 1줄)

[소제목] 좋은 점 vs 아쉬운 점
(· 불릿으로 장점과 단점을 솔직하게 균형 있게. 단점도 진짜로. 광고티 금지.)

[소제목] 이런 분께 추천
(구매 적합 대상을 · 불릿으로. 3~4개.)

[쇼핑추천]
""" + _BENCH_CLOSE,
    # ④ 비교·논란 — 비교형(표 중심).
    "compare": _COMMON_RULES + "\n[구조 — 비교/논란 분석형]\n" + _BENCH_OPEN + """
[소제목] 뭐가 쟁점이길래
(비교 포인트·논란을 양쪽 입장 균형 있게. 독자가 왜 이걸 고민하는지 짚어줘라.)

[소제목] 항목별로 비교해보면
(비교가 핵심이니 표를 충실히 — 3열(항목|A|B), 4~5개 행, 각 셀 15자 이내, 빈칸 금지. 표 아래 한 줄로 '표의 핵심 시사점' 해석.)
[표시작]
항목 | A | B
가격 | ~ | ~
성능 | ~ | ~
[표끝]

[소제목] 그래서 뭘 골라야 하나
(용도·예산별 결론을 · 불릿으로. "~라면 A, ~라면 B" 조건부로 명확하게.)
""" + _BENCH_CLOSE,
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
    # 기업 동정·B2B 보도자료 (2026-07-16 실측: 'SM벡셀 배터리팩솔루션팀 신설'이 '배터리' 가점으로
    # 통과 → 소비자 실익 없는 글. 조직·수주성 뉴스는 강한 감점)
    "신설", "출범", "조직", "본부", "사업부", "솔루션팀", "수주", "납품",
    "공급계약", "양산", "증설", "협력사", "자회사", "법인", "사옥", "공장",
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


def pick_tech_topic(days: int = 7, exclude: set | None = None,
                    exclude_headlines: set | None = None,
                    seeds: list | None = None) -> dict | None:
    """여러 시드의 최신 뉴스를 모아 '소비자 관심도' 최고 헤드라인을 글감으로 선정.
    학술/B2B/지역 뉴스는 감점으로 배제 → 트래픽 되는 소비자 주제로 편향.
    exclude_headlines: 최근 발행 헤드라인 — 후보에서 원천 제외(같은 글감 반복 발행 방지, 2026-07-16).
    seeds: 시드 부분집합(카테고리별 하루 1편 발행용, 2026-07-17) — 없으면 전체 TECH_SEEDS.
    반환: {seed, headline, news:[...]} — headline이 실제 글 주제.
    """
    exclude = exclude or set()
    exclude_headlines = exclude_headlines or set()
    seeds = [s for s in (seeds or TECH_SEEDS) if s not in exclude]
    random.shuffle(seeds)
    candidates = []  # (score, seed, news_item, news_list)
    for seed in seeds[:10]:
        news = _recent_tech_news(seed, days=days)
        for n in news:
            if n["title"] in exclude_headlines:
                continue
            candidates.append((_score_headline(n["title"]), seed, n, news))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_score, seed, item, news = candidates[0]
    if best_score <= 0:
        # 2026-07-16 사용자 피드백: 소비자 실익 없는 B2B성 주제로 억지 글을 쓰느니 스킵
        logger.warning(f"소비자 관심 주제 없음(최고점 {best_score}: {item['title'][:30]}) — 오늘 발행 스킵")
        return None
    logger.info(f"주제 선정: [{seed}] {item['title'][:40]} (점수 {best_score})")
    # 선정 헤드라인과 같은 시드의 뉴스만 맥락으로 전달(초점 유지).
    # 선정 기사를 news 맨 앞으로 → 대표 실사진(og:image)이 '헤드라인 기사'에서 우선 추출되어
    # 본문 주제와 무관한 다른 기사 사진이 대표로 붙던 문제 방지(2026-07-16: 태양광카메라 글에
    # 폰가격 배너가 붙던 실측).
    news_ordered = [item] + [n for n in news if n is not item]
    return {"seed": seed, "headline": item["title"], "news": news_ordered}


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
    base_user = news_block + (
        f"\n위 뉴스 중 가장 화제성 있는 '{topic['headline']}' 관련 내용을 중심으로 "
        f"'{fmt}' 형식의 테크 글을 작성해라.\n"
        "- ★독자가 이 소식에서 '진짜 궁금해할 것'과 '나한테 무슨 이득·손해인지'를 먼저 떠올리고, 그걸 축으로 써라. 정보 나열 금지, 스펙은 반드시 '왜 좋은지/아쉬운지'로 해석.\n"
        "- ★재미: 도입부는 궁금증·의외성·손해회피로 확 잡고, 문체를 섞어라('~습니다' 3연속 금지, 질문·짧은 단정·대비 활용). 밋밋한 설명체 금지.\n"
        "- ★본문 1,800~2,400자. 각 소제목 4~6줄로 충실히(빈약한 한두 줄 금지).\n"
        "- ★구체 팩트: 모델명·수치·가격대·경쟁/이전 세대 비교를 뉴스 팩트 범위에서. 없는 사실 창작 금지, 확정 안 된 건 '~로 알려졌다' 톤, 기준일 표기 필수.\n"
        "- 맨 위 [사진1]은 발행 스크립트가 뉴스 실사진을 자동으로 얹는 자리다. 마커는 [사진1] 하나만 두고, 도입부에서 '사진을 보면' 식으로 이미지를 설명하지 마라."
    )

    # ✔요약박스·FAQ 제거로 본문이 짧아지는 경향 → 목표 미달 시 '더 두껍게' 피드백을 주입해 재생성.
    # 하한(TECH_BODY_MIN)은 return None 방지용 안전망, 목표(TARGET)는 품질 유도용.
    TECH_BODY_TARGET = 1700
    extra = ""
    best = None
    best_len = 0
    waits = [10, 30]
    for attempt in range(1, len(waits) + 2):
        try:
            # 실시간성 강화: Google Search Grounding 활성화(뉴스 팩트 보강)
            raw = _gen_text(api_key, base_user + extra, system, 8192, 0.85, use_search=True)
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
                extra = (
                    f"\n\n[재작성 지시] 직전 원고가 {body_len}자로 너무 짧았다. 각 소제목 섹션을 4~6줄로 "
                    "늘리고 배경·이전 세대/경쟁 제품 비교·소비자 영향·구체 수치를 더 담아 전체 1,800자 "
                    "이상으로 다시 써라. 단, [최신 뉴스]에 없는 사실은 절대 지어내지 마라."
                )
                continue
            # 하한 통과 — 최장본 보관(마지막에 목표 미달이어도 최선본으로 발행)
            if body_len > best_len:
                best, best_len = parsed, body_len
            if body_len < TECH_BODY_TARGET and attempt <= len(waits):
                logger.info(f"본문 {body_len}자 — 목표({TECH_BODY_TARGET}자) 미달, 더 두껍게 재시도")
                extra = (
                    f"\n\n[재작성 지시] 직전 원고가 {body_len}자였다. 사실 왜곡·창작 없이 각 섹션의 "
                    "설명·맥락·비교를 더 풍부하게 늘려 1,800자 이상으로 다시 써라."
                )
                continue
            break  # 목표 도달 or 마지막 시도 — best 확정
        except Exception as e:
            logger.error(f"테크글 생성 실패 (시도 {attempt}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])

    if best is None:
        return None
    best["fmt"] = fmt
    best["seed"] = topic["seed"]
    best["image_strategy"] = FMT_IMAGE[fmt]
    logger.info(
        f"테크글 생성 완료 [{fmt}]: {best.get('title')!r} "
        f"(본문 {best_len}자, 표={bool(best.get('table_str'))}, "
        f"FAQ={bool(best.get('faq_str'))}, 요약={bool(best.get('summary_text'))})"
    )
    return best


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
