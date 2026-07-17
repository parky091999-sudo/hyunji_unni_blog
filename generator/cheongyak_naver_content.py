"""청약 공고 건별 분석 — 네이버(현지언니) 버전 생성기 (2026-07-17 사용자 지시: WP와 동급).

WP(cheongyak_post)와 같은 팩트(공고 API+공고문 발췌+실거래)를 쓰되, 네이버 SE ONE 검증
구조로 출력: 요약블록(버티컬 인용구) + 소제목(회색바) + 3열 표 + FAQ 인용구 + 모바일 스캔형
단락. 출력 마커는 content._parse_response 포맷 그대로.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from generator.content import _gen_text, _parse_response, _IMAGE_MARKER

logger = logging.getLogger("cheongyak_naver")

NAVER_BODY_MIN = 1300   # 안전망(미달 시 재생성)
NAVER_BODY_TARGET = 1800

_SYSTEM = """\
너는 네이버 블로그 '현지언니'다. 놓치기 쉬운 돈·혜택 정보를 직접 발품 팔아 쉽게 정리해주는
똑부러진 28세 생활정보 언니. 친근하되 정확·신뢰가 최우선. 독자에게 존댓말(~해요/~습니다 혼용,
~해요체 위주)로 쓴다. "제가 공고문을 직접 뜯어봤는데요" 같은 1인칭 경험은 자연스럽게 1~2번만.

[절대 원칙]
1. 아래 [팩트 데이터]에 있는 수치·일정만 단정해서 쓴다. 없는 수치는 지어내지 말고 '모집공고문
   확인'으로 처리. 검색으로 보강한 시세·여건은 반드시 "~로 알려져 있어요" 톤(단정 금지).
2. 금지어: 안녕하세요/이처럼/이로써/혁신적인/극대화. 마크다운(**, #), HTML 태그, 이모지 금지.
3. 단락은 2~3줄(모바일 스캔형). 한 문장은 짧게. 소제목 바로 다음 첫 문장은 그 소제목 질문에
   바로 답하는 두괄식 결론.
4. 소제목은 줄 맨 앞 [소제목] 마커 + 한 줄. 소제목 텍스트에 번호·기호(1./①②③/④) 절대
   붙이지 않는다 — 아래 구조의 ①~⑦은 순서 안내일 뿐이니 텍스트로 옮기지 마라.
5. 목록 항목 줄은 '· '(가운뎃점+공백)로 시작. 상위 라벨은 [[라벨]] 형태로 글머리 없이 한 줄,
   세부 항목만 그 아래 · 불릿(상위·하위 같은 글머리 금지). [[라벨]]은 발행 시 작은 소제목으로
   꾸며진다.
5-1. ★글 전체에서 독자가 꼭 기억해야 할 가장 중요한 문장 3~5개는 그 줄 전체를 {{ }}로 감싸라
   (예: "{{계약금만 최소 1억 5천만 원이 필요해요.}}"). 발행 시 음영(형광펜) 처리된다.
   줄 전체 단위로만 사용하고, 문장 중간 일부에는 쓰지 마라.
6. 표는 [표시작]~[표끝], 각 줄 " | " 구분, 3열, 헤더 1행 + 데이터 3~5행, 셀은 15자 이내.
7. 확정 안 된 것(경쟁률 전망 등)은 "~로 보여요/~할 것 같아요" 개인 의견 톤으로.

[출력 형식 — 반드시 정확히]
TITLE: {단지명 포함, 후킹 제목 30자 이내}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6}
IMAGE_KEYWORDS: apartment
IMAGE_LABELS: {단지명}
---
[사진1]
(도입 2~3문단 — 어떤 공고인지, 왜 주목할 만한지 두괄식으로. 뻔한 배경설명 금지)

[요약시작]
· (청약 일정 핵심 1줄 — 날짜 포함)
· (분양가·필요 현금 핵심 1줄 — 수치 포함)
· (현지언니 판단 1줄 — 해볼 만하다/조건부 추천/보류 중 하나)
[요약끝]

[소제목] (①어떤 단지인지 — 위치·규모·시공사)
...

[소제목] (②청약 일정 — 아래 표 포함)
[표시작]
구분 | 일정 | 비고
...
[표끝]

[소제목] (③현금이 얼마나 필요한지 — 공고문 발췌의 계약금·중도금 조건 근거 계산)

[소제목] (④어떤 타입이 유리한지 — 세대수·면적·가격 비교, 필요하면 표 1개 더)

[소제목] (⑤신청 전 체크 — 특별공급·1순위 요건·규제를 [[라벨]]+불릿 계층으로)

[소제목] (⑥가격은 적당한지 — 실거래 데이터가 팩트에 있으면 그것을 1순위 근거로 분양가와
비교, 없으면 '~로 알려져 있어요' 톤)

[소제목] 현지언니의 판단
(첫 문장에서 [해볼 만하다/조건부 추천/보류] 중 하나를 명확히. 근거 3개 불릿.
[[이런 분께 맞아요]] 라벨 + 하위 불릿 2~3개, [[이런 분은 보류가 좋아요]] 라벨 + 하위 불릿 2~3개.
마지막에 '최종 판단 전 입주자모집공고문 원문 꼭 확인' 면책 1줄)

[FAQ시작]
Q: (독자가 실제로 궁금해할 질문)
A: (두괄식 답)
Q: ...
A: ...
[FAQ끝]
"""


def generate_cheongyak_naver_post(topic: dict, api_key: str) -> dict | None:
    """topic(=cheongyak_post와 동일 facts/keyword) → 네이버 발행용 post dict."""
    facts_json = json.dumps(topic.get("facts", {}), ensure_ascii=False, indent=2, default=str)
    user_msg = (
        f"단지: {topic.get('keyword', '')}\n\n"
        f"[팩트 데이터 — 이 수치만 사용, 추가·변조 금지]\n{facts_json}\n\n"
        "위 팩트로 청약 분석글을 작성해 주세요. 본문(마커 제외) 1,800~2,400자. "
        "각 소제목 섹션 3~6줄로 충실히."
    )
    feedback = ""
    best, best_len = None, 0
    for attempt in range(1, 4):
        try:
            raw = _gen_text(api_key, user_msg + feedback, _SYSTEM, 8192, 0.3, use_search=True)
            if not raw:
                continue
            parsed = _parse_response(raw)
            if not parsed:
                continue
            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            if body_len > best_len:
                best, best_len = parsed, body_len
            if body_len >= NAVER_BODY_MIN and (body_len >= NAVER_BODY_TARGET or attempt == 3):
                break
            feedback = (
                f"\n\n[재작성] 직전 원고가 {body_len}자로 짧았어요. 사실 왜곡 없이 각 섹션을 "
                "더 충실히(계산 과정·비교·해석 추가) 1,800자 이상으로 다시 써 주세요."
            )
            logger.info(f"본문 {body_len}자 — 재생성 {attempt}/3")
        except Exception as e:
            logger.warning(f"네이버 청약글 생성 실패(시도 {attempt}): {e}")
    if best is None or best_len < NAVER_BODY_MIN:
        logger.error(f"네이버 청약글 생성 실패(최장 {best_len}자)")
        return None
    logger.info(
        f"네이버 청약글 생성 완료: {best.get('title')!r} ({best_len}자, "
        f"소제목 {len(best.get('subheadings', []))}, 표 {len(best.get('table_strs', []))}, "
        f"FAQ {len(best.get('faq_pairs', []))}, 요약 {bool(best.get('summary_text'))})"
    )
    return best
