"""WP 주제 풀 주간 자동 갱신 (2026-07-19, 사용자 지시 — 매일 1건 전환에 따른 소진 대응).

미발행 주제가 MIN_UNPOSTED(21) 미만이면, 잔여가 적은 허브부터 Gemini 검색 그라운딩으로
신규 주제를 리서치해 data/wp_topic_pool_extra.json에 추가한다(회당 최대 MAX_NEW).
- facts는 검색 근거가 확인된 수치만(불확실 수치는 넣지 않음 — 규칙 3-3과 동일 철학)
- 기존 keyword/slug와 중복 금지, deep_content가 그대로 쓰는 _t() 필드 구조로 저장
실행: EC2 주 1회(run_wp_refresh.sh). 수동: python -m scripts.wp_topic_refresh
"""
import json
import logging
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from generator.content import _gen_text
from generator.wp_topics import TOPICS, HUB_BY_WEEKDAY, hub_display

EXTRA_PATH = os.path.join(ROOT, "data", "wp_topic_pool_extra.json")
HIST_PATH = os.path.join(ROOT, "data", "wp_post_history.json")
MIN_UNPOSTED = 21   # 3주 버퍼
MAX_NEW = 8         # 회당 상한

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wp_topic_refresh")

_HUB_THEMES = {
    "pension-tax": "연금·절세 설계 (ISA·연금저축·IRP·퇴직연금·비과세 제도)",
    "insurance-risk": "보험·리스크 설계 (실손·정기·암·운전자·보험 리모델링)",
    "loan-credit": "대출·신용 전략 (주담대·전세대출·신용점수·대환·중도상환)",
    "tax-refund": "세금·환급 가이드 (연말정산·종소세·양도세·증여·공제)",
    "policy-benefit": "제도·복지 해설 (정부지원금·바우처·청년·신혼부부 정책)",
    "housing-plan": "주거·청약 전략 (청약·특공·전세안전·재개발·주거 지원)",
}


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _gen_topic(hub_id: str, existing_kw: list[str], api_key: str) -> dict | None:
    prompt = (
        f"한국 금융·생활정보 블로그의 '{_HUB_THEMES[hub_id]}' 허브에 넣을 심층분석 글 주제 1개를 "
        "검색으로 리서치해서 만들어라.\n"
        f"[이미 있는 주제 — 겹치면 안 됨]\n{', '.join(existing_kw[:60])}\n\n"
        "요구사항:\n"
        "- 2026년 한국 기준 검색 수요가 있는 실용 주제(제도·상품·전략). 뉴스성 아닌 에버그린.\n"
        "- facts: 검색으로 확인된 핵심 수치·조건 5~8개(키: 한글 짧은 라벨). "
        "★확인 안 되는 수치는 절대 넣지 말 것 — 넣은 값은 전부 근거가 있어야 한다.\n"
        "- key_stats: facts 중 대표 수치 4개, [값, 라벨] 쌍.\n"
        "- sources: 실제 공식 출처 2개, [설명, URL] 쌍(law.go.kr·nts.go.kr·기관 공식 등).\n"
        "- slug: 영문 소문자-하이픈 3~5단어.\n"
        "JSON 한 개만 출력:\n"
        '{"keyword": "…", "slug": "…", "facts": {…}, "key_stats": [[값,라벨]×4], '
        '"sources": [[설명,URL]×2], "naver_overlap": ["…","…"]}'
    )
    raw = _gen_text(api_key, prompt, "너는 금융 콘텐츠 리서처다. 검색 근거 수치만 쓰고 JSON만 출력한다.",
                    4096, 0.6, use_search=True)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        t = json.loads(m.group(0))
    except Exception:
        return None
    slug = str(t.get("slug", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,6}", slug):
        return None
    if not (t.get("keyword") and isinstance(t.get("facts"), dict) and len(t["facts"]) >= 4):
        return None
    t["slug"], t["hub_id"] = slug, hub_id
    return t


def run():
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        logger.error("GOOGLE_API_KEY 없음")
        return
    posted = set(_load(HIST_PATH, {}).keys())
    extra = _load(EXTRA_PATH, {})
    unposted = [tid for tid in TOPICS if tid not in posted]
    need = min(MAX_NEW, max(0, MIN_UNPOSTED - len(unposted)))
    logger.info(f"주제 풀: 총 {len(TOPICS)} / 미발행 {len(unposted)} / 보충 필요 {need}")
    if need == 0:
        return
    # 잔여가 적은 허브부터 보충
    hub_remaining = {h: sum(1 for tid in unposted if TOPICS[tid]["hub_id"] == h)
                     for h in HUB_BY_WEEKDAY.values()}
    order = sorted(hub_remaining, key=lambda h: hub_remaining[h])
    existing_kw = [t["keyword"] for t in TOPICS.values()]
    existing_slugs = {t["slug"] for t in TOPICS.values()}
    added = 0
    i = 0
    while added < need and i < need * 3:
        hub = order[i % len(order)]
        i += 1
        t = _gen_topic(hub, existing_kw, api_key)
        if not t or t["slug"] in existing_slugs or t["keyword"] in existing_kw:
            continue
        tid = re.sub(r"[^a-z0-9]+", "_", t["slug"])
        if tid in TOPICS or tid in extra:
            continue
        t["auto"] = True
        extra[tid] = t
        existing_kw.append(t["keyword"])
        existing_slugs.add(t["slug"])
        added += 1
        logger.info(f"신규 주제 +[{hub_display(hub)}] {t['keyword']} ({t['slug']})")
    if added:
        json.dump(extra, open(EXTRA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        logger.info(f"저장: +{added}개 → {EXTRA_PATH}")


if __name__ == "__main__":
    run()
