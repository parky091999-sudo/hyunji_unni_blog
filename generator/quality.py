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
    # AI 단어 (실생활에서 잘 안 쓰는 표현)
    (re.compile(r"이로써"), "AI 단어: '이로써'"),
    (re.compile(r"이처럼"), "AI 단어: '이처럼'"),
    (re.compile(r"혁신적"), "AI 단어: '혁신적'"),
    (re.compile(r"극대화"), "AI 단어: '극대화'"),
    (re.compile(r"선사(합니다|해|하는)"), "AI 단어: '선사하다'"),
    (re.compile(r"마련해\s*보세요"), "AI 단어: '마련해보세요'"),
    (re.compile(r"추천드립니다"), "AI 단어: '추천드립니다'"),
    (re.compile(r"다양한\s*(방법|이유|제품|팁|역할|기능|활용)"), "AI 표현: '다양한 ~'"),
    (re.compile(r"도움이\s*(되길|되었으면|되기를|되었기를)\s*(바랍니다|좋겠습니다)"), "AI 상투구: '도움이 되길 바랍니다'"),
    (re.compile(r"기억하세요"), "AI 지시어: '기억하세요'"),
    (re.compile(r"매우\s*(유용|효과적|중요|편리|탁월)"), "AI 수식어: '매우 ~'"),
    (re.compile(r"살펴보(도록\s*하겠습니다|겠습니다)"), "AI 진행어: '살펴보겠습니다'"),
    (re.compile(r"^(첫째|둘째|셋째|넷째|다섯째),?\s", re.MULTILINE), "AI 열거식: '첫째, 둘째'"),
    (re.compile(r"지금부터"), "AI 진행어: '지금부터'"),
    (re.compile(r"충격\s*실화"), "낚시성 표현: '충격 실화'"),
    (re.compile(r"무조건\s*100%"), "낚시성 표현: '무조건 100%'"),
    (re.compile(r"아무도\s*모르는\s*비밀"), "낚시성 표현: '아무도 모르는 비밀'"),
    (re.compile(r"클릭\s*안\s*하면\s*손해"), "낚시성 표현: '클릭 안 하면 손해'"),
    (re.compile(r"절대\s*놓치지\s*마세요"), "낚시성 표현: '절대 놓치지 마세요'"),
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

# 구체적 데이터 — 숫자/가격/브랜드 (AEO 최적화 핵심 팩트)
_CONCRETE_DATA = re.compile(
    r"\d+[,\d]*원|\d+만\s*원|\d+천\s*원|"  # 가격
    r"\d{4}년|\d+월|\d+일|\d+주|\d+일간|\d+개월|"  # 날짜/기간
    r"다이소|이케아|쿠팡|무인양품|JAJU|자주|올리브영|스타벅스|"  # 브랜드명
    r"\d+분\s*만에|\d+배|\d+%\s*|\d+개|\d+곳|\d+종|\d+회|\d+평|\d+호"  # 수량/비율/단위
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
    category: str = "",
) -> dict:
    """
    블로그 글 품질 점수화.
    
    category 파라미터를 기반으로 A/B/C/D 패턴별 가중치/필수 요소를 동적으로 판별합니다.
    """
    c = category.strip()
    if c in ["신혼일상", "일상", "신혼 일상"]:
        pattern = "D"  # 일상/리뷰 (표/FAQ 제외)
    elif c in ["요리식비", "오늘의 집밥 레시피", "cooking", "요리&식비절약", "요리&식비"]:
        pattern = "B"  # 요리/레시피 (표 필수, FAQ 제외)
    elif c in ["절약재테크", "재테크/절약", "절약&재테크"]:
        pattern = "C"  # 재테크/절약 (표 필수, FAQ 필수)
    else:
        pattern = "A"  # 살림/청소/생활 (표 필수, FAQ 제외)

    score = 0
    issues: list[str] = []
    # 점수는 통과(>=60)여도, 아래 '중대(수정 가능)' 이슈가 있으면 재생성을 유도하기 위한 목록.
    critical: list[str] = []

    # 1. 본문 길이 (패턴 D, A, B는 최대 30점, 패턴 C는 최대 20점)
    # ★목표 글자수는 카테고리별로 다름(WRITING_SYSTEM §6 모바일 스캔형, 정보밀도>볼륨):
    #   B(레시피)=1200 / D(일상)=1300 / A(살림)=1500 / C(절약)=1800.
    # full=목표 이상, -10=목표-300 이상, -20=목표-600 이상, 그 미만은 매우 짧음.
    body_len = len(body)
    max_body_score = 30 if pattern in ["D", "A", "B"] else 20
    body_target = {"B": 1200, "D": 1300, "A": 1500, "C": 1800}.get(pattern, 1500)
    if body_len >= body_target:
        score += max_body_score
    elif body_len >= body_target - 300:
        score += (max_body_score - 10)
        issues.append(f"본문 약간 짧음 ({body_len}자, 목표 {body_target}자+)")
    elif body_len >= body_target - 600:
        score += (max_body_score - 20)
        issues.append(f"본문 짧음 ({body_len}자, 목표 {body_target}자+)")
        critical.append(f"본문 짧음 ({body_len}자) — {body_target}자+로 보강(경험담·꿀팁 추가)")
    else:
        issues.append(f"본문 매우 짧음 ({body_len}자, 목표 {body_target}자+) — 발행 비권장")
        critical.append(f"본문 매우 짧음 ({body_len}자) — {body_target}자+로 대폭 보강 필요")

    # 2. AI 패턴 감지 (패턴 D는 최대 30점, 패턴 A, B, C는 최대 20점)
    ai_base = 30 if pattern == "D" else 20
    ai_deduct = 0
    for pattern_regex, desc in _AI_PATTERNS:
        if pattern_regex.search(body) or pattern_regex.search(title):
            ai_deduct = min(ai_deduct + 5, 20)
            issues.append(f"AI 패턴 감지: {desc}")
    score += max(0, ai_base - ai_deduct)

    # 3. 소제목 존재 (최대 10점)
    subheading_matches = re.findall(r"^\S.{2,25}\??\s*$", body, re.MULTILINE)
    subheadings = [s for s in subheading_matches if 5 <= len(s.strip()) <= 30]
    if len(subheadings) >= 2:
        score += 10
    elif len(subheadings) == 1:
        score += 5
        issues.append("소제목 1개 — 2개 이상 권장")
    else:
        issues.append("소제목 없음 — 질문형 소제목 추가 권장")

    # 4. 표 포함 (패턴 A, B, C는 10점, 패턴 D는 체크하지 않음)
    has_table = bool(table_str) or bool(_TABLE_MARKER.search(body))
    if pattern in ["A", "B", "C"]:
        if has_table:
            score += 10
        else:
            issues.append("표 없음 — 비교표 추가 권장")

    # 5. FAQ 포함 (패턴 C는 10점, 패턴 A, B, D는 체크하지 않음)
    has_faq = bool(faq_str) or bool(_FAQ_MARKER.search(body))
    if pattern == "C":
        if has_faq:
            score += 10
        else:
            issues.append("FAQ 없음 — FAQ 섹션 추가 권장")

    # 6. 1인칭 경험 표현 (패턴 D는 20점, 패턴 A, B, C는 10점)
    personal_count = len(_PERSONAL_KEYWORDS.findall(body))
    max_personal_score = 20 if pattern == "D" else 10
    if personal_count >= 3:
        score += max_personal_score
    elif personal_count >= 1:
        score += (max_personal_score - 10)
        issues.append(f"1인칭 경험 표현 부족 ({personal_count}회) — '저', '남편', '신혼' 등 추가")
    else:
        issues.append("1인칭 경험 표현 없음 — 개인 경험담 추가 필요")

    # 7. 구체적 데이터 및 AEO 정보 밀도 (10점)
    sentences = [s.strip() for s in body.split(".") if s.strip()]
    fact_sentences = [s for s in sentences if _CONCRETE_DATA.search(s)]
    data_count = len(_CONCRETE_DATA.findall(body))
    fact_ratio = len(fact_sentences) / len(sentences) if sentences else 0

    if data_count >= 6 and fact_ratio >= 0.15:
        score += 10
    elif data_count >= 4 or fact_ratio >= 0.10:
        score += 7
        if data_count < 6:
            issues.append(f"AEO 팩트 데이터 보강 가능 ({data_count}개, 비율 {fact_ratio:.1%})")
    elif data_count >= 2:
        score += 4
        issues.append(f"AEO 팩트 데이터 부족 ({data_count}개, 비율 {fact_ratio:.1%}) — 수치(가격, 시간, 단위) 추가 권장")
    else:
        issues.append("AEO 구체적 팩트 데이터 거의 없음 — 숫자/가격/시간/브랜드명 추가 필수")
        critical.append("AEO 팩트 데이터 거의 없음 — 분량/시간/가격 등 구체 수치를 본문에 추가")

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

    # 10. 네이버 블로그 SEO 키워드 노출 및 스태핑 검사
    keyword = ""
    if "|" in title:
        keyword = title.split("|")[0].strip()
    else:
        keyword = title.strip()

    if keyword:
        # 특수문자 제거 후 글자만 매칭하여 공백 유연성 제공
        kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword)
        if kw_clean:
            # 검색 엔진처럼 각 글자 사이에 공백이 들어갈 수 있도록 정규식 생성
            kw_pattern = re.compile(r"\s*".join(re.escape(char) for char in kw_clean), re.IGNORECASE)
            
            # 본문에서 모든 마커(대괄호로 둘러싸인 항목)를 임시 제거하고 순수 텍스트 추출
            body_clean = re.sub(r'\[.*?\]', '', body).strip()
            
            # 첫 문단(300자 이내)에 키워드가 있는지 확인
            first_300 = body_clean[:300]
            if not kw_pattern.search(first_300):
                score -= 10
                msg = f"네이버 SEO 오류: 첫 300자 내 핵심 키워드('{keyword}')가 미배치됨"
                issues.append(msg)
                critical.append(msg + " — 도입부에 키워드 자연스럽게 1회 배치")

            # 키워드 반복 빈도 확인 (과다 반복 - 6회 초과 시 감점, 0회 시 감점)
            occurrences = len(kw_pattern.findall(body_clean))
            if occurrences > 6:
                score -= 10
                msg = f"네이버 SEO 오류: 핵심 키워드('{keyword}') 과다 반복 ({occurrences}회, 권장 3~5회)"
                issues.append(msg)
                critical.append(f"키워드('{keyword}') 과다 반복 {occurrences}회 → 3~5회로 줄이고 대명사·동의어로 대체")
            elif occurrences == 0:
                score -= 10
                msg = f"네이버 SEO 오류: 본문에 핵심 키워드('{keyword}')가 전혀 사용되지 않음"
                issues.append(msg)
                critical.append(f"핵심 키워드('{keyword}')를 본문에 3~5회 자연스럽게 사용")

    # 점수 범위 보정 (0~100)
    score = max(0, min(100, score))
    passed = score >= 60
    # 점수는 통과여도 수정 가능한 중대 이슈가 있으면 재생성을 권고(needs_retry).
    needs_retry = bool(critical)

    logger.info(
        f"품질 점수: {score}/100 ({'통과' if passed else '재생성 권장'}"
        f"{', 중대이슈 재생성권고' if (passed and needs_retry) else ''}) | 패턴: {pattern} | "
        f"본문 {body_len}자 | AI패턴 {ai_deduct//5}개 | "
        f"소제목 {len(subheadings)}개 | 데이터 {data_count}개"
    )
    if issues:
        logger.info(f"품질 이슈: {' / '.join(issues)}")
    if needs_retry:
        logger.info(f"중대(수정가능) 이슈: {' / '.join(critical)}")

    return {
        "score": score,
        "issues": issues,
        "critical": critical,
        "needs_retry": needs_retry,
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
            "pattern": pattern,
        },
    }
