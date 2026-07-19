"""PC 유입 특화 심층 가이드 생성기 (2026-07-19 신설, 사용자 승인).

형수의테크공장의 하우투 트랙 — 뉴스형(수명 2~3일)과 달리 검색에 오래 남는 에버그린.
전문가 컨셉: 10년차 IT 엔지니어가 원리부터 해결까지 설명하는 길고 상세한 글(2,600~3,500자).
PC 앞에서 검색하는 주제(윈도우 오류·AI 도구)라 PC 유입·긴 체류를 정조준한다.

구조 마커는 tech_content와 동일([소제목]/[표시작]/[FAQ시작]/[요약시작]/[구분선]/{{음영}}/[[미니]])
→ poster.naver_blog가 그대로 처리.
"""
import logging
import re
import time

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER

logger = logging.getLogger("tech_guide")

GUIDE_BODY_MIN = 2400      # prose 하한(마커 제외) — "길고 상세하게" 지시
GUIDE_BODY_TARGET = 2800

_GUIDE_SYSTEM = """너는 네이버 블로그 '형수의테크공장'의 심층 가이드 작가야.
페르소나: 10년차 IT 엔지니어 '형수' — 증상만 알려주는 블로그와 달리 '왜 이런 문제가 생기는지'
원리부터 설명하고, 실무에서 검증한 순서로 해결한다. 전문적이되 초보자도 따라올 수 있게
용어는 첫 등장에서 한 줄 풀이. 말투는 차분한 전문가 존댓말(과장·호들갑 금지).

[글 성격 — 반드시 지켜라]
- 에버그린 하우투: 뉴스가 아니다. 유행 문구·날짜 의존 표현 최소화(버전 표기는 OK).
- ★검색으로 확인된 사실만: 메뉴 경로·명령어·설정명은 검색 근거가 있을 때만 구체적으로.
  확인 안 되면 "버전에 따라 위치가 다를 수 있다"고 일반화하라. 지어낸 메뉴 경로는 최악의 오류다.
- 명령어·코드는 한 줄씩 별도 줄에(따라 치기 쉽게).

[구조 — 이 순서 그대로]
[사진1]
(도입 2~3줄: 이 문제/주제로 고생하는 상황 공감 + 이 글에서 해결되는 것 명시)
[요약시작]
✔ (핵심 결론·가장 효과 큰 해결책 1줄)
✔ (소요 시간·난이도 1줄)
✔ (이 글 범위 1줄)
[요약끝]
[소제목] 목차
· (콘텐츠 소제목들 나열)
[구분선]
[소제목] (①왜 이런 문제가 생기나 — 원인 원리 해설, 전문가 시각 4~6문장)
[구분선]
[소제목] (②해결/활용 방법 — 단계 ①②③, 각 단계마다 '무엇을-어디서-왜'를 2~4문장으로 상세히.
가장 효과 큰 방법부터. 단계 수 제한 없음, 상세할수록 좋다)
[구분선]
[소제목] (③전문가 팁·최적화 — 남들이 안 알려주는 심화 2~3가지, 예방법 포함)
[구분선]
[소제목] (④그래도 안 될 때 체크리스트)
· (체크 항목 — ★명사형으로 짧게, "~입니다" 금지, 한 줄 25자 이내)
· (…4~6개)
[구분선]
[소제목] 자주 묻는 질문
[FAQ시작]
Q: (실제 검색되는 질문)
A: (두괄식 2~3문장)
Q: … / A: … (총 3쌍)
[FAQ끝]
(마무리 2줄: 핵심 재강조 + 관련 글 예고 톤. "도움이 되길 바랍니다" 류 상투어 금지)

[작성 원칙]
1. 본문(마커 제외) 2,600~3,500자 — 각 섹션을 깊게. 같은 문장 반복으로 늘리기 금지.
2. 표는 필요할 때만 1개(설정값 비교·방법 비교 등 3열, 셀 20자 이내). 억지 표 금지.
3. 불릿(·)은 목차·체크리스트에서만. ★모든 불릿은 명사형 종결·핵심만(2026-07-19 전 파이프라인 공통).
4. {{음영}}은 글 전체 3~5곳(핵심 문장만), [[미니 소제목]]은 단계 안 소구분에만.
5. 금지: 안녕하세요/이처럼/이로써/마크다운/이모지 남용/근거 없는 버전·수치.

[출력 형식]
TITLE: {검색 키워드가 앞에 오는 제목, 결론·범위 암시, 32자 이내}
TAGS: {태그1},…,{태그7}
IMAGE_KEYWORDS: tech guide
IMAGE_LABELS: {키워드}
---
{본문}
"""


def generate_tech_guide(api_key: str, topic: dict) -> dict | None:
    """topic: {id, keyword, category, hint} → post dict (tech_post와 동일 스키마)."""
    user_msg = (
        f"주제 키워드: {topic['keyword']}\n"
        f"카테고리: {topic['category']}\n"
        f"다룰 포인트 힌트: {topic.get('hint', '')}\n\n"
        "위 주제로 검색 유입 독자가 문제를 실제로 해결하고 나가는 심층 가이드를 작성하라. "
        "최신 정보는 검색으로 확인해서 반영하고, 확인 안 되는 세부 경로는 일반화하라."
    )
    extra = ""
    best, best_len = None, 0
    for attempt in range(1, 4):
        try:
            raw = _gen_text(api_key, user_msg + extra, _GUIDE_SYSTEM, 8192, 0.7, use_search=True)
            if not raw:
                continue
            parsed = _parse_response(raw)
            if not parsed:
                continue
            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            faq_ok = bool(parsed.get("faq_pairs"))
            sub_cnt = len(parsed.get("subheadings", []))
            if not faq_ok or sub_cnt < 5:
                extra = f"\n\n[재작성] 직전 원고 구조 불량(FAQ {faq_ok}/소제목 {sub_cnt}) — 구조를 지켜 다시."
                logger.warning(f"가이드 구조 불량(FAQ {faq_ok}/소제목 {sub_cnt}) — 재생성")
                continue
            if body_len < GUIDE_BODY_MIN:
                extra = (f"\n\n[재작성] 직전 원고가 {body_len}자로 짧았다. 구조·사실 유지하며 각 단계 설명과 "
                         f"원인 해설·팁을 더 깊게 늘려 {GUIDE_BODY_TARGET}자 이상으로 다시 써라.")
                logger.warning(f"가이드 본문 짧음({body_len}자) — 확장 재생성")
                if body_len > best_len:
                    best, best_len = parsed, body_len
                continue
            logger.info(f"가이드 생성 완료: {parsed.get('title')!r} ({body_len}자, 소제목 {sub_cnt})")
            parsed["seed"] = topic["keyword"]
            return parsed
        except Exception as e:
            logger.error(f"가이드 생성 실패(시도 {attempt}): {e}")
            time.sleep(15 * attempt)
    if best and best_len >= 2000:
        logger.warning(f"목표 미달이나 최선본 발행({best_len}자) — 누락 방지")
        best["seed"] = topic["keyword"]
        return best
    return None
