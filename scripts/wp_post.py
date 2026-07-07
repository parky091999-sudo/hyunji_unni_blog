"""
심층분석 생성 → 렌더 → 워드프레스 발행 (WP_PIPELINE.md §5 B·C).

DRY_RUN(scripts/wp_dry)과 달리 실제 WP에 글을 올린다.
매일 9시 자동발행(2026-07-08~) 전제 — WP_TOPIC 미지정 시 이력 기반 자동 로테이션
(가장 오래전에 쓴 주제, 또는 아직 안 쓴 주제 우선 — 네이버 info_post 패턴 재사용).

실행:
  WP_TOPIC=isa WP_STATUS=draft   python -m scripts.wp_post   (주제 지정 + 임시저장)
  WP_STATUS=publish              python -m scripts.wp_post   (자동 로테이션 + 실발행 — 크론 기본)
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

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
from poster.wp_publish import publish_wordpress, check_connection
from scripts.wp_dry import TOPICS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_post")

KST = timezone(timedelta(hours=9))
_HISTORY_PATH = os.path.join(DATA_DIR, "wp_post_history.json")


def _load_history() -> dict:
    if os.path.exists(_HISTORY_PATH):
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_history(hist: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def _pick_topic(hist: dict) -> str:
    """가장 오래전에 발행(또는 미발행)한 주제 선택 — 매일 다른 글이 나오도록 로테이션."""
    never_posted = [t for t in TOPICS if t not in hist]
    if never_posted:
        return never_posted[0]
    return min(hist, key=lambda t: hist[t])


def run():
    topic_id = os.environ.get("WP_TOPIC", "").strip().lower()
    status = os.environ.get("WP_STATUS", "draft").strip().lower()
    hist = _load_history()

    if not topic_id:
        topic_id = _pick_topic(hist)
        logger.info(f"WP_TOPIC 미지정 — 로테이션 자동 선택: {topic_id}")
    topic = TOPICS.get(topic_id)
    if not topic:
        logger.error(f"알 수 없는 WP_TOPIC: {topic_id!r} (가능: {list(TOPICS)})")
        sys.exit(1)
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not check_connection():
        logger.error("WP 연결 실패 — 종료")
        sys.exit(1)

    logger.info(f"[{status}] 심층분석 생성 시작: {topic_id}")
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("생성 실패 — 종료")
        sys.exit(1)

    r = render_wordpress_post(post, category=topic["category"], base_url=WP_URL)
    logger.info(f"제목: {post['title']}")
    logger.info(f"slug: {r['slug']} · content_html {len(r['content_html'])}자 · "
                f"목차 {'O' if r['toc_html'] else 'X'} · 핵심수치 {'O' if r['key_stats_html'] else 'X'}")

    res = publish_wordpress(r, title=post["title"], status=status, category=topic["category"])
    if not res:
        logger.error("발행 실패 — 종료")
        sys.exit(1)
    logger.info(f"===== 발행 완료 =====")
    logger.info(f"상태: {res['status']} · id: {res['id']}")
    logger.info(f"링크: {res['link']}")

    if status == "publish":
        hist[topic_id] = datetime.now(KST).strftime("%Y-%m-%d")
        _save_history(hist)
        logger.info(f"이력 저장: {topic_id} → {hist[topic_id]}")


if __name__ == "__main__":
    run()
