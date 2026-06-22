"""
매일 자동 포스팅 메인 스크립트
GitHub Actions: python -m scripts.daily_post

업그레이드 내역 (v2):
- 카테고리 기반 키워드 선정
- 품질 점수 검증 + 60점 미만 재생성 (최대 2회)
- Pexels 이미지 3장 수집 및 포스터 전달
- 트렌딩 캐시 활용
- 이력에 카테고리/품질점수 저장
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
MAX_QUALITY_RETRIES = 2   # 품질 미달 시 최대 재생성 횟수
QUALITY_PASS_SCORE  = 60  # 발행 최소 점수

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
    logger.info("=" * 60)
    logger.info(f"일일 포스팅 시작 v2: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
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
        logger.info("DRAFT=true — 임시저장 검증 모드 (공개 발행 안 함 / 중복체크 무시 / 이력 미기록)")
    history = _load_history()
    if _already_posted_today(history) and not force and not draft:
        logger.info("오늘 이미 포스팅 완료 — 건너뜀 (강제실행: FORCE_POST=true)")
        return
    if force:
        logger.info("FORCE_POST=true — 오늘 중복 체크 무시하고 강제 실행")

    # ── 1. 키워드 선정 (카테고리 기반) ──────────────────────────
    from generator.keyword import pick_keyword
    kw_result   = pick_keyword()
    keyword     = kw_result["keyword"]
    category    = kw_result["category"]
    category_name = kw_result["category_name"]
    logger.info(f"키워드: {keyword!r} | 카테고리: {category_name}")

    # ── 2. 트렌딩 수집 (캐시 우선) ──────────────────────────────
    try:
        from generator.trend import get_weekly_trends, suggest_trend_angle
        trends = get_weekly_trends()
        trend_angle = suggest_trend_angle(keyword, trends, category)
        logger.info(f"트렌딩 {len(trends)}개 수집 | 각도: {trend_angle[:60] if trend_angle else '없음'}")
    except Exception as e:
        logger.warning(f"트렌딩 수집 실패 (무시): {e}")
        trends = []
        trend_angle = ""

    # ── 3. 글 생성 + 품질 검증 (최대 2회 재시도) ────────────────
    from generator.content import generate_post
    from generator.quality import score_content

    post = None
    quality_result = None

    for attempt in range(1, MAX_QUALITY_RETRIES + 2):  # 최대 3번 시도
        logger.info(f"글 생성 시도 {attempt}/{MAX_QUALITY_RETRIES + 1}")
        candidate = generate_post(
            keyword=keyword,
            api_key=GOOGLE_API_KEY,
            trending=trends[:4] if trends else None,
            category=category_name,
        )
        if not candidate:
            logger.error(f"글 생성 실패 (시도 {attempt})")
            if attempt > MAX_QUALITY_RETRIES:
                logger.error("글 생성 최종 실패 — 종료")
                return
            continue

        # 품질 채점
        qr = score_content(
            title=candidate.get("title", ""),
            body=candidate.get("body", ""),
            tags=candidate.get("tags", []),
            table_str=candidate.get("table_str", ""),
            faq_str=candidate.get("faq_str", ""),
        )
        logger.info(f"품질 점수: {qr['score']}/100 ({'통과' if qr['pass'] else '재생성'})")

        if qr["pass"] or attempt > MAX_QUALITY_RETRIES:
            post = candidate
            quality_result = qr
            if not qr["pass"]:
                logger.warning(f"품질 미달({qr['score']}점)이지만 재시도 소진 — 발행 진행")
            break
        else:
            logger.warning(
                f"품질 미달 ({qr['score']}점, 기준 {QUALITY_PASS_SCORE}점) — 재생성\n"
                f"이슈: {' / '.join(qr['issues'][:3])}"
            )

    if not post:
        logger.error("글 생성 최종 실패 — 종료")
        return

    logger.info(f"제목: {post['title']}")
    logger.info(f"태그: {post['tags']}")
    logger.info(f"표 포함: {'있음' if post.get('table_str') else '없음'}")
    logger.info(f"FAQ 포함: {'있음' if post.get('faq_str') else '없음'}")
    # 디버그: 생성·퇴고된 본문 전문 (품질 육안 검토용 — 로그에서 확인)
    logger.info("===== 본문 전문 시작 =====\n" + post.get("body", "") + "\n===== 본문 전문 끝 =====")
    if post.get("coupang_hints"):
        logger.info(f"쿠팡 힌트: {post['coupang_hints']}")

    # ── 4. 이미지 수집 (image_keywords 활용 시 7장 위치별 수집) ──────
    images: list[dict] = []
    image_keywords = post.get("image_keywords", [])
    if image_keywords:
        logger.info(f"이미지 키워드 {len(image_keywords)}개: {image_keywords}")
    if PEXELS_API_KEY:
        try:
            from generator.image import get_post_images
            img_count = len(image_keywords) if image_keywords else 7
            images = get_post_images(
                keyword=keyword,
                api_key=PEXELS_API_KEY,
                count=img_count,
                category=category,
                image_keywords=image_keywords if image_keywords else None,
            )
            logger.info(f"이미지 수집: {len(images)}장")
        except Exception as e:
            logger.warning(f"이미지 수집 실패 (무시): {e}")
    else:
        logger.info("PEXELS_API_KEY 없음 — 이미지 없이 진행")

    # ── 5. 포스팅 ────────────────────────────────────────────────
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
    )

    # ── 드래프트 검증 모드: 이력 기록 없이 결과만 로깅하고 종료 ──
    if draft:
        if result:
            logger.info(
                f"[DRAFT] 임시저장 결과: {result.get('post_url')} | "
                f"에디터 본문 {result.get('editor_text_len')}자 | "
                f"이미지 {result.get('images_inserted')}장 삽입"
            )
            logger.info("[DRAFT] 스크린샷(draft_after_save, after_body, body_verify_failed) 확인 요망")
        else:
            logger.error("[DRAFT] 포스팅 함수 None 반환 — 로그/스크린샷 확인 필요")
        logger.info("[DRAFT] 이력 미기록 — 검증 모드 종료")
        return

    # ── 6. 이력 저장 ─────────────────────────────────────────────
    post_url  = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)
    now_str   = datetime.now(KST).isoformat()

    entry = {
        "date":           datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp":      now_str,
        "keyword":        keyword,
        "category":       category,
        "category_name":  category_name,
        "title":          post["title"],
        "tags":           post["tags"],
        "status":         "posted" if is_posted else "failed",
        "post_url":       post_url if is_posted else None,
        "quality_score":  quality_result["score"] if quality_result else None,
        "quality_pass":   quality_result["pass"]  if quality_result else None,
        "images_count":   len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table":      bool(post.get("table_str")),
        "has_faq":        bool(post.get("faq_str")),
    }
    history.insert(0, entry)
    _save_history(history[:200])

    if is_posted:
        logger.info(f"포스팅 완료: {post_url}")
        logger.info(
            f"품질: {quality_result['score']if quality_result else 'N/A'}점 | "
            f"이미지: {entry['images_inserted']}장 삽입"
        )
    else:
        # 실패 시 프로세스를 비정상 종료해 GitHub Actions가 '실패'로 표시 → 알림이 가게 함
        # (예전엔 exit 0 이라 본문 소실/쿠키 만료에도 초록불이 떠 모니터링 사각지대였음)
        logger.error(f"포스팅 실패 — 쿠키 만료(보호조치) 또는 발행 오류 의심. URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
