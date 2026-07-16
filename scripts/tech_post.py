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

    # ── 3. 실사진: 대표(헤더) + 섹션 사진 여러 장(테크티노식) ──
    # 홈판 대표 썸네일=[사진1] 최상단 실사진. 추가로 콘텐츠 소제목마다 관련 실사진을 [사진2][사진3]로
    # 주입해 섹션마다 사진이 오게 한다. 실사진 전무 시에만 인포그래픽 카드 폴백.
    images: list[dict] = []
    from config import PEXELS_API_KEY

    def _ensure_local(p: dict):
        lp = p.get("local_path")
        if not lp and p.get("url"):
            try:
                from poster.naver_blog import _download_image_to_temp
                lp = _download_image_to_temp(p["url"], label=p.get("label"))
            except Exception as e:
                logger.warning(f"이미지 다운로드 실패: {e}")
        return lp

    photos: list[dict] = []
    try:
        from generator.tech_image import get_tech_photos
        photos = get_tech_photos(topic, PEXELS_API_KEY, want=3)
    except Exception as e:
        logger.warning(f"실사진 확보 실패: {e}")

    # 대표(헤더) = 첫 장을 배경으로 '사진+훅텍스트' 헤더카드(테크티노 스타일). 실패 시 원본 사진.
    if photos:
        lead_local = _ensure_local(photos[0])
        if lead_local:
            header_local = None
            try:
                from poster.infographic_html import create_photo_header_card
                header_local = create_photo_header_card(
                    lead_local, post["title"], keyword=post.get("seed", "테크"), category="tech"
                )
            except Exception as e:
                logger.warning(f"사진 헤더카드 실패 — 원본 사진 사용: {e}")
            images.append({
                "local_path": header_local or lead_local, "url": "",
                "alt_text": post.get("seed", "테크"),
                # 카드는 사진이 이미 박혀 있어 '출처' 캡션 불필요, 원본사진 폴백 시에만 캡션.
                "label": "" if header_local else photos[0].get("label", ""),
            })
            logger.info(f"대표 헤더{'카드' if header_local else '(원본사진)'} 확보: {photos[0].get('source')}")

    # 섹션 사진 — 콘텐츠 소제목(핵심요약/목차/총평/FAQ 제외) 위에 [사진N] 주입 + insert_before
    if images and len(photos) > 1:
        _skip = {"핵심 요약 3줄", "목차", "총평", "자주 묻는 질문"}
        content_subs = [s for s in post.get("subheadings", []) if s.strip() not in _skip]
        targets = content_subs[1:] or content_subs  # 첫 콘텐츠 섹션은 헤더와 가까워 두 번째부터
        body = post.get("body", "")
        marker_n = 2
        for i, ph in enumerate(photos[1:]):
            if i >= len(targets):
                break
            sub = targets[i]
            pat = f"[구분선]\n{sub}\n"  # 실제 소제목([구분선] 뒤)만 매칭 — 목차 '· {sub}'는 안 걸림
            if pat not in body:
                continue
            local = _ensure_local(ph)
            if not local:
                continue
            # ★소제목 '다음 줄'에 [사진N] 주입 → 마커 다음의 '고유한 본문 첫 줄'이 앵커가 되어 그 앞에 삽입.
            #   insert_before(소제목 텍스트)는 목차에도 같은 텍스트가 있어 목차 항목에 먼저 걸리므로 쓰지 않는다.
            body = body.replace(pat, f"{pat}[사진{marker_n}]\n", 1)
            images.append({
                "local_path": local, "url": "",
                "alt_text": post.get("seed", "테크"), "label": ph.get("label", ""),
            })
            logger.info(f"섹션 실사진 예약: [사진{marker_n}] → '{sub[:15]}' 섹션 ({ph.get('source')})")
            marker_n += 1
        post["body"] = body

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
