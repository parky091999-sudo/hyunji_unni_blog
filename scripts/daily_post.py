"""
매일 자동 포스팅 메인 스크립트
GitHub Actions: python -m scripts.daily_post
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR, LOG_DIR,
    GOOGLE_API_KEY, PEXELS_API_KEY,
    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES,
)

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "post_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "daily_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_today(history: list) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return any(h.get("date") == today and h.get("status") == "posted" for h in history)


def _is_real_post_url(url: str | None) -> bool:
    """실제 게시된 포스트 URL인지 확인 (숫자 ID 포함, 에디터 URL 아님)"""
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def run():
    logger.info("=" * 50)
    logger.info(f"일일 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 50)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        return
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        return

    history = _load_history()
    if _already_posted_today(history):
        logger.info("오늘 이미 포스팅 완료 — 건너뜀")
        return

    # 1. 키워드 선정
    from generator.keyword import pick_keyword, get_trending_bonus
    keyword  = pick_keyword()
    trending = get_trending_bonus()
    logger.info(f"키워드: {keyword!r} | 트렌딩: {trending[:3]}")

    # 2. 글 생성
    from generator.content import generate_post
    post = generate_post(keyword, api_key=GOOGLE_API_KEY, trending=trending)
    if not post:
        logger.error("글 생성 실패 — 종료")
        return

    logger.info(f"제목: {post['title']}")
    logger.info(f"태그: {post['tags']}")
    if post.get("coupang_hints"):
        logger.info(f"쿠팡 힌트: {post['coupang_hints']}")

    # 3. 포스팅
    from poster.naver_blog import post_to_naver_blog
    result = post_to_naver_blog(
        naver_id=NAVER_ID,
        naver_pw=NAVER_PW,
        blog_id=NAVER_BLOG_ID or NAVER_ID,
        title=post["title"],
        body=post["body"],
        tags=post["tags"],
        naver_cookies=NAVER_COOKIES,
    )

    # 4. 이력 저장
    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)
    now_str = datetime.now(KST).isoformat()
    entry = {
        "date":      datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": now_str,
        "keyword":   keyword,
        "title":     post["title"],
        "tags":      post["tags"],
        "status":    "posted" if is_posted else "failed",
        "post_url":  post_url if is_posted else None,
    }
    history.insert(0, entry)
    _save_history(history[:200])

    if result:
        logger.info(f"포스팅 완료: {result.get('post_url')}")
    else:
        logger.warning("포스팅 실패")


if __name__ == "__main__":
    run()
