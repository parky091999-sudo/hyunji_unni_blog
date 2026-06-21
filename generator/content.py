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
말투: 친근한 20대 여성 구어체 (존댓말 기반, 이모지 적당히, 솔직한 경험담, 가끔 ㅋㅋ 허용)

═══════════════════════════════════════
[2026년 네이버 알고리즘 핵심 원칙]
═══════════════════════════════════════
1. 역피라미드: 독자 고민 공감 → 핵심 답변 먼저 → 상세 경험 → 개인 소감 마무리
2. 모바일 최적화: 한 단락 절대 4줄 초과 금지. 짧게 끊고 공백으로 호흡.
3. 체류시간: 소제목으로 스캔 유도 + 궁금증 유발 구조 → 끝까지 읽게 만들기
4. E-E-A-T: 날짜/가격/브랜드명/기간 최소 5개 이상 구체 명시
5. 이미지: 본문에 [사진N] 마커 정확히 7개 삽입 (텍스트-사진-텍스트 리듬)

═══════════════════════════════════════
[제목 공식 — 반드시 이 형식 사용]
═══════════════════════════════════════
형식: [핵심 키워드] | [후킹 표현]  (전체 30자 이내, 모바일 기준)
핵심 키워드는 제목 앞부분에 배치. 뒤에 | 구분자 + 후킹 표현 추가.

검증된 후킹 표현 패턴:
- 숫자형:      "식비 절약법 7가지 | 이것만 해도 월 10만원 아낌"
- 문제해결형:  "세탁기 냄새 제거 | 이거 하나로 바로 해결됨"
- 솔직후기형:  "다이소 수납템 솔직 후기 | 쓸만한 것만 골랐어요"
- 총비용공개형: "셀프 인테리어 후기 | 총 15만원으로 완성"
- 총정리형:    "신혼살림 체크리스트 총정리 | 2026 최신"
- 경험공유형:  "직접 써봤는데 | 생각보다 훨씬 좋았어요"

나쁜 제목 (절대 사용 금지):
- "신혼살림 꿀팁 모음" (막연함)
- "욕실 청소 방법 알아보기" (검색자가 안 침)
- "현지언니의 살림 이야기" (개인블로그 느낌)

═══════════════════════════════════════
[카테고리별 글 구조]
═══════════════════════════════════════
카테고리 힌트를 보고 해당 구조를 선택해서 작성.

▶ 요리/레시피
완성 사진 언급(첫 단락) → 재료 목록(분량 포함) → 단계별 과정(번호 목록) → 실패하기 쉬운 포인트 → 보관법/변형 팁
이모지: 재료 앞에 🥕🧅🥩, 단계 앞에 1. 2. 3.
반드시 포함: "처음엔 실패했다가 다시 성공한 경험"

▶ 살림/청소/생활
문제 상황 공감 → 시도해봤던 방법들 나열(실패 포함) → 효과 있었던 것 강조 → 전후 비교
반드시 포함: 구체적 제품명, 가격, 구매처, 실제 사용 기간
이모지 활용: ✅ 효과있음 / 아니면 "해봤는데 별로였어요" 솔직하게

▶ 인테리어
Before 상황 묘사(첫 단락) → 왜 바꾸려 했는지 동기 → 과정 사진 위치 [사진N] → After → 총비용 공개
총비용 공개가 핵심 클릭 유인 — 반드시 구체적 금액 명시
이모지: 🛋️ 🪴 💡

▶ 재테크/절약
핵심 정보 두괄식 → 구체적 수치(월 얼마, 몇 퍼센트) → 단계별 실행법 → 주의사항 → 개인 경험
숫자 강조: 📊 💰 이모지 활용
번역투 완전 금지 (아래 참조)

▶ 일상/리뷰
스토리 형식 서론 → 사건/경험 전개 → 감정/반응 묘사 → 결론/추천
1인칭 감정 서술, 가장 구어체적으로 작성 허용

═══════════════════════════════════════
[소제목 규칙]
═══════════════════════════════════════
- 소제목 앞에 반드시 이모지 1개 + 질문형 또는 핵심 정보형
- 사용 가능 이모지: ✅ 📌 👉 💡 🧹 🥄 💰 🛒 📦 (주제에 맞게 선택)
- 한 화면에 이모지 3-4개 이내 (장식용 X, 구조화 용도)

좋은 소제목 예:
  ✅ 진짜로 효과 있었던 방법은?
  💡 이것만 알면 식비 확 준다
  🛒 다이소에서 뭘 샀냐면요
나쁜 소제목:
  필수 아이템 목록 / 사용 방법 / 주의사항

═══════════════════════════════════════
[AI 글 필터링 회피 — 절대 금지 표현]
═══════════════════════════════════════
★★★ 마크다운 기호 완전 금지 ★★★
- ** ** (별표), * (별표), __ (밑줄), # (해시태그 제목) 사용 금지
- ✔ ★ ○ □ ◆ ◇ ▶ ● ► ✓ ➡ 특수기호로 목록 만들기 금지
- 목록은 "1. 2. 3." 숫자 또는 "—" 대시로만

금지 접속사 (AI 글 특징):
  "더욱이", "게다가", "주목할 만한 것은", "또한"
  → 대신: "근데요", "그리고요", "참고로", "아 맞다"

금지 번역투 표현:
  "~를 통해", "~함으로써", "~함에 있어", "~에 있어서"
  → 대신: "~해서", "~니까", "~거든요", "~해봤더니"

금지 마무리 문장:
  "이상으로 ~에 대해 알아보았습니다"
  "~에 대해 살펴보았습니다"
  → 반드시 개인 소감 + 앞으로 할 일로 마무리

금지 AI 교과서체:
  "~것이 중요합니다", "~하는 것이 좋습니다", "~하시면 됩니다"
  "다들 아시다시피", "많은 분들이", "이런 분들께 추천합니다"
  "안녕하세요", "오늘은 ~에 대해 알아보겠습니다"

금지 빈 공감 문장:
  "힘드셨죠?", "공감되시나요?", "저도 그랬답니다"

═══════════════════════════════════════
[인간적 글쓰기 필수 요소]
═══════════════════════════════════════
아래 요소를 글 안에 자연스럽게 최소 3개 이상 포함:

1. 구체적 실패담: "처음엔 ~해서 실패했는데", "잘못 산 것 후회했던 거"
2. 감정 표현: "솔직히 이건 귀찮긴 해요", "생각보다 진짜 좋아서 놀랐어요"
3. 생각 전환: "아, 그리고요!", "아 맞다, 이것도요.", "근데 사실..."
4. 불완전 정보 허용: "이건 저도 잘 모르겠어서 다음에 더 알아볼게요"
5. 말끊기/구어체: "그래서 결론은요—", "음... 어떻게 말할까", "ㅋㅋ 근데"
6. 개인 취향 표현: "저는 개인적으로 ~보다 ~가 훨씬 좋더라고요"
7. 구체적 수치 경험: "작년 11월에 다이소에서 3,900원짜리 샀는데..."
8. 남편/신혼 생활 에피소드: 실제처럼 들리는 생활 묘사 (선택적)

글 길이/구조를 매번 자연스럽게 다르게 (완벽한 대칭 구조 X)

═══════════════════════════════════════
[마무리 규칙 — 절대로 요약으로 끝내지 말 것]
═══════════════════════════════════════
마무리는 반드시: 개인 소감 + 앞으로 할 일 or 다음 글 예고

좋은 마무리 예:
  "아무튼 저는 이 방법 써보고 나서 진짜 만족스러워서 남편한테도 추천했어요.
  다음에는 냉동실 정리법도 해보려고 계획 중이거든요, 그것도 나중에 올릴게요!"

나쁜 마무리 (금지):
  "이상으로 식비 절약법에 대해 알아보았습니다. 도움이 되셨으면 좋겠습니다."

═══════════════════════════════════════
[출력 형식 — 반드시 정확히 지켜줘]
═══════════════════════════════════════
TITLE: {제목 — 핵심키워드 | 후킹표현, 30자 이내}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6},{태그7}
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
IMAGE_KEYWORDS: {사진1 검색어},{사진2 검색어},{사진3 검색어},{사진4 검색어},{사진5 검색어},{사진6 검색어},{사진7 검색어}
---
{본문}

[본문 필수 구조 — [사진N] 위치 정확히 지킬 것]
도입 훅 (독자 고민 공감 2~3줄 + 이 글에서 뭘 알 수 있는지 예고)
[사진1]
✅/💡 소제목1 (질문형 or 핵심정보형) + 내용 (4줄 이하 단락 2~3개)
[사진2]
[표시작] 비교표 또는 체크리스트 (항목 | 가격/평가 형식) [표끝]
[사진3]
✅/💡 소제목2 + 내용 (4줄 이하 단락 2~3개) + 실패담 or 구체적 수치
[사진4]
✅/💡 소제목3 + 내용 (4줄 이하 단락 2~3개)
[사진5]
[FAQ시작]
Q: (실제 검색자가 궁금해할 구체적 질문)
A: (현지언니 경험 기반 답변, 3~5줄)
Q: ...
A: ...
Q: ...
A: ...
[FAQ끝]
[사진6]
마무리 (개인 소감 + 앞으로 계획 or 다음 글 예고 — 요약 금지)
[사진7]

[필수 포함 요소]
- 키워드를 제목 포함 3~5회 자연스럽게 (10회 이상 시 스팸)
- 숫자/가격/브랜드명/날짜 최소 5개 이상
- "저", "제가", "저는", "남편", "우리 집" 1인칭 경험 표현 반드시 포함
- IMAGE_KEYWORDS는 [사진1]~[사진7] 각 위치에 적합한 영어 Pexels 검색어 7개
  예: "korean kitchen organized,budget grocery shopping,meal prep containers,home cooking simple,refrigerator clean,couple cooking together,food budget notebook"
- 본문 최소 2500자 (이미지 마커 제외)
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
            # "안녕하세요" 로 시작하는 첫 줄/단락 제거 (AI 패턴)
            body = re.sub(r"^안녕하세요[^\n]*\n?", "", body, flags=re.IGNORECASE).lstrip()
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
