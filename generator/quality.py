"""
생성된 블로그 글의 품질 점수화 모듈
네이버 C-Rank 기준 및 AI 패턴 탐지 기반으로 0~100점 채점
60점 이상이면 발행, 미만이면 재생성 권장
"""
import logging
import re

logger = logging.getLogger(__name__)

# 채점 기준 (최대 100점)
_SCORE_WEIGHTS = {
    "body_length": 20,     # 본문 2000자+ = 20점, 1500자+ = 10점, 1000자+ = 5점
    "no_ai_pattern": 20,   # AI 패턴 감지 시 패턴당 -5점 (최대 -20)
    "subheadings": 10,     # 소제목 2개+ = 10점, 1개 = 5점
    "has_table": 10,       # 표 포함 = 10점
    "has_faq": 10,         # FAQ 포함 = 10점
    "personal_exp": 10,    # 1인칭 경험 표현 = 10점
    "concrete_data": 10,   # 숫자/가격/브랜드 = 10점
    "tags_count": 10,      # 태그 5개+ = 10점, 3개+ = 5점
    "title_length": 10,    # 제목 15~35자 = 10점, 10~40자 = 5점
}

# AI 패턴 — 감지 시 점수 차감
_AI_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"안녕하세요"), "인사말 시작: '안녕하세요'"),
    (re.compile(r"오늘은\s*.+에\s*대해\s*(알아|살펴|소개)"), "AI 도입부: '오늘은 ~에 대해 알아보겠습니다'"),
    (re.compile(r"것이\s*중요합니다"), "AI 교과서체: '것이 중요합니다'"),
    (re.compile(r"하는\s*것이\s*좋습니다"), "AI 교과서체: '하는 것이 좋습니다'"),
    (re.compile(r"하시면\s*됩니다"), "AI 교과서체: '하시면 됩니다'"),
    (re.compile(r"다들\s*아시다시피"), "채우기 문장: '다들 아시다시피'"),
    (re.compile(r"많은\s*분들이"), "채우기 문장: '많은 분들이'"),
    (re.compile(r"이런\s*분들께\s*추천"), "템플릿 문장: '이런 분들께 추천'"),
    (re.compile(r"힘드셨죠"), "빈 공감: '힘드셨죠?'"),
    (re.compile(r"공감되시나요"), "빈 공감: '공감되시나요?'"),
    (re.compile(r"\*\*.+\*\*"), "마크다운 사용: **굵게**"),
    (re.compile(r"[✔★○□◆◇▶]"), "특수기호 목록 사용"),
    (re.compile(r"함께\s*알아보겠습니다"), "AI 도입부: '함께 알아보겠습니다'"),
    (re.compile(r"도움이\s*되셨으면"), "AI 마무리: '도움이 되셨으면'"),
    # 공식(천편일률) 도입부 — 2026 AI/저품질 핵심 신호
    (re.compile(r"이\s*글\s*하나만"), "공식 도입부: '이 글 하나만'"),
    (re.compile(r"찾았지\s*뭐예요"), "공식 도입부: '찾았지 뭐예요'"),
    (re.compile(r"오늘은\s*제가.{0,15}(알려|소개|준비)"), "공식 도입부: '오늘은 제가 ~'"),
    (re.compile(r"끝까지\s*읽어\s*(주세요|보세요)"), "체류 구걸: '끝까지 읽어주세요'"),
]

# 소제목 패턴 (질문형 소제목 우대)
_SUBHEADING_PATTERN = re.compile(
    r"^[^\n]{3,30}\??\s*$",  # 짧은 단독 줄 (소제목 후보)
    re.MULTILINE,
)

# 1인칭 경험 표현 키워드
_PERSONAL_KEYWORDS = re.compile(
    r"저\s|제가\s|저는\s|남편|신혼|우리\s*집|우리\s*남편|제\s*경험|작년|올해|지난\s*달|"
    r"직접\s*써|실제로\s*써|구매해봤|해봤는데|했는데|사봤|써봤"
)

# 구체적 데이터 — 숫자/가격/브랜드
_CONCRETE_DATA = re.compile(
    r"\d+[,\d]*원|\d+만\s*원|\d+천\s*원|"  # 가격
    r"\d{4}년|\d+월|\d+일|\d+주|"          # 날짜/기간
    r"다이소|이케아|쿠팡|무인양품|JAJU|자주|"  # 브랜드
    r"\d+분\s*만에|\d+배|\d+%|\d+개"       # 수량/비율
)

# 표 마커
_TABLE_MARKER = re.compile(r"\[표시작\].*?\[표끝\]", re.DOTALL)
# FAQ 마커
_FAQ_MARKER = re.compile(r"\[FAQ시작\].*?\[FAQ끝\]", re.DOTALL)


def score_content(
    title: str,
    body: str,
    tags: list[str],
    table_str: str = "",
    faq_str: str = "",
) -> dict:
    """
    블로그 글 품질 점수화.

    반환:
    {
        "score": 75,       # 0~100
        "issues": ["..."], # 발견된 문제점 목록
        "pass": True       # 60점 이상이면 True
    }
    """
    score = 0
    issues: list[str] = []

    # 1. 본문 길이 (최대 20점)
    body_len = len(body)
    if body_len >= 2000:
        score += 20
    elif body_len >= 1500:
        score += 10
        issues.append(f"본문 짧음 ({body_len}자, 권장 2000자+)")
    elif body_len >= 1000:
        score += 5
        issues.append(f"본문 너무 짧음 ({body_len}자, 권장 2000자+)")
    else:
        issues.append(f"본문 매우 짧음 ({body_len}자) — 발행 비권장")

    # 2. AI 패턴 감지 (패턴당 -5점, 최대 -20점까지만 차감)
    ai_base = 20
    ai_deduct = 0
    for pattern, desc in _AI_PATTERNS:
        if pattern.search(body) or pattern.search(title):
            ai_deduct = min(ai_deduct + 5, 20)
            issues.append(f"AI 패턴 감지: {desc}")
    score += max(0, ai_base - ai_deduct)

    # 3. 소제목 존재 (최대 10점)
    # 물음표로 끝나는 줄 또는 짧은 단독 줄을 소제목으로 간주
    subheading_matches = re.findall(r"^\S.{2,25}\??\s*$", body, re.MULTILINE)
    # 너무 짧거나 긴 줄 제외
    subheadings = [s for s in subheading_matches if 5 <= len(s.strip()) <= 30]
    if len(subheadings) >= 2:
        score += 10
    elif len(subheadings) == 1:
        score += 5
        issues.append("소제목 1개 — 2개 이상 권장")
    else:
        issues.append("소제목 없음 — 질문형 소제목 추가 권장")

    # 4. 표 포함 (10점) — 마커가 이미 포맷으로 교체됐으므로 table_str로 판단
    has_table = bool(table_str) or bool(_TABLE_MARKER.search(body))
    if has_table:
        score += 10
    else:
        issues.append("표 없음 — 비교표 추가 권장")

    # 5. FAQ 포함 (10점) — 마커가 이미 포맷으로 교체됐으므로 faq_str로 판단
    has_faq = bool(faq_str) or bool(_FAQ_MARKER.search(body))
    if has_faq:
        score += 10
    else:
        issues.append("FAQ 없음 — FAQ 섹션 추가 권장")

    # 6. 1인칭 경험 표현 (10점)
    personal_count = len(_PERSONAL_KEYWORDS.findall(body))
    if personal_count >= 3:
        score += 10
    elif personal_count >= 1:
        score += 5
        issues.append(f"1인칭 경험 표현 부족 ({personal_count}회) — '저', '남편', '신혼' 등 추가")
    else:
        issues.append("1인칭 경험 표현 없음 — 개인 경험담 추가 필요")

    # 7. 숫자/구체적 데이터 (10점)
    data_count = len(_CONCRETE_DATA.findall(body))
    if data_count >= 5:
        score += 10
    elif data_count >= 3:
        score += 7
    elif data_count >= 1:
        score += 3
        issues.append(f"구체적 데이터 부족 ({data_count}개) — 가격, 날짜, 브랜드명 추가")
    else:
        issues.append("구체적 데이터 없음 — 숫자/가격/브랜드명 필수")

    # 8. 태그 수 (최대 10점)
    tag_count = len(tags)
    if tag_count >= 5:
        score += 10
    elif tag_count >= 3:
        score += 5
        issues.append(f"태그 부족 ({tag_count}개) — 5개 이상 권장")
    else:
        issues.append(f"태그 너무 적음 ({tag_count}개)")

    # 9. 제목 길이 (최대 10점)
    title_len = len(title)
    if 15 <= title_len <= 35:
        score += 10
    elif 10 <= title_len <= 40:
        score += 5
        issues.append(f"제목 길이 미흡 ({title_len}자, 권장 15~35자)")
    else:
        issues.append(f"제목 길이 부적합 ({title_len}자, 권장 15~35자)")

    # 점수 범위 보정 (0~100)
    score = max(0, min(100, score))
    passed = score >= 60

    logger.info(
        f"품질 점수: {score}/100 ({'통과' if passed else '재생성 권장'}) | "
        f"본문 {body_len}자 | AI패턴 {ai_deduct//5}개 | "
        f"소제목 {len(subheadings)}개 | 데이터 {data_count}개"
    )
    if issues:
        logger.info(f"품질 이슈: {' / '.join(issues)}")

    return {
        "score": score,
        "issues": issues,
        "pass": passed,
        "detail": {
            "body_length": body_len,
            "ai_patterns_found": ai_deduct // 5,
            "subheadings": len(subheadings),
            "has_table": has_table,
            "has_faq": has_faq,
            "personal_count": personal_count,
            "data_count": data_count,
            "tag_count": tag_count,
            "title_length": title_len,
        },
    }
