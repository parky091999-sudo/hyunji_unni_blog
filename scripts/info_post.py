"""
고CPC 정보성 범용 포스팅 스크립트 (금융재테크·세금절세·보험·부동산주거).
카테고리는 환경변수 INFO_CATEGORY로 지정.
GitHub Actions: INFO_CATEGORY=금융재테크 python -m scripts.info_post
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
    GOOGLE_API_KEY,
    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES,
)

KST = timezone(timedelta(hours=9))

# INFO_CATEGORY(키워드풀 id) → 네이버 블로그 카테고리명
INFO_CAT_MAP = {
    "금융재테크": "금융, 재테크",
    "세금절세": "세금, 절세",
    "보험": "보험",
    "부동산주거": "부동산, 주거",
}

def _pick_least_recent_category() -> str:
    """스케줄 실행(카테고리 미지정) 시: 4개 정보 카테고리 중 가장 오래 전 발행(또는 미발행)된 카테고리 선택 → 고른 순환 발행."""
    best, best_ts = None, None
    for cid in INFO_CAT_MAP:
        path = os.path.join(DATA_DIR, f"info_{cid}_history.json")
        last = ""
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                posted = [h.get("timestamp", "") for h in data if h.get("status") == "posted"]
                last = max(posted) if posted else ""
        except Exception:
            last = ""
        # 미발행("")이 최우선, 그다음 가장 오래된 timestamp
        key = last or "0000"
        if best is None or key < best_ts:
            best, best_ts = cid, key
    return best or "금융재테크"


INFO_CAT_ID = os.environ.get("INFO_CATEGORY", "").strip()
if not INFO_CAT_ID or INFO_CAT_ID == "auto":
    INFO_CAT_ID = _pick_least_recent_category()
    print(f"[자동 순환] 카테고리 선택: {INFO_CAT_ID}")
if INFO_CAT_ID not in INFO_CAT_MAP:
    print(f"알 수 없는 INFO_CATEGORY: {INFO_CAT_ID!r} (가능: {list(INFO_CAT_MAP)})")
    sys.exit(1)
BLOG_CATEGORY = INFO_CAT_MAP[INFO_CAT_ID]
HISTORY_PATH = os.path.join(DATA_DIR, f"info_{INFO_CAT_ID}_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "info_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("info_post")


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


def _is_real_post_url(url) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _extract_summary_bullets(summary_text: str, max_count: int = 4) -> list[str]:
    """summary_text에서 불릿 항목 추출 (인포그래픽 헤더 카드용)."""
    bullets = []
    for line in summary_text.splitlines():
        line = line.strip()
        for prefix in ("· ", "• ", "- ", "* ", "✓ ", "√ ", "▶ ", "> "):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        # 5~35자 길이의 의미있는 항목만 사용
        if 5 <= len(line) <= 35:
            bullets.append(line)
        if len(bullets) >= max_count:
            break
    return bullets


def _append_internal_links(body: str, history: list) -> tuple:
    """같은 카테고리 최근 글 1~2개를 본문 끝에 회색바 소제목 + 가운데정렬 링크카드로 추가"""
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
    logger.info(f"[{BLOG_CATEGORY}] 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"

    history = _load_history()
    if _already_posted_this_run(history, run_slot) and not force and not draft:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 {BLOG_CATEGORY} 포스팅 완료 — 건너뜀")
        return

    # ── 1. 키워드 선정 ──
    from generator.keyword import pick_keyword_for_blog_category
    recent_kws = _get_recent_posted_keywords(history)
    kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY)
    keyword = kw_result["keyword"]
    for _ in range(3):
        if keyword not in recent_kws:
            break
        logger.info(f"최근 발행 키워드 중복 ({keyword!r}) — 재선정")
        kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY)
        keyword = kw_result["keyword"]
    logger.info(f"선정 키워드: {keyword!r} | 카테고리: {BLOG_CATEGORY}")

    # ── 2. 글 생성 ──
    from generator.info_content import generate_info_post
    post = generate_info_post(keyword=keyword, api_key=GOOGLE_API_KEY, info_cat_id=INFO_CAT_ID)
    if not post:
        logger.error(f"{BLOG_CATEGORY}글 생성 실패 — 종료")
        sys.exit(1)

    # 안전장치: 헤더([사진1]) 외 본문 사진 마커([사진2]+) 제거
    if post.get("body"):
        cleaned = re.sub(r"^\s*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        if cleaned != post["body"]:
            logger.info("본문 사진 마커 [사진2]+ 제거 (헤더카드만 사용)")
            post["body"] = cleaned

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    # ── 3. 이미지: 헤더 카드만 (본문 스톡사진 없음) ──
    images: list[dict] = []
    try:
        from poster.naver_blog import create_health_header_card
        bullets = _extract_summary_bullets(post.get("summary_text", "")) or None
        header_path = create_health_header_card(
            title=post["title"], keyword=keyword, category=INFO_CAT_ID, bullets=bullets
        )
        if header_path:
            images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
            logger.info(f"{BLOG_CATEGORY} 헤더 카드 생성 완료 (불릿 {len(bullets) if bullets else 0}개): {header_path}")
    except Exception as e:
        logger.warning(f"헤더 카드 생성 실패 (무시): {e}")
    logger.info(f"{BLOG_CATEGORY} 글: 본문 스톡사진 생략 (헤더 카드만)")

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
        "info_category": INFO_CAT_ID,
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table": bool(post.get("table_strs")),
        "has_faq": bool(post.get("faq_pairs")),
    }
    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"{BLOG_CATEGORY} 포스팅 완료: {post_url} | 이미지 {entry['images_inserted']}장")
    else:
        logger.error(f"{BLOG_CATEGORY} 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
