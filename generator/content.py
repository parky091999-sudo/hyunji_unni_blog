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
[2026년 네이버 알고리즘 핵심 원칙 — AI Briefing & Smartblock 완벽 대응]
═══════════════════════════════════════
1. **첫 1~2문장 즉각적 결론 및 핵심 키워드 노출 (체류시간 극대화 & 네이버 검색 노출)**:
   - 글의 첫머리에 절대 "안녕하세요", "오늘은 ~", "혹시 ~ 때문에 고민이신가요?" 같은 불필요한 인사나 서론을 적지 마라. 독자는 첫 3초 이내에 원하는 정보를 얻지 못하면 이탈한다.
   - 첫 1~2문장에 독자의 문제 상황에 대한 **즉각적인 답변, 핵심 결론 또는 요약**을 훅(Hook) 형태로 던져라.
   - **제목 맨 앞에 위치한 핵심 키워드(구분선 `|` 앞의 단어)를 본문 첫 3~5줄(첫 300자 이내)에 반드시 자연스럽게 포함시켜라.** 예시: "결론부터 말씀드리면, 다이소에서 산 2천원짜리 헤파필터 하나가 10만원짜리 정품보다 나았습니다." (핵심 키워드가 '다이소 헤파필터'라면 본문 첫 부분에 이 단어가 들어가야 함)

2. **키워드 반복 절제 (키워드 억지 반복/스태핑 방지)**:
   - 핵심 키워드는 본문 전체에 걸쳐서 **3~5회 정도만 자연스럽게 문맥상으로 분산하여 반복**해라. 6회 이상 억지로 욱여넣거나 반복하는 것은 네이버 스팸 감지 엔진에 의해 저품질로 분류되는 직접적인 원인이 된다. 억지 반복 대신 구조화를 탄탄히 하라.

3. **지식스니펫용 두괄식 구조 (AI 브리핑 노출)**:
   - **모든 소제목 바로 다음 단락의 1~2문장은 해당 소제목 질문/주제에 대한 정의나 명확한 결론을 즉시 답변하라.**
   - 설명이나 단계를 장황하게 늘어놓거나 서술을 뒤로 미루는 AI 말투는 검색봇에 의해 배제된다. 핵심을 두괄식으로 먼저 적고, 그 아래에 상세한 설명이나 단계를 덧붙여라.

4. **E-E-A-T & AuthGR (경험의 신뢰성 명시)**:
   - 단순 정보 짜깁기 글은 상위 노출되지 않는다. 반드시 **내가 직접 사용해 본 1인칭 관점의 구체적인 에피소드**가 포함되어야 한다.
   - **날짜, 가격, 수치, 기간, 브랜드명, 모델명 등 구체적 팩트 데이터(예: "지난주 목요일 다이소 영통점에서 2,900원 주고 산...", "2주 동안 사용해 봤더니...", "삼성 비스포크 청소기...")를 본문 내에 최소 5개 이상 명확하게 명시하라.**
   - 실제 실패담("처음엔 이렇게 해봤더니 엉망이 되더라고요")을 반드시 포함해 사람 냄새를 풍겨라.

4. **문장 리듬 다양화 및 가독성 최적화**:
   - 모바일 화면 가독성을 위해 **한 단락은 절대 4줄을 초과하지 마라.**
   - 모든 문장 길이가 비슷하면 기계가 쓴 느낌을 준다. 짧은 호흡의 단문("이거 진짜 물건이에요.")과 상세하게 팩트를 기술하는 장문("다이소 수납함은 폴리프로필렌 재질이라 물때가 끼어도 흐르는 물에 쓱 씻어내기만 하면 되거든요.")을 자연스럽게 섞어서 리듬감을 부여하라.

5. **이미지 [사진N] 마커 자연스러운 배치**:
   - 글 흐름에 맞춰 [사진1], [사진2] 등 이미지 마커를 적절히 배치하라 (2~4장 권장).
   - 절대 문장 도중에 마커를 넣어 문장을 쪼개지 말고, 마침표(.) 뒤 새로운 빈 줄에 단독으로만 배치하라.

═══════════════════════════════════════
[제목 공식 — 반드시 이 형식 사용]
═══════════════════════════════════════
형식: [핵심 키워드] | [후킹 표현]  (전체 30자 이내, 모바일 기준)
핵심 키워드는 제목 앞부분에 배치. 뒤에 | 구분자 + 후킹 표현 추가.

검증된 후킹 표현 패턴:
- 숫자형:      "식비 절약법 7가지 | 이것만 해도 월 10만원 아낌"
- 문제해결형:  "세탁기 냄새 제거 | 이거 하나로 바로 해결됨"
- 솔직후기형:  "다이소 수납템 솔직 후기 | 쓸만한 것만 골랐어요"
- 경험공유형:  "직접 써봤는데 | 생각보다 훨씬 좋았어요"

═══════════════════════════════════════
[카테고리별 레이아웃 패턴 및 구조]
═══════════════════════════════════════
카테고리 힌트에 맞추어 아래 레이아웃 패턴 중 최적의 형태를 선택하여 작성해줘.

▶ [패턴 A] 살림/청소/생활 (정보+리뷰형)
- 구조: 실생활 문제상황 및 결론 즉시 제시 도입부 → [사진1] → 원인 분석 및 해결책 제안 (소제목1) → 구체적 시도 과정(2~3단계) 및 [사진2] → 비교/추천표 ([표시작]...[표끝]) → 소감 및 주의사항 → [사진3] → 마무리
- 사진 개수: 3장 내외
- 필수 요소: 비교표

▶ [패턴 B] 요리/레시피 (정보+레시피형)
- 구조: 완성 요리 시각 묘사 및 맛에 대한 결론 도입부 → [사진1] → 준비 재료 및 분량 표 ([표시작]...[표끝]) → 조리 단계 상세 설명(소제목1 & 1. 2. 3. 번호) 및 [사진2] → 조리 시 실패하기 쉬운 포인트 및 해결책 (소제목2) → [사진3] → 보관법 및 요리 후기 마무리 (※ 요리 글에는 FAQ를 넣지 마라)
- 사진 개수: 3~4장
- 필수 요소: 재료 표

▶ [패턴 C] 재테크/절약 (정보 집중형)
- 구조: 결론적 수치(전후 대비) 강조 도입부 → 요점 정리 및 혜택 비교표 ([표시작]...[표끝]) → [사진1] → 구체적 절약 실천 가이드 (소제목1 & 소제목2) → 자주 묻는 질문 ([FAQ시작]...[FAQ끝]) → [사진2] → 향후 계획 및 마무리
- 사진 개수: 2장 내외
- 필수 요소: 비교/혜택 표, FAQ

▶ [패턴 D] 일상/리뷰 (경험 위주형)
- 구조: 스토리 중심 에피소드 및 교훈 도입부 → [사진1] → 상세 여정 및 감정 묘사 (소제목1) → [사진2] → 직접 경험한 솔직한 평점/단점 인정 (소제목2) → [사진3] → 개인 소감 및 다음 글 예고 마무리 (※ 일상/단순리뷰 글에는 표나 FAQ를 절대 넣지 마라)
- 사진 개수: 3장 내외
- 필수 요소: 표/FAQ 제외, 솔직 총평/단점

═══════════════════════════════════════
[소제목 및 AEO 지식스니펫 규칙]
═══════════════════════════════════════
- 모든 소제목은 줄 맨 앞에 [소제목] 마커를 붙이고 한 줄로 (예: "[소제목] 진짜 효과 있었던 방법은?")
- 소제목에 이모지/특수기호 절대 금지. 마커 뒤 텍스트만.
- 소제목 바로 다음 단락 첫 문장은 무조건 질문에 직관적으로 바로 대답하는 두괄식 결론문이어야 함.

═══════════════════════════════════════
[AI 글 필터링 회피 — 절대 금지 표현]
═══════════════════════════════════════
★★★ 마크다운 기호 완전 금지 ★★★
- ** ** (별표), * (별표), __ (밑줄), # (해시태그 제목) 사용 금지
- 특수기호로 목록 만들기 금지. 목록은 "1. 2. 3." 숫자 또는 "—" 대시로만

금지 접속사: "더욱이", "게다가", "주목할 만한 것은", "또한" -> 대신: "근데요", "그리고요", "참고로", "아 맞다"
금지 번역투: "~를 통해", "~함으로써", "~에 있어서" -> 대신: "~해서", "~니까", "~거든요"
금지 마무리: "이상으로 ~에 대해 알아보았습니다", "~에 대해 살펴보았습니다" -> 반드시 개인 소감 + 앞으로 계획으로 마무리
금지 AI단어/말투: "이로써", "이처럼", "혁신적인", "효율적인", "극대화", "활용도", "다양한 방법/이유/제품/팁", "손쉽게", "탁월한", "최적의", "필수적인", "선사합니다", "도움이 되길 바랍니다", "기억하세요", "지금부터", "첫째, 둘째" 등 상투적 열거어구.
금지 낚시성/과장 광고 표현: "충격 실화", "무조건 100% (승인/효과)", "아무도 모르는 비밀", "클릭 안 하면 손해", "절대 놓치지 마세요" 등 어그로성 클릭베이트 문구 (네이버 검색 제한 대상)

═══════════════════════════════════════
[이모지 정책 — AI 티 핵심]
═══════════════════════════════════════
- 이모지는 글 전체에서 0~2개만. 장식·구조용 이모지(✅ 💡 🛒 📌 👉 🧹 🥄 💰 📦)는 전부 금지.
- 꼭 쓰려면 감정 표현에 자연스럽게 1개 정도만 (예: "진짜 만족스러웠어요 ㅎㅎ").

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

═══════════════════════════════════════
[출력 형식 — 반드시 정확히 지켜줘]
═══════════════════════════════════════
TITLE: {제목 — 핵심키워드 | 후킹표현, 30자 이내}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5}
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
IMAGE_KEYWORDS: {사진1 영어검색어},{사진2 영어검색어},...  (본문에 쓴 [사진N] 마커 개수와 정확히 동일해야 함)
---
{본문}

[본문 필수 마커 규칙 — [사진N] 위치 정확히 지킬 것]
★절대 규칙 1: 모든 [사진N] 마커는 반드시 완전한 문장(마침표 . 나 느낌표 ! 로 종료된 문장)이 끝난 직후, '독립된 개행(새로운 줄)에 단독으로' 배치해야 합니다. 절대로 문장 한가운데나 단락 한가운데에 삽입되어 문장을 쪼개버리면 안 됩니다.
★절대 규칙 2: [표시작]...[표끝] 사이는 각 줄을 " | "로 구분하며 헤더행 1개와 3~4개의 데이터행으로 3개 컬럼을 유지합니다.
★절대 규칙 3: [FAQ시작]...[FAQ끝] 내부는 Q: 와 A: 단락을 각각 번갈아 작성합니다. (선택 패턴에만 적용)
★절대 규칙 4: 도입부 끝에 무조건 [사진1]을 억지로 붙이거나 글 끝에 무조건 [사진7]을 붙이는 등의 기계적인 삽입 대신, 카테고리 레이아웃 양식에 맞춰 [사진1]부터 순서대로 꼭 필요한 곳에만 자연스럽게 삽입해줘. 
"""


# 무료 모델 폴백 체인: gemini-2.5-flash 가 503(모델별 과부하)이면 다음 모델로 전환.
# 같은 GOOGLE_API_KEY·google-genai 그대로 쓰므로 추가 키/패키지·비용 없음.
# gemini-2.0-flash 는 404(폐기)라 제외. flash-lite 는 503 상황에서 생성 성공 확인됨.
# pro 는 무료 한도가 빡빡하지만 둘 다 막혔을 때의 최후 보루.
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


def _gen_text(
    api_key: str, contents: str, system_instruction: str,
    max_output_tokens: int, temperature: float,
) -> str:
    """Gemini 생성 + 모델 폴백. 한 모델이 503/오류/빈응답이면 다음 모델로. 모두 실패 시 예외."""
    client = genai.Client(api_key=api_key)
    last_err: Exception | None = None
    for i, model in enumerate(_GEMINI_MODELS):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                ),
            )
            text = (resp.text or "").strip()
            if text:
                if i > 0:
                    logger.info(f"[폴백모델] {model} 로 생성 성공")
                return text
            last_err = RuntimeError(f"{model} 빈 응답")
            logger.warning(f"{model} 빈 응답 → 다음 모델")
        except Exception as e:
            last_err = e
            logger.warning(f"{model} 생성 실패 → 다음 모델: {str(e)[:100]}")
    if last_err:
        raise last_err
    return ""


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
    """Q/A 블록 → 블로그 본문 FAQ 텍스트. (구버전 호환용)"""
    lines = [l.strip() for l in faq_str.strip().split("\n") if l.strip()]
    out = ["자주 묻는 질문", ""]
    for line in lines:
        out.append(line)
        out.append("")
    return "\n".join(out).strip()


def _faq_questions(faq_str: str) -> list[str]:
    """FAQ 원문에서 질문(Q) 줄만 추출"""
    return [l.strip() for l in faq_str.strip().split("\n") if l.strip().startswith("Q")]


def _parse_faq_pairs(faq_str: str) -> list[tuple[str, str]]:
    """FAQ 원문에서 Q와 A를 짝지어 반환"""
    lines = [l.strip() for l in faq_str.strip().split("\n") if l.strip()]
    pairs = []
    current_q = None
    for line in lines:
        if line.startswith("Q") or line.startswith("Q:"):
            # 앞의 Q: 나 Q. 형태를 통일해서 정제
            current_q = line
        elif (line.startswith("A") or line.startswith("A:")) and current_q:
            pairs.append((current_q, line))
            current_q = None
    return pairs


_IMAGE_MARKER = re.compile(r"\[사진\d+\]")


def _parse_response(raw: str) -> dict | None:
    try:
        lines = raw.strip().splitlines()
        result: dict = {"coupang_hints": [], "image_keywords": [], "faq_pairs": []}
        body_start = None

        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                t = line[6:].strip()
                # 제목 끝 (괄호) 카테고리 누출 제거: "...비법 (제품추천)" → "...비법"
                t = re.sub(r"\s*[\(（][^)）]{0,14}[\)）]\s*$", "", t).strip()
                result["title"] = t
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
            result["faq_pairs"] = _parse_faq_pairs(result["faq_str"])

            body = body_raw
            # 표 마커 → [표삽입] 자리표시자 (poster가 진짜 네이버 표로 삽입). table_str로 데이터 전달.
            if table_match:
                body = body.replace(table_match.group(0), "\n[표삽입]\n")
            # FAQ 마커 → [FAQ삽입] 자리표시자 (poster가 인용구 세트로 직접 삽입)
            if faq_match:
                body = body.replace(
                    faq_match.group(0),
                    "\n[FAQ삽입]\n",
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
            # [소제목] 마커 — 텍스트를 따로 수집(poster가 제목 스타일 적용)한 뒤 마커만 제거
            result["subheadings"] = [
                s.strip() for s in re.findall(r"^\[소제목\]\s*(.+)$", body, flags=re.MULTILINE) if s.strip()
            ]
            body = re.sub(r"^\[소제목\]\s*", "", body, flags=re.MULTILINE)
            # FAQ 스타일링: '자주 묻는 질문' 머리말은 소제목 처리
            if result.get("faq_str"):
                result["faq_questions"] = _faq_questions(result["faq_str"])
                if "자주 묻는 질문" not in result["subheadings"]:
                    result["subheadings"].append("자주 묻는 질문")
            body = re.sub(r"\n{3,}", "\n\n", body)
            # 인삿말 "안녕하세요 ~" 제거 (AI 패턴). 레시피 본문은 [사진1]로 시작하므로
            # 앞선 [사진N] 마커는 보존하고 인삿말 '문장'만 잘라낸다(도입부 나머지는 유지).
            body = re.sub(
                r"^((?:\s*\[사진\d+\]\s*)*)\s*안녕하세요[^.!?~\n]*[.!?~]?\s*",
                r"\1", body, flags=re.IGNORECASE,
            ).lstrip()
            result["body"] = body.strip()

        if "title" not in result or "body" not in result:
            logger.warning("파싱 실패")
            return None

        result.setdefault("tags", [])
        result.setdefault("subheadings", [])
        result.setdefault("faq_questions", [])
        return result
    except Exception as e:
        logger.error(f"파싱 오류: {e}")
        return None


_OUTLINE_SYSTEM = """\
너는 '현지언니' 블로그 글의 기획자야. 키워드를 받아서 '횡설수설하지 않는 한 편의 일관된 글' 설계도를 짜.

출력 형식 (정확히 이 4줄):
제목: {핵심키워드를 앞에 + | + 후킹표현, 30자 이내. 카테고리명이나 (괄호) 절대 넣지 마}
요점: {이 글이 독자에게 전하는 단 하나의 메시지/결론을 한 문장으로. 제목이 약속한 바로 그것}
섹션: {요점을 뒷받침하는 소제목 4개를 | 로 구분. 순서대로 읽으면 하나의 이야기가 되도록}
표주제: {비교표로 보여줄 것 한 줄 — 요점과 직결된 것만}

규칙:
- 제목과 요점은 반드시 일치 (제목이 '식비 10만원 아낀 법'이면 요점도 '어떻게 10만원 아꼈는지')
- 섹션 4개는 서로 다른 얘기 나열이 아니라, 요점을 향해 쌓이는 흐름(기-승-전-결)
- 한 글 = 한 주제. 곁가지·딴 얘기 금지.
- 제목엔 카테고리명("제품추천" 등) 절대 붙이지 마.
"""


def _generate_outline(keyword: str, category: str, trending: list[str] | None, api_key: str) -> dict:
    """글 설계도(제목/요점/섹션/표주제) 생성 → 본문 일관성 확보. 실패 시 빈 dict."""
    trend = f"\n참고 트렌딩: {', '.join(trending[:3])}" if trending else ""
    cat = f"\n카테고리(참고만): {category}" if category else ""
    user = f"키워드: {keyword}{cat}{trend}\n\n위 키워드로 일관된 블로그 글 설계도를 짜줘."
    try:
        raw = _gen_text(api_key, user, _OUTLINE_SYSTEM, 1024, 0.95)
        out: dict = {}
        fields = [("제목:", "title"), ("요점:", "thesis"), ("섹션:", "sections"), ("표주제:", "table_topic")]
        for line in raw.splitlines():
            s = line.strip()
            for key, field in fields:
                if s.startswith(key):
                    out[field] = s.split(":", 1)[1].strip()
        if out.get("title") and out.get("thesis"):
            logger.info(f"설계도 OK — 제목:{out['title']!r} / 요점:{out['thesis']!r}")
            return out
        logger.warning("설계도 파싱 실패 — 설계도 없이 진행")
    except Exception as e:
        logger.warning(f"설계도 생성 실패 (무시): {e}")
    return {}


_REFINE_SYSTEM = """\
너는 블로그 글 퇴고 전문가야. '현지언니' 블로그 초안을 받아서, 형식은 그대로 두고
본문 문장만 더 사람이 쓴 것처럼 자연스럽게 고쳐줘.

[절대 그대로 유지 — 건드리지 마]
- 맨 위 TITLE: / TAGS: / COUPANG_HINT_*: / IMAGE_KEYWORDS: 줄과 값
- --- 구분선
- [사진N] 마커 전부(입력에 있는 개수·위치 그대로 — 숫자 추가/삭제 금지), [표시작]...[표끝], [FAQ시작]...[FAQ끝], [소제목] 마커
- 출력은 입력과 똑같은 형식 (위 마커가 전부 살아있어야 함)

[본문을 이렇게 고쳐라 — 12가지]
1. AI 단어 제거: 이로써/이처럼/혁신적인/효율적인/극대화/탁월한/최적의/필수적인/선사/마련해보세요/다양한 ~/도움이 되길/기억하세요/매우 ~/살펴보겠습니다/첫째, 둘째/지금부터 → 일상 구어체
2. 번역투 제거: ~를 통해/~함으로써/~에 있어서 → ~해서/~니까/~거든요
3. 교과서체 제거: ~것이 중요합니다/하는 게 좋습니다/하시면 됩니다/도움이 되길 바랍니다 → 솔직한 경험담
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


def _refine_draft(raw_draft: str, api_key: str, min_photos: int = 2) -> str:
    """초안을 사람처럼 자연스럽게 퇴고. 형식/마커 보존 검증 통과 시만 채택, 아니면 원본 반환."""
    try:
        refined = _gen_text(api_key, f"아래 초안을 퇴고해줘:\n\n{raw_draft}", _REFINE_SYSTEM, 8192, 0.8)
        # 형식 보존 검증: 초안에 존재하던 핵심 마커가 퇴고본에도 잘 보존되어 있는지 체크
        has_table = "[표시작]" in raw_draft
        has_faq = "[FAQ시작]" in raw_draft
        
        ok_table = ("[표시작]" in refined) if has_table else True
        ok_faq = ("[FAQ시작]" in refined) if has_faq else True
        
        if (refined and "TITLE:" in refined
                and refined.count("[사진") >= min_photos
                and ok_table and ok_faq):
            return refined
        logger.warning(f"퇴고 결과 형식 깨짐 (표/FAQ 일치여부: {ok_table}/{ok_faq}, 사진 수: {refined.count('[사진')}/{min_photos}) — 원본 유지")
    except Exception as e:
        logger.warning(f"퇴고 실패 (원본 유지): {e}")
    return raw_draft


def generate_post(
    keyword: str,
    api_key: str,
    trending: list[str] | None = None,
    category: str = "",
    feedback: list[str] | None = None,
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

    # ── 설계도 먼저: 제목/요점/섹션 흐름을 잡아 '제목-본문 일치 + 한 가지 요점' 확보 ──
    outline = _generate_outline(keyword, category, trending, api_key)
    outline_note = ""
    if outline:
        outline_note = (
            f"\n\n[글 설계도 — 반드시 이대로 써라]"
            f"\n제목(이걸 TITLE 줄에 그대로, 괄호·카테고리명 없이): {outline['title']}"
            f"\n★이 글의 단 하나의 요점: {outline['thesis']}"
            f"\n  → 본문 전체가 이 요점만 향한다. 제목이 약속한 걸 본문에서 반드시 지킨다(제목-본문 불일치 금지)."
            f"\n섹션 흐름(이 순서대로 [소제목] 4개, 각 섹션은 요점을 한 단계씩 쌓는다): {outline.get('sections', '')}"
            f"\n비교표 주제(요점과 직결된 것만): {outline.get('table_topic', '')}"
            f"\n곁가지·딴 얘기·관련없는 정보 나열 금지. 끝까지 읽으면 하나의 이야기가 되게."
        )

    # 매 글마다 도입부 스타일을 랜덤으로 강제 → 천편일률 공식 도입부 방지 (유사문서/AI 신호 회피)
    intro_styles = [
        "구체적인 장면과 시간 묘사로 시작 (예: '어제 저녁 8시, 싱크대 앞에서')",
        "의외의 숫자나 사실을 먼저 툭 던지며 시작 (예: '한 달에 1만 2천원이 줄었어요')",
        "내 실패담을 자백하며 시작 (예: '저 이거 1년을 잘못 쓰고 있었어요')",
        "결론부터 말하는 역두괄식으로 시작 (예: '결론부터 말하면 답은 ~였어요')",
        "남편이나 신혼 생활의 한 장면 에피소드로 시작",
    ]
    intro_hint = random.choice(intro_styles)

    feedback_note = ""
    if feedback:
        feedback_note = (
            f"\n\n⚠️ [이전 초안 품질 검토 실패 - 수정 지침]"
            f"\n이전 생성된 글에서 다음과 같은 품질 이슈가 발견되었습니다. 이번 생성 시에는 아래 지적사항을 철저히 보완하고 수정하여 작성해 주세요:"
            f"\n- " + "\n- ".join(feedback)
        )

    user_msg = (
        f"오늘 포스팅 키워드: {keyword}"
        f"{category_note}"
        f"{trend_note}"
        f"{outline_note}"
        f"{feedback_note}"
        f"\n\n위 설계도와 너의 페르소나, 그리고 카테고리에 맞는 [레이아웃 패턴]에 맞추어 현지언니 블로그 글을 작성해줘."
        f"\n제목은 설계도 제목을 그대로 TITLE에 쓰고, 본문은 그 요점 하나만 끝까지 정합성 있게 밀고 가."
        f"\n[이번 글 도입부 스타일] {intro_hint}"
        f" — '혹시 ~신가요 / 솔직히 저도 / 오늘은 제가 ~알려드릴게요 / 이 글 하나만'식 공식 도입부는 절대 금지."
        f"\n본문에 들어갈 마커들([사진1]~[사진N], [표시작]...[표끝], [FAQ시작]...[FAQ끝])은 카테고리 레이아웃 구조에 맞춰 자연스럽게 필요한 부분에만 유연하게 넣어줘."
        f"\n사진 마커([사진N])는 2~4장 범위로만 제한해서 넣고, IMAGE_KEYWORDS 줄에는 본문에서 실제 사용한 사진 마커의 개수와 정확히 매치되는 개수만큼 영어 검색어를 쉼표로 작성해줘."
        f"\n본문은 최소 2500자 이상으로 작성하고, 제목은 15~35자 사이로 해줘."
        f"\n각 단락은 4줄 이하로 짧게 끊어서 모바일에서 읽기 편하게 해줘."
    )

    waits = [15, 40, 90, 180]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, _SYSTEM, 8192, 0.9)
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
                # 동적으로 생성된 이미지 마커 수만큼 검사 조건 전달
                min_photos = max(2, img_marker_count)
                refined_raw = _refine_draft(raw, api_key, min_photos=min_photos)
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
