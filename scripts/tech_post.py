"""
형수의테크공장 — IT/테크 자동 포스팅 스크립트
GitHub Actions: python -m scripts.tech_post

형식 4종 로테이션(breaking/explain/pick/compare)을 순환 발행.
계정: hyungsutech (khj) — 현지언니와 별도. TECH_NAVER_* 시크릿 사용.
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
    DATA_DIR, LOG_DIR, GOOGLE_API_KEY,
    TECH_NAVER_ID, TECH_NAVER_PW, TECH_NAVER_BLOG_ID, TECH_NAVER_COOKIES,
    NAVER_ID, NAVER_PW, NAVER_COOKIES,  # 로컬 폴백용
)

KST = timezone(timedelta(hours=9))
BLOG_CATEGORY = "IT·테크"
HISTORY_PATH = os.path.join(DATA_DIR, "tech_history.json")

# 형식 로테이션 순서 — 매 발행 다음 형식으로 (지루함 방지)
FMT_ROTATION = ["breaking", "explain", "pick", "compare"]

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "tech_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("tech_post")


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


def _recent_headlines(history: list, days: int = 14) -> set:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {h["headline"] for h in history if h.get("date", "") >= cutoff and h.get("headline")}


def _next_format(history: list) -> str:
    """직전 발행 형식 다음 순번을 선택(4종 순환)."""
    last_fmt = history[0].get("fmt") if history else None
    if last_fmt in FMT_ROTATION:
        idx = (FMT_ROTATION.index(last_fmt) + 1) % len(FMT_ROTATION)
        return FMT_ROTATION[idx]
    return FMT_ROTATION[0]


def _is_real_post_url(url) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _clean_shopping_placeholder(body: str) -> str:
    """쇼핑커넥트 링크 미발급 상태 — [쇼핑추천] 마커와 안내 플레이스홀더 줄 제거(리터럴 노출 방지)."""
    body = re.sub(r"^\s*\[쇼핑추천\]\s*$\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"^\s*\(※\s*쇼핑커넥트.*$\n?", "", body, flags=re.MULTILINE)
    return body


def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"[형수의테크공장] 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    # 계정: TECH_NAVER_* 우선, 없으면 로컬 테스트용 NAVER_* 폴백
    naver_id = TECH_NAVER_ID or NAVER_ID
    naver_pw = TECH_NAVER_PW or NAVER_PW
    naver_cookies = TECH_NAVER_COOKIES or NAVER_COOKIES
    blog_id = TECH_NAVER_BLOG_ID or "hyungsutech"

    if not dry_run and not naver_id and not naver_cookies:
        logger.error("TECH_NAVER 계정/쿠키 없음 — 발행 불가 (DRY_RUN만 가능)")
        sys.exit(1)

    history = _load_history()
    if _already_posted_this_run(history, run_slot) and not force and not draft and not dry_run:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 발행 완료 — 건너뜀")
        return

    # ── 1. 형식 + 주제 선정 ──
    from generator.tech_content import generate_tech_post, pick_tech_topic, category_for_seed

    forced_fmt = os.environ.get("FORCE_FMT", "").strip()
    fmt = forced_fmt if forced_fmt in FMT_ROTATION else _next_format(history)

    recent_heads = _recent_headlines(history)
    topic = pick_tech_topic(exclude=set())
    if topic is None:
        logger.error("최신 테크 뉴스 없음 — 종료")
        sys.exit(1)
    # 최근 발행 헤드라인 중복 회피(간단): 겹치면 한 번 더 시도
    if topic["headline"] in recent_heads:
        logger.info(f"최근 발행 헤드라인 중복 — 재선정 시도")
        topic = pick_tech_topic(exclude={topic["seed"]}) or topic

    _post_category = category_for_seed(topic["seed"])
    logger.info(f"형식={fmt} | 시드={topic['seed']} | 카테고리={_post_category} | 주제={topic['headline'][:40]}")

    # ── 2. 글 생성 ──
    post = generate_tech_post(GOOGLE_API_KEY, fmt=fmt, topic=topic)
    if not post:
        logger.error("테크글 생성 실패 — 종료")
        sys.exit(1)

    # 본문 사진 마커([사진2]+)·쇼핑 플레이스홀더 정리
    if post.get("body"):
        post["body"] = re.sub(r"^\s*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        post["body"] = _clean_shopping_placeholder(post["body"])

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:600] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 대표 이미지 = 뉴스 실사진(홈판 썸네일 최적화) ──
    # 카테크 홈판 노출 글은 전부 '실사진' 썸네일 — 현지언니식 인포그래픽 헤더카드는 복제 인상을
    # 주므로 폐기. 첫 이미지([사진1] 최상단 = 홈판 대표 썸네일)를 뉴스 og:image 실사진으로 넣는다.
    # 인포그래픽 카드는 실사진을 하나도 못 구했을 때만 최후 폴백(썸네일 없는 글 방지)으로 사용.
    images: list[dict] = []
    from config import PEXELS_API_KEY

    lead = None
    try:
        from generator.tech_image import get_tech_body_image
        lead = get_tech_body_image(topic, PEXELS_API_KEY)
    except Exception as e:
        logger.warning(f"대표 실사진 확보 실패: {e}")

    if lead:
        lead_local = lead.get("local_path")
        # Pexels 폴백 등 URL만 있는 경우: 최상단 헤더 삽입은 local_path가 필수 → 로컬 다운로드
        if not lead_local and lead.get("url"):
            try:
                from poster.naver_blog import _download_image_to_temp
                lead_local = _download_image_to_temp(lead["url"], label=lead.get("label"))
            except Exception as e:
                logger.warning(f"대표 실사진 다운로드 실패: {e}")
        if lead_local:
            images.append({
                "local_path": lead_local, "url": "",
                "alt_text": post.get("seed", "테크"), "label": lead.get("label", ""),
            })
            logger.info(f"대표 실사진(홈판 썸네일) 확보: {lead.get('source')} | {lead.get('label', '')}")

    if not images:
        # 실사진 전무 → 썸네일 없는 글 방지용 최후 폴백(인포그래픽 카드)
        logger.warning("실사진 미확보 — 인포그래픽 카드 폴백(대표이미지 공백 방지)")
        from generator.content import extract_summary_bullets
        bullets = extract_summary_bullets(post.get("summary_text", "")) or None
        header_path = None
        try:
            from poster.infographic_html import create_infographic_via_html
            header_path = create_infographic_via_html(
                title=post["title"], keyword=post.get("seed", "테크"), category="tech", bullets=bullets
            )
        except Exception as e:
            logger.warning(f"HTML 인포그래픽 폴백 실패: {e}")
        if header_path:
            images.append({"local_path": header_path, "url": "", "alt_text": post.get("seed", "테크"), "label": post.get("seed", "테크")})

    # ── 4. 포스팅 ──
    from poster.naver_blog import post_to_naver_blog
    try:
        result = post_to_naver_blog(
            naver_id=naver_id,
            naver_pw=naver_pw,
            blog_id=blog_id,
            title=post["title"],
            body=post["body"],
            tags=post["tags"],
            naver_cookies=naver_cookies,
            images=images if images else None,
            draft=draft,
            allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
            table_str=post.get("table_str", ""),
            table_strs=post.get("table_strs", []),
            subheadings=post.get("subheadings", []),
            faq_questions=post.get("faq_questions", []),
            category=_post_category,
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
        "fmt": fmt,
        "seed": post.get("seed", ""),
        "headline": topic["headline"],
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_inserted": result.get("images_inserted", 0) if result else 0,
    }
    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"형수의테크공장 포스팅 완료 [{fmt}]: {post_url}")
    else:
        logger.error(f"형수의테크공장 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
