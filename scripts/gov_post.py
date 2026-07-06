"""
정부지원&혜택 카테고리 자동 포스팅 스크립트
GitHub Actions: python -m scripts.gov_post
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR, LOG_DIR,
    GOOGLE_API_KEY, PEXELS_API_KEY,
    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES,
)

KST = timezone(timedelta(hours=9))
BLOG_CATEGORY = "정부지원, 혜택"
HISTORY_PATH = os.path.join(DATA_DIR, "gov_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "gov_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("gov_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("posts", [])


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_this_run(history: list, run_slot: str) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("run_slot") == run_slot and h.get("status") == "posted":
            return True
    return False


def _get_recent_posted_keywords(history: list, days: int = 30) -> set:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {h["keyword"] for h in history if h.get("date", "") >= cutoff and h.get("keyword")}


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_internal_links(body: str, history: list) -> tuple:
    """같은 카테고리 최근 글 1~2개를 본문 끝에 가운데 정렬 링크로 추가"""
    related = [h for h in history if h.get("status") == "posted" and h.get("post_url") and h.get("title")][:2]
    if not related:
        return body, []

    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"

    return body + links_text, ["함께 보면 좋은 글"]


def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"정부지원 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    history = _load_history()

    if _already_posted_this_run(history, run_slot) and not force and not draft and not dry_run:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 정부지원 포스팅 완료 — 건너뜀")
        return

    # ── 1. 키워드 선정 ──
    from generator.keyword import pick_keyword_for_blog_category
    recent_kws = _get_recent_posted_keywords(history)

    # ★exclude로 풀 단계에서 자기 이력 제외 (DataLab 트렌딩 반복 반환 → 중복 발행 차단)
    kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
    keyword = kw_result["keyword"]
    gov_category = kw_result["category_name"]

    for _ in range(3):
        if keyword not in recent_kws:
            break
        logger.info(f"최근 발행 키워드 중복 ({keyword!r}) — 재선정")
        kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
        keyword = kw_result["keyword"]
        gov_category = kw_result["category_name"]

    logger.info(f"선정 키워드: {keyword!r} | 정부지원 카테고리: {gov_category}")

    # ── 2. 글 생성 ──
    from generator.content import generate_gov_post
    post = generate_gov_post(keyword=keyword, api_key=GOOGLE_API_KEY, gov_category=gov_category)

    if not post:
        logger.error("정부지원글 생성 실패 — 종료")
        sys.exit(1)

    # 안전장치: 헤더([사진1]) 외 본문 사진 마커([사진2]+)가 남아 있으면 제거 (리터럴 노출 방지)
    if post.get("body"):
        cleaned = re.sub(r"^\s*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        if cleaned != post["body"]:
            logger.info("본문 사진 마커 [사진2]+ 제거 (헤더카드만 사용)")
            post["body"] = cleaned

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 이미지 수집 ──
    images: list[dict] = []
    image_keywords = post.get("image_keywords", [])
    image_labels = post.get("image_labels", [])

    # 브랜드 헤더 카드 (images[0] = [사진1]) — HTML/CSS 인포그래픽 우선, 실패 시 PIL 폴백
    # (info_post.py의 4개 정보성 카테고리와 동일한 카드 시스템 — 정부지원도 정보성 글이라 통일)
    from generator.content import extract_summary_bullets
    bullets = extract_summary_bullets(post.get("summary_text", "")) or None
    header_path = None
    try:
        from poster.infographic_html import create_infographic_via_html
        header_path = create_infographic_via_html(
            title=post["title"], keyword=keyword, category="gov", bullets=bullets
        )
        if header_path:
            logger.info(f"HTML 인포그래픽 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"HTML 인포그래픽 실패 — PIL 폴백: {e}")

    if not header_path:
        try:
            from poster.naver_blog import create_info_infographic
            header_path = create_info_infographic(
                title=post["title"], keyword=keyword, category="gov", bullets=bullets
            )
            if header_path:
                logger.info(f"PIL 인포그래픽 생성 완료: {header_path}")
        except Exception as e:
            logger.warning(f"PIL 헤더 카드 생성 실패 (무시): {e}")

    if header_path:
        images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
        logger.info(f"정부지원 헤더 카드 완료 (불릿 {len(bullets) if bullets else 0}개)")

    # 정부지원 글은 헤더 카드만 사용 — Pexels 스톡사진 미수집(주제와 무관한 엉뚱한 사진 방지, 2026-06-30 사용자 요청).
    # 정보 전달이 핵심인 카테고리라 본문 사진 없이 표·요약블록·불릿으로 구성.
    logger.info("정부지원 글: 본문 스톡사진 생략 (헤더 카드만)")

    # 내부 링크 연계
    post["body"], extra_subs = _append_internal_links(post["body"], history)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

    # ── 4. 포스팅 ──
    from poster.naver_blog import post_to_naver_blog
    try:
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
            table_strs=post.get("table_strs", []),
            subheadings=post.get("subheadings", []),
            faq_questions=post.get("faq_questions", []),
            category=BLOG_CATEGORY,
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)

    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return

    # ── 5. 이력 저장 ──
    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)

    entry = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(KST).isoformat(),
        "run_slot": run_slot,
        "keyword": keyword,
        "gov_category": gov_category,
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table": bool(post.get("table_str")),
        "has_faq": bool(post.get("faq_str")),
    }

    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"정부지원 포스팅 완료: {post_url} | 이미지 {entry['images_inserted']}장")
    else:
        logger.error(f"정부지원 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
