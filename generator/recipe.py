"""
현지언니 '오늘의 집밥 레시피' 생성기.
content.py 와 동일한 출력 형식({title, tags, body, table_str, faq_str, subheadings,
image_keywords})을 내도록 _parse_response 를 재사용한다. 표=재료/분량, 본문=만드는 법.
"""
import logging
import random
import time
from datetime import datetime, timezone, timedelta

from generator.content import _parse_response, _refine_draft, _IMAGE_MARKER, _gen_text

logger = logging.getLogger("recipe")

# 신혼·자취 집밥에 어울리는 메뉴 풀 (계절 태그) — 최근 올린 건 피해서 선택
DISHES = [
    ("에어프라이어 두부조림", "사계절"), ("계란말이", "사계절"), ("애호박전", "사계절"),
    ("김치볶음밥", "사계절"), ("된장찌개", "사계절"), ("제육볶음", "사계절"),
    ("어묵볶음", "사계절"), ("멸치볶음", "사계절"), ("콩나물무침", "사계절"),
    ("감자조림", "사계절"), ("감자채볶음", "사계절"), ("소시지야채볶음", "사계절"),
    ("스팸김치볶음밥", "사계절"), ("간장계란밥", "사계절"), ("참치마요덮밥", "사계절"),
    ("토마토 계란볶음", "사계절"), ("두부김치", "사계절"), ("어묵탕", "겨울"),
    ("김치찌개", "겨울"), ("부대찌개", "겨울"), ("떡국", "겨울"), ("동태찌개", "겨울"),
    ("콩나물국밥", "겨울"), ("미역국", "사계절"), ("북엇국", "사계절"),
    ("오이무침", "여름"), ("열무비빔밥", "여름"), ("냉국수", "여름"), ("가지볶음", "여름"),
    ("애호박된장국", "여름"), ("물냉면", "여름"), ("비빔국수", "여름"),
    ("버섯들깨볶음", "가을"), ("고등어무조림", "가을"), ("무생채", "가을"),
    ("배추전", "겨울"), ("시금치나물", "봄"), ("봄동겉절이", "봄"), ("달래장", "봄"),
    ("순두부찌개", "사계절"), ("닭볶음탕", "사계절"), ("불고기", "사계절"),
    ("카레라이스", "사계절"), ("오므라이스", "사계절"), ("잡채", "사계절"),
]


def _season() -> str:
    m = datetime.now(timezone(timedelta(hours=9))).month
    return {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
            6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}[m]


def pick_dish(recent: list[str] | None = None) -> str:
    """최근 올린 메뉴는 피하고, 제철 메뉴에 가중치를 둬 선택."""
    recent = set(recent or [])
    season = _season()
    pool = [d for d, s in DISHES if d not in recent]
    if not pool:
        pool = [d for d, _ in DISHES]
    # 제철(또는 사계절) 메뉴 우선
    seasonal = [d for d, s in DISHES if d not in recent and s in (season, "사계절")]
    chosen = random.choice(seasonal or pool)
    return chosen


_RECIPE_SYSTEM = """
너는 신혼 1년차 주부 '현지언니'다. 자취·신혼 살림에 맞는 쉬운 집밥 레시피를
네이버 블로그에 쓴다. 친근한 까꿍언니 톤이지만, 레시피 정보는 정확하고 따라하기 쉽게.

[톤·문체]
- "~했어요/~더라고요/~거든요" 다정한 반말 섞인 존댓말. 과한 이모지·감탄사 금지.
- 첫 문장에 "안녕하세요", "오늘은 ~", "혹시 ~신가요", "솔직히 저도" 절대 금지(인삿말·공식 도입부 = 저품질 신호). 바로 본론/장면/계절감으로 시작.
- 실제 해먹어 본 사람처럼 구체적으로 (불 세기, 시간, 팁, 실패 포인트).
- AI틱 표현 금지: 이로써/이처럼/뿐만 아니라/마무리로/정리하자면, 별표·해시태그·마크다운 금지.

[글 구조 — 마커 정확히 지킬 것]
TITLE: {요리명 포함 + | + 후킹표현, 15~30자} (예: "에어프라이어 두부조림 | 자취생 10분 반찬")
TAGS: 쉼표로 8~12개 (요리명/집밥/자취요리/간단레시피/반찬 등)
IMAGE_KEYWORDS: 쉼표로 5개 영문 검색어 (완성요리/재료/조리과정 — 예: korean home food,tofu dish,cooking pan,fresh vegetables,korean side dish)
---
(여기부터 본문)
[사진1]
도입 2~3줄: 이 요리를 왜/언제 해먹는지, 어떤 점이 좋은지 (장면·계절감 자연스럽게)

[소제목] 재료 (몇 인분인지 명시)
[표시작]
구분 | 재료 | 분량
주재료 | 재료1 | 분량
주재료 | 재료2 | 분량
양념 | 양념1 | 분량
[표끝]
[사진2]
재료 관련 한두 줄 팁 (대체 가능한 재료, 손질 팁)

[소제목] 만드는 법
1. 첫 단계 (구체적으로: 불 세기/시간)
[사진3]
2. 다음 단계
3. 다음 단계
[사진4]
4. 다음 단계
5. 완성 단계

[소제목] 현지언니 꿀팁
실패하지 않는 포인트 2~3개, 보관법, 곁들이면 좋은 것 등 (3~5줄)
[사진5]

[FAQ시작]
Q: (이 요리 관련 실제 궁금증)
A: (현지언니 경험 기반 답)
Q: ...
A: ...
[FAQ끝]

[규칙]
- 본문(이미지마커 제외) 1500자 이상.
- 분량·시간·불세기는 현실적이고 정확하게. 위험하거나 틀린 조리법 금지.
- [사진1]~[사진5] 정확히 5개. 표는 재료/분량으로 [표시작]...[표끝] 1개.
- 재료표는 ★정확히 3열★ (구분 | 재료 | 분량). 구분은 '주재료/부재료/양념' 중 하나. 머리글 포함 9행 이내로 핵심 재료만.
- 소제목은 [소제목] 마커로 시작하는 한 줄. 이모지·기호 금지.
- 한국어만.
""".strip()


def generate_recipe(api_key: str, dish: str | None = None, recent: list[str] | None = None) -> dict | None:
    """레시피 글 생성. 반환: content.generate_post 와 동일 형식 + dish 키."""
    dish = dish or pick_dish(recent)
    season = _season()
    user_msg = (
        f"오늘 만들 요리: {dish}\n현재 계절: {season} (계절감 자연스럽게, 억지로 넣지 마)\n\n"
        f"위 요리의 현지언니 집밥 레시피 글을 구조 그대로 작성해줘. "
        f"재료는 [표시작]...[표끝] 표로, 만드는 법은 번호 단계로, 꿀팁과 FAQ 포함. "
        f"[사진1]~[사진5] 5개와 IMAGE_KEYWORDS 5개 반드시 포함."
    )
    waits = [15, 40, 90]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, _RECIPE_SYSTEM, 8192, 0.85)
            if not raw:
                logger.error(f"Gemini 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if parsed:
                body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
                logger.info(
                    f"레시피 생성 완료: {dish} / {parsed.get('title')!r} "
                    f"(본문 {body_len}자, 표:{'O' if parsed.get('table_str') else 'X'}, "
                    f"FAQ:{'O' if parsed.get('faq_str') else 'X'}, "
                    f"이미지키워드 {len(parsed.get('image_keywords', []))}개)"
                )
                if body_len < 400:
                    logger.warning(f"본문 너무 짧음 ({body_len}자) — 재생성")
                    continue
                refined_raw = _refine_draft(raw, api_key, min_photos=5)
                if refined_raw != raw:
                    rp = _parse_response(refined_raw)
                    if rp and len(_IMAGE_MARKER.sub("", rp.get("body", ""))) >= 400:
                        rp["dish"] = dish
                        logger.info("퇴고 적용")
                        return rp
                parsed["dish"] = dish
                return parsed
        except Exception as e:
            logger.error(f"레시피 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])
    return None


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    r = generate_recipe(os.environ.get("GOOGLE_API_KEY", ""))
    if r:
        print("제목:", r["title"])
        print("표:\n", r.get("table_str"))
        print("본문:\n", r["body"][:600])
