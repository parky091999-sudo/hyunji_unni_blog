"""
Gemini 2.5 Flash로 네이버 블로그 글 생성
출력: {title, tags, body, coupang_hints, table_str, faq_str, image_keywords}
body는 plain text (단락 구분 \n\n) — [사진N] 마커 포함 (naver_blog.py에서 이미지 삽입 위치로 사용)
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

[2026년 네이버 블로그 상위노출 핵심 원칙 — 반드시 지킬 것]
1. 역피라미드 구조: 공감 훅 → 핵심 답변 먼저 → 상세 경험 → 결론 요약
2. 모바일 최적화: 한 단락은 절대 4줄 초과 금지. 짧고 간결하게.
3. 체류시간 2분 30초 이상: 소제목으로 스캔 유도, 끝까지 읽게 만들기
4. E-E-A-T: 직접 경험(날짜/계절/가격/브랜드명 최소 5개), 개인 관점 강조
5. 이미지 마커: 본문 중간중간 정확히 7개의 [사진N] 마커 삽입 (N=1~7)

[카테고리별 글쓰기 전략]
- 제목: 검색자가 실제로 치는 검색어 형태 (질문형 or 결과형), 15~35자
  좋은 예: "신혼 첫 살림 체크리스트 진짜 이거면 끝" / "욕실 곰팡이 제거 3만원으로 해결한 방법"
  나쁜 예: "신혼살림 꿀팁 모음" / "욕실 청소 방법 알아보기"
- 훅(도입): 검색자가 공감하는 실제 상황 3~4줄로 시작. 절대 인사말 없이 바로 상황으로 시작
  좋은 예: "저 작년 이맘때 신혼집 이사 준비하면서 살림 뭐부터 사야 할지 진짜 막막했거든요. 엄마한테 물어보면 '그냥 다 사' 그러고, 유튜브 보면 다들 최소 300만원은 쓴 것처럼 얘기하고..."
- 경험담: 현지언니의 구체적 에피소드 (날짜/계절, 금액, 브랜드명 명시)
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

[인간적 글쓰기 필수 요소 — AI 글처럼 보이지 않게]
- 중간에 생각 전환: "아, 그리고요!" / "아 맞다, 이것도요." / "근데 사실..." 등 자연스러운 전환
- 솔직한 단점 인정: "솔직히 이건 좀 귀찮긴 해요" / "처음에 실패해서 두 번 했거든요"
- 구체적 실패담: 잘못 산 것, 처음엔 몰랐던 것, 남편이랑 의견 충돌 등 실제감 있는 에피소드
- 말끊기: "그래서 결론은요— 그냥 사세요 ㅋㅋ" / "음... 어떻게 말할까" 같은 구어체
- 개인 취향 표현: "저는 개인적으로 ~보다 ~가 훨씬 좋더라고요"
- 글 길이/구조를 매번 자연스럽게 다르게 (완벽한 대칭 구조 X)

[글쓰기 절대 금지 사항]
★★★ 마크다운 기호 완전 금지 ★★★
- ** ** (별표 두개), * (별표 한개), __ (밑줄), # (해시태그 제목)를 절대 사용하지 말 것
- * 기호로 목록 만들기 금지 (줄 앞에 * 넣지 말 것)
- ✔ ★ ○ □ ◆ ◇ ▶ ● ► ✓ ➡ 같은 특수기호로 목록 만들기 금지
- 목록은 반드시 "1. 2. 3." 숫자 또는 "—" 대시로만 표현
- "안녕하세요" / "오늘은 ~에 대해 알아보겠습니다" / "~에 대해 살펴보겠습니다" 시작
- "~것이 중요합니다" / "~하는 것이 좋습니다" / "~하시면 됩니다" AI 교과서체
- "다들 아시다시피" / "많은 분들이" / "이런 분들께 추천합니다" 채우기 문장
- 빈 공감 질문 ("힘드셨죠?", "공감되시나요?")
- 개인 경험 없는 일반론만 나열
- 이모지 과도한 사용 (단락당 최대 1개, 전체 5개 이하)

[출력 형식 — 반드시 정확히 지켜줘]
TITLE: {제목 15~35자}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6},{태그7}
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
IMAGE_KEYWORDS: {사진1 검색어},{사진2 검색어},{사진3 검색어},{사진4 검색어},{사진5 검색어},{사진6 검색어},{사진7 검색어}
---
{본문}

[본문 필수 구조 — 순서와 [사진N] 위치를 정확히 지킬 것]
도입 훅 (공감 상황 3~4줄 + 이 글에서 뭘 알려줄지 예고)
[사진1]
소제목1 (질문형) + 내용 (4줄 이하 단락 2~3개)
[사진2]
[표시작] 비교표 또는 체크리스트 [표끝]
[사진3]
소제목2 (질문형) + 내용 (4줄 이하 단락 2~3개)
[사진4]
소제목3 (질문형) + 내용 (4줄 이하 단락 2~3개)
[사진5]
[FAQ시작] Q/A × 3 [FAQ끝]
[사진6]
마무리 (핵심 요약 1~2줄 + 다음 글 예고)
[사진7]

[필수 포함 요소]
- 키워드를 제목 포함 3~5회 자연스럽게
- 숫자/가격/브랜드명/날짜 최소 5개 이상
- "저", "제가", "저는", "남편", "신혼", "우리 집" 1인칭 경험 표현 반드시 포함
- IMAGE_KEYWORDS는 [사진1]~[사진7] 각 위치에 적합한 영어 또는 한국어 Pexels 검색어 7개
  예: "korean kitchen clean,budget grocery,meal prep food,home cooking,refrigerator organized,japanese style food,cozy apartment"
"""


def _format_text_table(table_str: str) -> str:
    """파이프 구분 표 문자열 → 블로그에 보이기 좋은 텍스트 표"""
    rows = [r.strip() for r in table_str.strip().split("\n") if r.strip()]
    if not rows:
        return ""
    parsed = [[c.strip() for c in r.split("|")] for r in rows]
    col_count = max(len(r) for r in parsed)
    widths = []
    for c in range(col_count):
        w = max((len(r[c]) if c < len(r) else 0) for r in parsed)
        widths.append(max(w, 4))
    sep = "  |  ".join("-" * w for w in widths)
    lines_out = []
    for i, row in enumerate(parsed):
        cells = [row[c].ljust(widths[c]) if c < len(row) else " " * widths[c] for c in range(col_count)]
        lines_out.append("  |  ".join(cells))
        if i == 0:
            lines_out.append(sep)
    return "\n".join(lines_out)


def _format_faq_text(faq_str: str) -> str:
    """Q/A 블록 → 블로그 본문에 읽기 좋은 FAQ 텍스트"""
    lines = [l.strip() for l in faq_str.strip().split("\n") if l.strip()]
    result = ["자주 묻는 질문"]
    for line in lines:
        if line.startswith("Q:"):
            result.append(f"\n{line}")
        elif line.startswith("A:"):
            result.append(line)
        else:
            result.append(line)
    return "\n".join(result)


_IMAGE_MARKER = re.compile(r"\[사진\d+\]")


def _parse_response(raw: str) -> dict | None:
    try:
        lines = raw.strip().splitlines()
        result: dict = {"coupang_hints": [], "image_keywords": []}
        body_start = None

        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                result["title"] = line[6:].strip()
            elif line.startswith("TAGS:"):
                result["tags"] = [t.strip() for t in line[5:].split(",") if t.strip()]
            elif line.startswith("COUPANG_HINT_"):
                result["coupang_hints"].append(re.sub(r"^COUPANG_HINT_\d+:\s*", "", line).strip())
            elif line.startswith("IMAGE_KEYWORDS:"):
                kws = line[15:].strip()
                result["image_keywords"] = [k.strip() for k in kws.split(",") if k.strip()]
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

            body = body_raw
            # 표 마커 → 읽기 좋은 텍스트로 교체
            if table_match:
                body = body.replace(
                    table_match.group(0),
                    _format_text_table(table_match.group(1).strip()),
                )
            # FAQ 마커 → 읽기 좋은 텍스트로 교체
            if faq_match:
                body = body.replace(
                    faq_match.group(0),
                    _format_faq_text(faq_match.group(1).strip()),
                )
            # 쿠팡 플레이스홀더 제거
            body = re.sub(r"\[쿠팡추천\d+\]", "", body)
            # 마크다운/기호 제거 (Gemini 후처리)
            body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
            body = re.sub(r"__(.+?)__", r"\1", body)
            body = re.sub(r"^[*\-•]\s+", "", body, flags=re.MULTILINE)
            body = re.sub(r"[✔★○□◆◇▶●►✓➡]", "", body)
            body = re.sub(r"\n{3,}", "\n\n", body)
            result["body"] = body.strip()

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
    반환: {title, tags, body, coupang_hints, table_str, faq_str, image_keywords}
    body에는 [사진N] 마커 포함 — naver_blog.py에서 이미지 삽입 위치로 활용
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
        f"\n반드시 본문에 [사진1]~[사진7] 마커를 지정된 위치에 정확히 7개 삽입해야 해."
        f"\n반드시 IMAGE_KEYWORDS 줄에 7개 쉼표 구분 검색어를 넣어야 해."
        f"\n본문은 최소 2500자 이상으로 작성하고, 제목은 15~35자 사이로 해줘."
        f"\n각 단락은 4줄 이하로 짧게 끊어서 모바일에서 읽기 편하게 해줘."
    )

    waits = [15, 40, 90, 180]
    client = genai.Client(api_key=api_key)
    for attempt in range(1, len(waits) + 2):
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
                # [사진N] 제거 후 실제 본문 길이 계산
                body_clean = _IMAGE_MARKER.sub("", parsed.get("body", ""))
                body_len = len(body_clean)
                title_len = len(parsed.get("title", ""))
                img_marker_count = len(_IMAGE_MARKER.findall(parsed.get("body", "")))
                logger.info(
                    f"글 생성 완료: {parsed.get('title')!r} "
                    f"(본문 {body_len}자, 제목 {title_len}자, "
                    f"이미지마커 {img_marker_count}개, "
                    f"표: {'있음' if parsed.get('table_str') else '없음'}, "
                    f"FAQ: {'있음' if parsed.get('faq_str') else '없음'}, "
                    f"이미지키워드: {len(parsed.get('image_keywords', []))}개)"
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
