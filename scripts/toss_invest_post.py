"""실계좌 투자 기록 — 토스증권 Open API → WP '투자 기록' 카테고리 주간 발행 (2026-07-17 뼈대).

키 발급 전엔 MOCK(스펙 예시)으로만 동작하며, MOCK 상태에선 절대 publish 하지 않는다
(크론=조용히 스킵 / 수동 ALLOW_MOCK=true + draft 검증만). 키 발급 후: 시크릿/.env에
TOSS_CLIENT_ID·TOSS_CLIENT_SECRET 등록 → 매주 일요일 21:30 자동 발행.

구성: 계좌 요약 → 보유 종목 표 → 이번 주 매매 일지 → 관찰 코멘트 → 다음 주 계획 → 면책.
사용: python -m scripts.toss_invest_post  (WP_STATUS/DRY_RUN/ALLOW_MOCK)
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

from config import DATA_DIR, GOOGLE_API_KEY, WP_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("toss_invest_post")

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "toss_report_history.json")
CATEGORY = "투자 기록"          # WP 전용 카테고리(없으면 자동 생성)
CATEGORY_SLUG = "invest-log"

_EXTRA_INSTRUCTIONS = """\
- 이 글은 블로그 주인장이 매주 쓰는 '실계좌 투자 기록' 시리즈다. 페르소나는 그대로 현지언니 —
  "제 실제 계좌를 그대로 공개하는 기록"이라는 톤. 꾸밈·과장 없이 담백하게.
- 구조(순서 유지, 소제목 문구는 자연스럽게):
  ① 이번 주 계좌 한 줄 요약 — 평가금액·수익률 변화를 두괄식으로
  ② 보유 종목 현황 — 표로(종목/수량/평단/현재가/수익률), 표 아래 눈에 띄는 종목 1~2개 코멘트
  ③ 이번 주 매매 일지 — 체결 내역이 있으면 무엇을 왜 샀/팔았는지, 없으면 '관망'과 그 이유 한 줄
  ④ 배당·인컴 관찰 — 배당/인컴형 보유분(커버드콜·배당 ETF 등)에 대한 짧은 관찰
  ⑤ 다음 주 관전 포인트 — 계획 1~2개(단정 금지, '지켜보려 해요' 톤)
- ★수치는 [팩트 데이터]의 값만 그대로 사용. 계산·추정으로 새 수치를 만들지 마라.
- ★절대 투자 권유·종목 추천으로 읽히게 쓰지 마라. 특정 종목 매수 유도 문구 금지.
- 글 끝 면책 1줄: "이 글은 개인 투자 기록일 뿐 투자 권유가 아니며, 모든 투자 판단과 책임은
  본인에게 있습니다." """


def _load_history() -> dict:
    try:
        return json.load(open(HISTORY_PATH, encoding="utf-8"))
    except Exception:
        return {"count": 0, "posts": []}


def _ensure_category() -> None:
    """WP에 '투자 기록' 카테고리 보장 — 없으면 생성(최초 1회)."""
    import requests
    from poster.wp_publish import _api, _headers
    try:
        r = requests.get(_api("categories"), params={"search": CATEGORY, "per_page": 5},
                         headers=_headers(), timeout=15)
        if r.ok and any(c.get("name") == CATEGORY for c in r.json()):
            return
        r = requests.post(_api("categories"),
                          json={"name": CATEGORY, "slug": CATEGORY_SLUG,
                                "description": "실계좌로 쓰는 투자 기록 시리즈"},
                          headers=_headers(), timeout=15)
        if r.status_code in (200, 201):
            logger.info(f"WP 카테고리 생성: {CATEGORY}")
    except Exception as e:
        logger.warning(f"카테고리 보장 실패(발행은 계속): {e}")


def run():
    from generator.toss_collector import build_invest_facts, is_mock, has_manual_snapshot

    status = os.environ.get("WP_STATUS", "publish").strip().lower()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    allow_mock = os.environ.get("ALLOW_MOCK", "false").lower() == "true"

    manual = is_mock() and has_manual_snapshot()  # 캡처 스냅샷 = 실데이터(반자동 모드)
    if is_mock() and not manual:
        if not (allow_mock or dry_run):
            logger.info("토스 키 미발급(MOCK) — 크론 스킵. 검증은 ALLOW_MOCK=true 또는 DRY_RUN=true")
            return
        status = "draft"  # 가짜(MOCK) 데이터는 어떤 경우에도 실발행 금지
        logger.warning("MOCK 모드 — 강제 draft")

    history = _load_history()
    n = history.get("count", 0) + 1
    now = datetime.now(KST)
    period = f"{(now - timedelta(days=7)).strftime('%m월 %d일')} ~ {now.strftime('%m월 %d일')}"
    keyword = f"실계좌 투자 기록 {n}주차"

    topic = {
        "keyword": keyword,
        "category": CATEGORY,
        "hub_id": CATEGORY_SLUG,
        "facts": build_invest_facts(f"{n}주차 · {period}"),
        "key_stats": [],
        "sources": [("토스증권 (실계좌 데이터)", "https://tossinvest.com")],
        "use_search": False,  # 계좌 팩트만 — 외부 검색 섞지 않음
        "extra_instructions": _EXTRA_INSTRUCTIONS,
    }

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)
    from generator.deep_content import generate_deep_post
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("투자 기록 생성 실패")
        sys.exit(1)

    if dry_run:
        logger.info(f"[DRY_RUN] 생성만 완료: {post['title']!r} ({len(post.get('body', ''))}자)")
        print(post.get("body", "")[:600])
        return

    from generator.wp_render import render_wordpress_post
    from poster.wp_publish import (publish_wordpress, check_connection,
                                   upload_media_info, set_featured_image)
    if not check_connection():
        sys.exit(1)
    _ensure_category()

    slug = f"invest-log-{n:03d}"
    r = render_wordpress_post(
        post, category=CATEGORY, base_url=f"{WP_URL.rstrip('/')}/{slug}/",
        slug_override=slug, related_posts=[], site_url=WP_URL, category_slug=CATEGORY_SLUG,
    )
    res = publish_wordpress(r, title=post["title"], status=status, category=CATEGORY)
    if not res:
        sys.exit(1)
    logger.info(f"발행 완료 [{res['status']}] {res['link']}")

    try:
        from generator.wp_featured import build_featured_image
        img = build_featured_image(post["title"], keyword, CATEGORY, CATEGORY_SLUG,
                                   api_key=GOOGLE_API_KEY)
        if img:
            info = upload_media_info(img, f"featured-{slug}.png", alt_text=post["title"])
            try:
                os.unlink(img)
            except OSError:
                pass
            if info:
                set_featured_image(res["id"], info["id"])
    except Exception as e:
        logger.warning(f"대표 이미지 실패(무시): {e}")

    if status == "publish":
        history["count"] = n
        history.setdefault("posts", []).append(
            {"n": n, "date": now.strftime("%Y-%m-%d"), "slug": slug, "link": res.get("link", "")})
        os.makedirs(DATA_DIR, exist_ok=True)
        json.dump(history, open(HISTORY_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run()
