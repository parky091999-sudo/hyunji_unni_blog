"""
심층분석 생성 → 렌더 → 워드프레스 발행 (WP_PIPELINE.md §5 B·C).

주 4회(월·화·목·토) 허브별 로테이션 + 네이버 최근 7일 키워드 회피.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import GOOGLE_API_KEY, WP_URL, DATA_DIR
from generator.deep_content import generate_deep_post
from generator.wp_render import render_wordpress_post
from generator.wp_topics import (
    TOPICS, HUB_BY_WEEKDAY, ALT_HUB_BY_WEEKDAY, CATEGORY_HUBS, hub_display,
)
from poster.wp_publish import publish_wordpress, check_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_post")

KST = timezone(timedelta(hours=9))
_HISTORY_PATH = os.path.join(DATA_DIR, "wp_post_history.json")
_NAVER_HISTORY_FILES = [
    "gov_history.json",
    "info_금융재테크_history.json",
    "info_세금절세_history.json",
    "info_보험_history.json",
    "info_부동산주거_history.json",
]


def _load_history() -> dict:
    if os.path.exists(_HISTORY_PATH):
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_history(hist: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _naver_keywords_last_n_days(days: int = 7) -> set[str]:
    """네이버 최근 N일 발행 키워드(부분일치용)."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out: set[str] = set()
    for fname in _NAVER_HISTORY_FILES:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
            for row in rows:
                if row.get("date", "") >= cutoff and row.get("status") == "posted":
                    kw = (row.get("keyword") or "").strip()
                    if kw:
                        out.add(kw)
        except Exception as e:
            logger.warning(f"네이버 이력 읽기 실패 {fname}: {e}")
    return out


def _overlaps_naver(topic: dict, naver_kws: set[str]) -> bool:
    if not naver_kws:
        return False
    needles = topic.get("naver_overlap") or [topic.get("keyword", "")]
    for needle in needles:
        n = (needle or "").strip()
        if not n:
            continue
        for kw in naver_kws:
            if n in kw or kw in n:
                return True
    return False


def _hub_for_today() -> str:
    """오늘 KST 요일 기준 허브. 환경변수 WP_HUB 우선."""
    forced = os.environ.get("WP_HUB", "").strip()
    if forced:
        return forced
    now = datetime.now(KST)
    wd = now.weekday()
    hub = HUB_BY_WEEKDAY.get(wd)
    if hub is None:
        return ""
    # 월·토 짝수주에 교차 허브
    if wd in ALT_HUB_BY_WEEKDAY and (now.isocalendar().week % 2 == 0):
        return ALT_HUB_BY_WEEKDAY[wd]
    return hub


# 같은 주제 재발행 최소 주기(일) — 풀이 소진돼도 이보다 이르게 같은 글을 다시 쓰지 않는다.
# (2026-07-10 사용자 결정: 최소 1년 — 주제 다양성이 유입 다양성. 풀 확장은 주간 제안 파이프라인이 담당.)
REPUBLISH_MIN_DAYS = int(os.environ.get("WP_REPUBLISH_MIN_DAYS", "365"))


def _pick_topic(hist: dict, hub_id: str | None = None) -> str:
    """허브 내 미발행·오래된 주제, 네이버 중복 회피."""
    naver_kws = _naver_keywords_last_n_days(7)
    candidates = []
    for tid, meta in TOPICS.items():
        if hub_id and meta.get("hub_id") != hub_id:
            continue
        if _overlaps_naver(meta, naver_kws):
            logger.info(f"네이버 7일 중복 회피: {tid}")
            continue
        last = hist.get(tid, "")
        candidates.append((tid, last or ""))
    if not candidates:
        # 허브 필터 실패 시 전체 풀에서 재시도(중복만 회피)
        for tid, meta in TOPICS.items():
            if _overlaps_naver(meta, naver_kws):
                continue
            candidates.append((tid, hist.get(tid, "") or ""))
    if not candidates:
        raise RuntimeError("선택 가능한 WP 주제 없음(전부 네이버 중복 또는 소진)")
    never = [t for t, d in candidates if not d]
    if never:
        return never[0]
    return min(candidates, key=lambda x: x[1])[0]


def _related_for(topic_id: str, category: str, hist: dict) -> list[dict]:
    out = []
    for tid, meta in TOPICS.items():
        if tid == topic_id or meta.get("category") != category:
            continue
        if tid not in hist:
            continue
        slug = meta.get("slug") or tid.replace("_", "-")
        out.append({"title": meta.get("keyword", tid), "slug": slug})
    return out[:3]


def run():
    topic_id = os.environ.get("WP_TOPIC", "").strip().lower()
    status = os.environ.get("WP_STATUS", "draft").strip().lower()
    hist = _load_history()

    # 하루 1건 가드 (2026-07-12): 크론 지연분·수동 실행이 겹쳐 같은 날 2건(동일 카테고리)
    # 발행된 사고 방지. 수동 재실행이 필요하면 WP_FORCE=true.
    if os.environ.get("WP_FORCE", "").lower() != "true":
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if any(d == today for d in hist.values()):
            logger.info(f"오늘({today}) 이미 발행됨 — 하루 1건 가드로 스킵 (강제: WP_FORCE=true)")
            return

    if not topic_id:
        hub_id = _hub_for_today()
        if hub_id:
            logger.info(f"오늘 허브: {hub_id} ({hub_display(hub_id)})")
        topic_id = _pick_topic(hist, hub_id or None)
        logger.info(f"WP_TOPIC 자동 선택: {topic_id}")
        # 재발행 최소주기 가드 — 자동 선택에만 적용(수동 WP_TOPIC 지정은 의도된 갱신)
        last = hist.get(topic_id, "")
        if last:
            days = (datetime.now(KST).date() - datetime.strptime(last, "%Y-%m-%d").date()).days
            if days < REPUBLISH_MIN_DAYS:
                logger.info(
                    f"풀 소진 — '{topic_id}' 최근 발행 {days}일 전(최소 {REPUBLISH_MIN_DAYS}일). "
                    f"오늘 발행 스킵. 주제 풀 확장 필요(제안 이슈 확인)."
                )
                return
    topic = TOPICS.get(topic_id)
    if not topic:
        logger.error(f"알 수 없는 WP_TOPIC: {topic_id!r}")
        sys.exit(1)
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)
    if not check_connection():
        logger.error("WP 연결 실패")
        sys.exit(1)

    logger.info(f"[{status}] 심층분석 생성: {topic_id} / {topic['category']}")
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("생성 실패")
        sys.exit(1)

    related = _related_for(topic_id, topic["category"], hist)
    slug = topic.get("slug") or topic_id.replace("_", "-")
    post_url = f"{WP_URL.rstrip('/')}/{slug}/"
    hub_meta = CATEGORY_HUBS.get(topic.get("hub_id", ""), {})
    r = render_wordpress_post(
        post, category=topic["category"], base_url=post_url,
        slug_override=slug, related_posts=related,
        site_url=WP_URL, category_slug=hub_meta.get("slug", ""),
    )
    logger.info(f"제목: {post['title']} · slug: {r['slug']} · html {len(r['content_html'])}자")

    res = publish_wordpress(r, title=post["title"], status=status, category=topic["category"])
    if not res:
        logger.error("발행 실패")
        sys.exit(1)
    logger.info(f"발행 완료 [{res['status']}] id={res['id']} {res['link']}")

    # 대표 이미지(일러스트+타이틀) — 실패해도 발행은 유지(best-effort)
    try:
        from scripts.wp_set_featured import process_topic
        logger.info(f"대표 이미지: {process_topic(topic_id)}")
    except Exception as e:
        logger.warning(f"대표 이미지 생성 실패(무시): {e}")

    if status == "publish":
        hist[topic_id] = datetime.now(KST).strftime("%Y-%m-%d")
        _save_history(hist)


if __name__ == "__main__":
    run()
