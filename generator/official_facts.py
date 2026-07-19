"""법정 고시값 정적 DB 주입기 (2026-07-19 신설, 사용자 승인 — 오류 원천 차단 설계).

배경: 2026-07-19 점검에서 오류 3건(청약 가점·중위소득·세율 구간)의 공통 원인이
'모델이 학습 기억으로 고시값을 추정'하는 것으로 확정. 검증기(LLM)도 같은 한계를 보임.
→ 해결은 프롬프트가 아니라 구조: 검증된 고시값을 생성 시 항상 팩트로 주입해
   기억에 의존할 일 자체를 없앤다.

- DB: data/official_facts_2026.json (검증값만 수록, verified/next_review 메타 포함)
- 주입: lookup_block(keyword, extra_terms) → 트리거 매칭 항목을 팩트 블록 문자열로
- 갱신: next_review 경과 항목은 quality_audit가 주간 이슈에 리마인드
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("official_facts")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "official_facts_2026.json")
KST = timezone(timedelta(hours=9))


def _load() -> dict:
    try:
        db = json.load(open(_DB_PATH, encoding="utf-8"))
        db.pop("_meta", None)
        return db
    except Exception as e:
        logger.warning(f"고시값 DB 로드 실패: {e}")
        return {}


def lookup_block(keyword: str, extra_terms: str = "") -> str:
    """키워드(+카테고리 등 부가 문자열)에 트리거가 걸리는 고시값을 팩트 블록으로 반환.
    매칭 없으면 빈 문자열."""
    text = f"{keyword} {extra_terms}"
    hits = []
    for name, entry in _load().items():
        if any(t in text for t in entry.get("triggers", [])):
            lines = [f"■ {k}: {v}" for k, v in entry.get("facts", {}).items()]
            src = entry.get("source", "")
            hits.append(f"[{name}] (출처: {src}, 검증 {entry.get('verified', '')})\n" + "\n".join(lines))
    if not hits:
        return ""
    logger.info(f"고시값 DB 주입: {len(hits)}개 항목 매칭 ({keyword!r})")
    return ("[법정 고시값 — 아래 값은 공식 검증본이다. 관련 수치는 반드시 이 값을 문자 그대로 사용하고, "
            "여기 없는 고시값은 학습 기억으로 추정하지 마라]\n" + "\n\n".join(hits) + "\n\n")


def overdue_reviews() -> list[str]:
    """재검토 기한이 지난 항목 이름 목록 — 주간 품질 감사가 갱신 리마인드에 사용."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [name for name, e in _load().items()
            if e.get("next_review", "9999-12-31") < today]
