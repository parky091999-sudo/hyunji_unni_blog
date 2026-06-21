"""
Gemini 2.5 Flash로 네이버 블로그 글 생성
출력: {title, tags, body, coupang_hints, table_str, faq_str}
body는 plain text (단락 구분 \n\n) — Playwright 타이핑용
"""
import logging
import re
import time

from google import genai
from google.genai import types as gtypes

logger = logging.getLogger(__name__)

_SYSTEM = """\
너는 네이버 블로그 "현지언니" 계정의 글을 쓰는 작가야.

[페르소나]
이름: 현지언니 (본명 박현지)
나이: 28세, 결혼 2년차 신혼주부
사는 곳: 경기도 수원 신축 24평 아파트
남편: 회사원, 집안일 50:50 분담
특기: 다이소/이케아 살림 꿀팁, 자취 → 신혼 살림 노하우 총정리
말투: 친근한 20대 여성 (존댓말, 이모지 적당히, 솔직한 경험담)

[카테고리별 글쓰기 전략]
- 제목: 검색자가 실제로 치는 검색어 형태 (질문형 or 결과형), 15~35자
  좋은 예: "신혼 첫 살림 체크리스트 진짜 이거면 끝" / "욕실 곰팡이 제거 3만원으로 해결한 방법"
  나쁜 예: "신혼살림 꿀팁 모음" / "욕실 청소 방법 알아보기"
- 훅(도입): 검색자가 공감하는 실제 상황 3~5줄로 시작. 절대 인사말 없이 바로 상황으로 시작
  좋은 예: "저 작년 이맘때 신혼집 이사 준비하면서 살림 뭐부터 사야 할지 진짜 막막했거든요. 엄마한테 물어보면 '그냥 다 사' 그러고, 유튜브 보면 다들 최소 300만원은 쓴 것처럼 얘기하고..."
- 경험담: 현지언니의 구체적 에피소드 포함 (날짜/계절, 금액, 브랜드명 명시)
  예: "작년 10월에 다이소에서 3,000원짜리 배수구 거름망 샀는데..." / "남편이 주말에 세탁기 청소 처음 해봤는데 30분 만에..."
- 본론: 소제목별 실용 정보. 소제목은 반드시 질문형으로 작성
  좋은 소제목: "뭐부터 사야 할까?" / "실제로 써봤더니 어때?" / "얼마나 절약됐을까?"
  나쁜 소제목: "필수 아이템 목록" / "사용 방법" / "주의사항"
- 비교/체크리스트: 반드시 아래 마커로 표 포함
  [표시작]
  (표 내용: 항목 | 가격 | 평점 형식이나 비교 형식)
  [표끝]
- FAQ: 반드시 아래 마커로 3문3답 포함
  [FAQ시작]
  Q: (실제 검색자가 궁금해할 질문)
  A: (현지언니의 경험 기반 답변, 3~5줄)
  Q: ...
  A: ...
  Q: ...
  A: ...
  [FAQ끝]
- 마무리: 다음 글 예고 포함. "다음에는 ~도 정리해볼게요!" 스타일

[글쓰기 절대 금지 사항]
- "안녕하세요" / "오늘은 ~에 대해 알아보겠습니다" / "~에 대해 살펴보겠습니다" 시작
- **굵게** / __밑줄__ / ✔ ★ ○ □ 같은 마크다운 기호로 목록 만들기
- "~것이 중요합니다" / "~하는 것이 좋습니다" / "~하시면 됩니다" AI 교과서체
- "다들 아시다시피" / "많은 분들이" / "이런 분들께 추천합니다" 채우기 문장
- 빈 공감 질문 ("힘드셨죠?", "공감되시나요?")
- 개인 경험 없는 일반론만 나열
- 이모지 과도한 사용 (단락당 최대 1개)

[출력 형식 — 반드시 정확히 지켜줘]
TITLE: {제목 15~35자}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6},{태그7}
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
---
{본문 — plain text, 2000자 이상 3500자 이하}

[본문 구성 필수 요소]
1. 도입부 (공감 상황 묘사, 3~5줄)
2. 소제목1 (질문형) + 내용
3. [표시작] ... [표끝]
4. 소제목2 (질문형) + 내용
5. 소제목3 (질문형) + 내용
6. [FAQ시작] Q/A × 3 [FAQ끝]
7. 마무리 (다음 글 예고 포함)

본문에 키워드를 3~5회 자연스럽게 포함할 것.
숫자/가격/브랜드명/날짜를 최소 5개 이상 포함할 것.
"저", "제가", "저는", "남편", "신혼", "우리 집" 같은 1인칭 경험 표현 반드시 포함.
"""


def _parse_response(raw: str) -> dict | None:
    try:
        lines = raw.strip().splitlines()
        result: dict = {"coupang_hints": []}
        body_start = None

        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                result["title"] = line[6:].strip()
            elif line.startswith("TAGS:"):
                result["tags"] = [t.strip() for t in line[5:].split(",") if t.strip()]
            elif line.startswith("COUPANG_HINT_"):
                result["coupang_hints"].append(re.sub(r"^COUPANG_HINT_\d+:\s*", "", line).strip())
            elif line.strip() == "---":
                body_start = i + 1
                break

        if body_start is None:
            for i, line in enumerate(lines):
                if line.strip() == "" and i > 3:
                    body_start = i + 1
                    break

        if body_start is not None:
            body_raw = "\n".join(lines[body_start:]).strip()

            # 표 마커 추출
            table_match = re.search(r"\[표시작\](.*?)\[표끝\]", body_raw, re.DOTALL)
            result["table_str"] = table_match.group(1).strip() if table_match else ""

            # FAQ 마커 추출
            faq_match = re.search(r"\[FAQ시작\](.*?)\[FAQ끝\]", body_raw, re.DOTALL)
            result["faq_str"] = faq_match.group(1).strip() if faq_match else ""

            # [쿠팡추천N] 플레이스홀더 제거
            body = re.sub(r"\[쿠팡추천\d+\]", "", body_raw)
            result["body"] = body

        if "title" not in result or "body" not in result:
            logger.warning("파싱 실패")
            return None

        result.setdefault("tags", [])
        return result
    except Exception as e:
        logger.error(f"파싱 오류: {e}")
        return None


def generate_post(
    keyword: str,
    api_key: str,
    trending: list[str] | None = None,
    category: str = "",
) -> dict | None:
    """
    keyword: 오늘 포스팅 키워드
    category: 카테고리 이름 (글쓰기 방향 힌트로 활용)
    반환: {title, tags, body, coupang_hints, table_str, faq_str}
    """
    trend_note = ""
    if trending:
        trend_note = f"\n참고 트렌딩 (자연스럽게 연결되면 살짝 언급, 억지로 넣지 말 것): {', '.join(trending[:3])}"

    category_note = f"\n카테고리: {category}" if category else ""

    user_msg = (
        f"오늘 포스팅 키워드: {keyword}"
        f"{category_note}"
        f"{trend_note}"
        f"\n\n위 키워드로 현지언니 블로그 글을 작성해줘."
        f"\n반드시 [표시작]...[표끝] 과 [FAQ시작]...[FAQ끝] 마커를 포함해야 해."
        f"\n본문은 최소 2000자 이상으로 작성하고, 제목은 15~35자 사이로 해줘."
    )

    waits = [15, 40, 90, 180]
    client = genai.Client(api_key=api_key)
    for attempt in range(1, len(waits) + 2):  # 최대 5회
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_msg,
                config=gtypes.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    max_output_tokens=8192,
                    temperature=0.9,
                ),
            )
            raw = (resp.text or "").strip()
            if not raw:
                logger.error(f"Gemini 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if parsed:
                body_len = len(parsed.get("body", ""))
                title_len = len(parsed.get("title", ""))
                logger.info(
                    f"글 생성 완료: {parsed.get('title')!r} "
                    f"(본문 {body_len}자, 제목 {title_len}자, "
                    f"표: {'있음' if parsed.get('table_str') else '없음'}, "
                    f"FAQ: {'있음' if parsed.get('faq_str') else '없음'})"
                )
                if body_len < 500:
                    logger.warning(f"본문 너무 짧음 ({body_len}자) — 재생성 시도")
                    continue
                return parsed
        except Exception as e:
            logger.error(f"Gemini 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)
    return None
