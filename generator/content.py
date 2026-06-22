"""
Gemini 2.5 Flash로 네이버 블로그 글 생성
출력: {title, tags, body, coupang_hints, table_str, faq_str, image_keywords}
body는 plain text (단락 구분 \n\n) — [사진N] 마커 포함 (naver_blog.py에서 이미지 삽입 위치로 사용)
"""
import logging
import random
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

금지 AI 단어/표현 (실생활에서 잘 안 쓰는 말 — 절대 금지):
  "이로써", "이처럼", "혁신적인", "효율적인", "극대화", "활용도",
  "다양한 ~를", "손쉽게", "탁월한", "최적의", "필수적인", "꼼꼼하게 살펴",
  "마련해 보세요", "추천드립니다", "선사합니다", "자리 잡았습니다"
  → 대신 일상 구어체로. ("진짜 좋더라", "이게 편해요", "이거 하나면 끝")

═══════════════════════════════════════
[이모지 정책 — AI 티 핵심]
═══════════════════════════════════════
- 이모지는 글 전체에서 0~2개만. 장식·구조용 이모지(✅ 💡 🛒 📌 👉 🧹 🥄 💰 📦)는 전부 금지.
- 소제목·목록 앞에 이모지 붙이지 마라 (가장 AI틱한 패턴).
- 꼭 쓰려면 감정 표현에 자연스럽게 1개 정도만 (예: "진짜 만족스러웠어요 ㅎㅎ").

═══════════════════════════════════════
[글 정체성 — 리뷰인지 정보글인지 분명히]
═══════════════════════════════════════
글이 '이것저것 짜깁기'처럼 보이지 않게, 하나의 명확한 정체성을 가져라.
- 제품 추천/리뷰 글이면 → 반드시 "리뷰" 톤: 직접 써본 솔직 총평 + 좋았던 점/아쉬운 점 + "이런 사람한테 추천/비추" 한 줄 결론을 명확히.
- 방법/팁 글이면 → 하나의 문제를 끝까지 해결하는 흐름(기승전결). 중간에 주제 이탈 금지.
- 한 글 = 한 주제. 관련 없는 정보 나열식 나열 금지 (짜깁기 방지).

═══════════════════════════════════════
[★최우선★ 도입부 공식 금지 — 매 글 완전히 다르게]
═══════════════════════════════════════
2026 네이버는 '첫 1~2단락이 다른 글과 똑같은 천편일률 도입부'를 AI/저품질의
가장 강한 신호로 본다. 아래 '공식 도입부'는 절대 쓰지 마라 (지금까지 반복한 금지 패턴):
  "혹시 ~하고 계신가요? / 아니면 저처럼 ~?"
  "솔직히 저도 처음엔 ~"
  "근데요, 몇 번의 시행착오 끝에 ~ 찾았지 뭐예요?"
  "오늘은 제가 ~ 알려드릴게요"
  "이 글 하나만 잘 읽어두시면 ~"
→ 위 뼈대를 순서만 바꾸거나 단어만 갈아끼우는 것도 금지. 매번 진짜로 다르게 시작하라.

도입부는 아래 스타일 중 하나로(또는 섞어) 자연스럽게 시작:
  A. 구체적 장면/시간 묘사 — "어제 저녁 8시, 싱크대 앞에서 또 한숨 쉬다가요."
  B. 의외의 숫자/사실 먼저 — "이거 하나 바꿨더니 한 달 전기세가 1만 2천원 줄었어요."
  C. 실패담 자백 — "저 이거 1년을 잘못된 방법으로 쓰고 있었더라고요. 진짜 어이없게."
  D. 결론부터(역두괄식) — "결론부터 말하면, 답은 다이소 2천원짜리였어요."
  E. 남편/생활 에피소드 — "남편이 '이거 왜 이래?' 묻는 순간 깨달았어요."
첫 문장에 '안녕하세요', '오늘은', '혹시 ~신가요'는 절대 금지.

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
도입부 (위 [도입부 공식 금지] 규칙대로 매번 다른 스타일로 2~4줄, 공식 도입부 절대 금지)
[사진1]
[소제목] 소제목1 (질문형 or 핵심정보형, 이모지 없이) + 내용 (4줄 이하 단락 2~3개)
[사진2]
[표시작] 비교표 또는 체크리스트 (항목 | 가격/평가 형식) [표끝]
[사진3]
[소제목] 소제목2 + 내용 (4줄 이하 단락 2~3개) + 실패담 or 구체적 수치
[사진4]
[소제목] 소제목3 + 내용 (4줄 이하 단락 2~3개)
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

[소제목 규칙]
- 모든 소제목은 줄 맨 앞에 [소제목] 마커를 붙이고 한 줄로 (예: "[소제목] 진짜 효과 있었던 방법은?")
- 소제목에 이모지/특수기호 절대 금지. 마커 뒤 텍스트만.
- 소제목은 4~5개. 본문과 명확히 구분되도록 짧게.

[표 규칙 — 진짜 표로 들어감]
- [표시작]과 [표끝] 사이는 각 줄을 " | "로 구분 (예: "제품 | 가격 | 한줄평")
- 첫 줄은 머리글(컬럼명), 2~4개 컬럼, 3~6개 행. 깔끔한 비교표 1개만.

[필수 포함 요소]
- 키워드를 제목 포함 3~5회 자연스럽게 (10회 이상 시 스팸)
- 숫자/가격/브랜드명/날짜 최소 5개 이상
- "저", "제가", "저는", "남편", "우리 집" 1인칭 경험 표현 반드시 포함
- IMAGE_KEYWORDS는 [사진1]~[사진7] 위치에 맞는 영어 Pexels 검색어 7개
  ★규칙: 글 내용과 직접 맞는 '구체적 사물/장면'만. 돈·비즈니스·외국풍 추상어 금지.
  (나쁜 예: "food budget notebook" → 미국 달러 사진 나옴 / "business success")
  (좋은 예: 살림글이면 "tidy kitchen shelf,storage basket,clean bathroom sink,folded laundry,korean home interior,kitchen utensils drawer,cozy apartment living room")
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
            # 장식용/구조용 AI 이모지 제거 (소제목 앞 ✅💡 등 — AI틱 핵심)
            body = re.sub(r"[✅💡🛒📌👉🧹🥄💰📦]\s*", "", body)
            # [소제목] 마커 정리 — 깔끔한 단독 줄로 (Phase2 포스터가 제목 스타일 적용)
            body = re.sub(r"^\[소제목\]\s*", "", body, flags=re.MULTILINE)
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


_REFINE_SYSTEM = """\
너는 블로그 글 퇴고 전문가야. '현지언니' 블로그 초안을 받아서, 형식은 그대로 두고
본문 문장만 더 사람이 쓴 것처럼 자연스럽게 고쳐줘.

[절대 그대로 유지 — 건드리지 마]
- 맨 위 TITLE: / TAGS: / COUPANG_HINT_*: / IMAGE_KEYWORDS: 줄과 값
- --- 구분선
- [사진1]~[사진7], [표시작]...[표끝], [FAQ시작]...[FAQ끝], [소제목] 마커 (위치·개수 그대로)
- 출력은 입력과 똑같은 형식 (위 마커가 전부 살아있어야 함)

[본문을 이렇게 고쳐라 — 12가지]
1. AI 단어 제거: 이로써/이처럼/혁신적인/효율적인/극대화/탁월한/최적의/필수적인/선사/마련해보세요 → 일상 구어체
2. 번역투 제거: ~를 통해/~함으로써/~에 있어서 → ~해서/~니까/~거든요
3. 교과서체 제거: ~것이 중요합니다/하는 게 좋습니다/하시면 됩니다 → 솔직한 경험담
4. 짜깁기 느낌 제거: 단락끼리 자연스럽게 이어지게, 반복·뜬금없는 주제 전환 정리
5. 정체성 강화: 리뷰글이면 솔직 총평 + 좋았던 점/아쉬운 점 + 추천대상 한 줄을 분명히
6. 1인칭 경험 강화: 막연한 일반론을 '내가 직접 ~했을 때' 구체담으로
7. 문장 리듬 다양화: 짧은 문장과 긴 문장 섞기 (전부 비슷한 길이 금지)
8. 디테일 또렷하게: 가격·날짜·브랜드·상황 구체화
9. 이모지 정리: 장식용 이모지(✅💡🛒📌👉 등) 전부 제거, 감정용 0~2개만
10. 도입부가 공식적이면(혹시~신가요/오늘은~알려드릴게요) 완전히 다른 방식으로 다시 써라
11. 마무리가 '~알아보았습니다/도움이 되셨으면'이면 개인 소감 + 다음 계획으로 바꿔라
12. 과장·광고 톤 빼고 솔직하게 (단점도 한 줄 인정)

길이는 유지하거나 살짝 늘려도 됨. 출력은 고친 전체 글(형식 포함)만. 설명/따옴표 붙이지 마.
"""


def _refine_draft(raw_draft: str, api_key: str) -> str:
    """초안을 사람처럼 자연스럽게 퇴고. 형식/마커 보존 검증 통과 시만 채택, 아니면 원본 반환."""
    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"아래 초안을 퇴고해줘:\n\n{raw_draft}",
            config=gtypes.GenerateContentConfig(
                system_instruction=_REFINE_SYSTEM,
                max_output_tokens=8192,
                temperature=0.8,
            ),
        )
        refined = (resp.text or "").strip()
        # 형식 보존 검증: 핵심 마커가 모두 살아있어야 채택
        if (refined and "TITLE:" in refined
                and refined.count("[사진") >= 6
                and "[FAQ시작]" in refined and "[표시작]" in refined):
            return refined
        logger.warning("퇴고 결과 형식 깨짐 — 원본 유지")
    except Exception as e:
        logger.warning(f"퇴고 실패 (원본 유지): {e}")
    return raw_draft


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

    # 매 글마다 도입부 스타일을 랜덤으로 강제 → 천편일률 공식 도입부 방지 (유사문서/AI 신호 회피)
    intro_styles = [
        "구체적인 장면과 시간 묘사로 시작 (예: '어제 저녁 8시, 싱크대 앞에서')",
        "의외의 숫자나 사실을 먼저 툭 던지며 시작 (예: '한 달에 1만 2천원이 줄었어요')",
        "내 실패담을 자백하며 시작 (예: '저 이거 1년을 잘못 쓰고 있었어요')",
        "결론부터 말하는 역두괄식으로 시작 (예: '결론부터 말하면 답은 ~였어요')",
        "남편이나 신혼 생활의 한 장면 에피소드로 시작",
    ]
    intro_hint = random.choice(intro_styles)

    user_msg = (
        f"오늘 포스팅 키워드: {keyword}"
        f"{category_note}"
        f"{trend_note}"
        f"\n\n위 키워드로 현지언니 블로그 글을 작성해줘."
        f"\n[이번 글 도입부 스타일] {intro_hint}"
        f" — '혹시 ~신가요 / 솔직히 저도 / 오늘은 제가 ~알려드릴게요 / 이 글 하나만'식 공식 도입부는 절대 금지."
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
                # ── 퇴고(refinement) 패스: 초안을 사람처럼 다듬기 (품질 최대 지렛대) ──
                refined_raw = _refine_draft(raw, api_key)
                if refined_raw != raw:
                    refined_parsed = _parse_response(refined_raw)
                    if refined_parsed:
                        rb_len = len(_IMAGE_MARKER.sub("", refined_parsed.get("body", "")))
                        if rb_len >= 500:
                            logger.info(f"퇴고 적용: 본문 {body_len}→{rb_len}자")
                            return refined_parsed
                    logger.warning("퇴고본 품질 미달 — 초안 사용")
                return parsed
        except Exception as e:
            logger.error(f"Gemini 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)
    return None
