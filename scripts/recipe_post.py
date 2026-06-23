"""
'오늘의 집밥 레시피' 자동 포스팅 — daily_post.py 와 같은 포스터를 재사용,
카테고리='오늘의 집밥 레시피' 로 발행. 별도 시간대(KST 17:00)에 실행.
GitHub Actions: python -m scripts.recipe_post
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
HISTORY_PATH = os.path.join(DATA_DIR, "recipe_history.json")
CATEGORY = "오늘의 집밥 레시피"

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "recipe_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("recipe_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_today(history: list) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return any(h.get("date") == today and h.get("status") == "posted" for h in history)


def _recent_dishes(history: list, days: int = 14) -> list[str]:
    cutoff = datetime.now(KST) - timedelta(days=days)
    out = []
    for h in history:
        try:
            ts = datetime.fromisoformat(h.get("timestamp", ""))
            if ts > cutoff and h.get("dish"):
                out.append(h["dish"])
        except Exception:
            continue
    return out


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def run():
    logger.info("=" * 60)
    logger.info(f"레시피 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        return
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        return

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    if draft:
        logger.info("DRAFT=true — 임시저장 검증 모드 (공개 발행 안 함 / 이력 미기록)")
    history = _load_history()
    if _already_posted_today(history) and not force and not draft:
        logger.info("오늘 이미 레시피 포스팅 완료 — 건너뜀 (FORCE_POST=true 로 강제)")
        return

    # ── 1. 레시피 생성 (최근 14일 메뉴 회피) ──
    from generator.recipe import generate_recipe
    recent = _recent_dishes(history, days=14)
    logger.info(f"최근 14일 메뉴 {len(recent)}개 회피: {recent}")
    post = generate_recipe(GOOGLE_API_KEY, recent=recent)
    if not post:
        logger.error("레시피 생성 실패 — 종료")
        sys.exit(1)

    dish = post.get("dish", "")
    logger.info(f"메뉴: {dish} | 제목: {post['title']}")
    logger.info("===== 본문 전문 시작 =====\n" + post.get("body", "") + "\n===== 본문 전문 끝 =====")

    # ── 2. 이미지 수집 (5장) ──
    images: list[dict] = []
    image_keywords = post.get("image_keywords", [])
    if PEXELS_API_KEY:
        try:
            from generator.image import get_post_images
            images = get_post_images(
                keyword=dish or "korean home food",
                api_key=PEXELS_API_KEY,
                count=len(image_keywords) if image_keywords else 5,
                category="cooking",
                image_keywords=image_keywords if image_keywords else None,
            )
            logger.info(f"이미지 수집: {len(images)}장")
        except Exception as e:
            logger.warning(f"이미지 수집 실패 (무시): {e}")
    else:
        logger.info("PEXELS_API_KEY 없음 — 이미지 없이 진행")

    # ── 3. 포스팅 (카테고리=오늘의 집밥 레시피) ──
    from poster.naver_blog import post_to_naver_blog
    result = post_to_naver_blog(
        naver_id=NAVER_ID,
        naver_pw=NAVER_PW,
        blog_id=NAVER_BLOG_ID or NAVER_ID,
        title=post["title"],
        body=post["body"],
        tags=post["tags"],
        naver_cookies=NAVER_COOKIES,
        images=images if images else None,
        draft=draft,
        allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
        table_str=post.get("table_str", ""),
        subheadings=post.get("subheadings", []),
        faq_questions=post.get("faq_questions", []),
        category=CATEGORY,
    )

    if draft:
        if result:
            logger.info(f"[DRAFT] 임시저장 결과: {result.get('post_url')} | 이미지 {result.get('images_inserted')}장")
        else:
            logger.error("[DRAFT] 포스팅 함수 None 반환 — 로그/스크린샷 확인")
        logger.info("[DRAFT] 이력 미기록 — 검증 모드 종료")
        return

    # ── 4. 이력 저장 ──
    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)
    entry = {
        "date":            datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp":       datetime.now(KST).isoformat(),
        "dish":            dish,
        "title":           post["title"],
        "tags":            post["tags"],
        "category":        CATEGORY,
        "status":          "posted" if is_posted else "failed",
        "post_url":        post_url if is_posted else None,
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table":       bool(post.get("table_str")),
        "has_faq":         bool(post.get("faq_str")),
    }
    history.insert(0, entry)
    _save_history(history[:200])

    if is_posted:
        logger.info(f"레시피 포스팅 완료: {post_url}")
    else:
        logger.error(f"레시피 포스팅 실패 — 쿠키 만료/발행 오류 의심. URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
