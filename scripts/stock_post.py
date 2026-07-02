"""
주식 블로그 자동 포스팅 (공모주·주식분석·ETF).
팩트 수집 → Gemini 원고 → 네이버 블로그 포스팅.

GitHub Actions: STOCK_TOPIC=etf포트폴리오 python -m scripts.stock_post
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR,
    LOG_DIR,
    GOOGLE_API_KEY,
    NAVER_ID,
    NAVER_PW,
    NAVER_BLOG_ID,
    NAVER_COOKIES,
)
from generator.stock_content import STOCK_TOPICS

KST = timezone(timedelta(hours=9))

STOCK_TOPIC_MAP = {
    "상한가특징주": "상한가특징주",
    "공모주캘린더": "공모주캘린더",
    "etf포트폴리오": "etf포트폴리오",
}

_CARD_CATEGORY = {
    "상한가특징주": "주식분석",
    "공모주캘린더": "공모주",
    "etf포트폴리오": "주식etf",
}


def _pick_least_recent_topic() -> str:
    best, best_ts = None, None
    for tid in STOCK_TOPIC_MAP:
        path = os.path.join(DATA_DIR, f"stock_{tid}_history.json")
        last = ""
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                posted = [h.get("timestamp", "") for h in data if h.get("status") == "posted"]
                last = max(posted) if posted else ""
        except Exception:
            last = ""
        key = last or "0000"
        if best is None or key < best_ts:
            best, best_ts = tid, key
    return best or "etf포트폴리오"


STOCK_TOPIC = os.environ.get("STOCK_TOPIC", "").strip()
if not STOCK_TOPIC or STOCK_TOPIC == "auto":
    STOCK_TOPIC = _pick_least_recent_topic()
    print(f"[자동 순환] 주식 소분류 선택: {STOCK_TOPIC}")
if STOCK_TOPIC not in STOCK_TOPIC_MAP:
    print(f"알 수 없는 STOCK_TOPIC: {STOCK_TOPIC!r} (가능: {list(STOCK_TOPIC_MAP)})")
    sys.exit(1)

HISTORY_PATH = os.path.join(DATA_DIR, f"stock_{STOCK_TOPIC}_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "stock_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("stock_post")


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


def _already_posted_today(history: list) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("status") == "posted":
            return True
    return False


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_internal_links(body: str, history: list) -> tuple:
    related = [h for h in history if h.get("status") == "posted" and h.get("post_url") and h.get("title")][:2]
    if not related:
        return body, []
    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"
    return body + links_text, ["함께 보면 좋은 글"]


def run():
    blog_category = STOCK_TOPICS[STOCK_TOPIC]["blog_category"]
    topic_name = STOCK_TOPICS[STOCK_TOPIC]["name"]
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(
        f"주식 포스팅 시작 [{topic_name}] 카테고리='{blog_category}' (슬롯 {run_slot}): "
        f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}"
    )
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
    if _already_posted_today(history) and not force and not draft and not dry_run:
        logger.info(f"오늘 이미 [{topic_name}] 포스팅 완료 — 건너뜀")
        return

    from generator.stock_collector import StockDataCollector

    fact_data = StockDataCollector.collect(STOCK_TOPIC)
    if not fact_data:
        # 상한가 0건인 날·휴장 등 데이터가 없을 수 있음 → 빨간 실패 대신 조용히 건너뜀.
        # (force/draft로 강제 실행한 경우엔 원인 확인을 위해 실패로 종료)
        logger.warning(f"[{topic_name}] 팩트 데이터 없음 — 이번 슬롯 건너뜀 (skip)")
        sys.exit(1 if (force or draft) else 0)
    logger.info(f"팩트 데이터 수집 완료: {type(fact_data).__name__}")

    from generator.stock_content import generate_stock_post

    post = generate_stock_post(STOCK_TOPIC, fact_data, GOOGLE_API_KEY)
    if not post:
        logger.error(f"[{topic_name}] 원고 생성 실패 — 종료")
        sys.exit(1)

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    images: list[dict] = []
    keyword = topic_name
    try:
        from poster.naver_blog import create_health_header_card

        card_cat = _CARD_CATEGORY.get(STOCK_TOPIC, "주식etf")
        header_path = create_health_header_card(title=post["title"], keyword=keyword, category=card_cat)
        if header_path:
            images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
            logger.info(f"주식 헤더 카드 생성: {header_path}")
    except Exception as e:
        logger.warning(f"헤더 카드 생성 실패 (무시): {e}")

    if STOCK_TOPIC == "etf포트폴리오":
        try:
            from generator.stock_chart import generate_comparison_chart

            tickers = ["SCHD", "JEPQ", "QLD", "TQQQ"]
            chart_path = generate_comparison_chart(
                tickers,
                labels={t: t for t in tickers},
                period="3mo",
                title="ETF 4종목 최근 3개월 성과 비교 (시작일=100 기준)",
            )
            if chart_path:
                images.append({
                    "local_path": chart_path, "url": "",
                    "alt_text": "ETF 4종목 3개월 성과 비교 차트",
                    "label": "3개월 성과 비교",
                })
                logger.info(f"ETF 비교 차트 생성: {chart_path}")
        except Exception as e:
            logger.warning(f"비교 차트 생성 실패 (무시): {e}")

    # 실제로 준비된 이미지 수보다 큰 [사진N] 마커는 게시 불가하므로 제거
    img_count = len(images)
    if post.get("body"):
        def _strip_excess_marker(m: "re.Match[str]") -> str:
            return "" if int(m.group(1)) > img_count else m.group(0)

        cleaned = re.sub(r"^\s*\[사진(\d+)\]\s*$\n?", _strip_excess_marker, post["body"], flags=re.MULTILINE)
        if cleaned != post["body"]:
            post["body"] = cleaned

    post["body"], extra_subs = _append_internal_links(post["body"], history)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

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
            category=blog_category,
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)

    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return

    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)

    entry = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(KST).isoformat(),
        "run_slot": run_slot,
        "stock_topic": STOCK_TOPIC,
        "topic_name": topic_name,
        "blog_category": blog_category,
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
        logger.info(f"[{topic_name}] 포스팅 완료: {post_url}")
    else:
        logger.error(f"[{topic_name}] 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
