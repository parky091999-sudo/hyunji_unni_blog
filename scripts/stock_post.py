"""
주식 블로그 자동 포스팅 (공모주·주식분석·ETF).
팩트 수집 → Gemini 원고 → 네이버 블로그 포스팅.

GitHub Actions: STOCK_TOPIC=etf포트폴리오 python -m scripts.stock_post
"""
import json
import logging
import os
import random
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
    "종목분석": "종목분석",
    "공모주캘린더": "공모주캘린더",
    "etf포트폴리오": "etf포트폴리오",
}

_CARD_CATEGORY = {
    "종목분석": "주식분석",
    "공모주캘린더": "공모주",
    "etf포트폴리오": "주식etf",
}

_INDIVIDUAL_ETF_TYPES = ("kr_individual", "us_individual", "kr_overseas_individual")


def _card_hook_keyword(keyword: str, fact_data, stock_topic: str) -> str:
    """헤더 카드 표시 문구를 절반 확률로 호기심형 질문으로 바꿔보는 실험(카드 전용, 실제
    게시글 제목·alt텍스트는 건드리지 않음). 단일종목/ETF 분석처럼 "사도 될까?"가 실제로
    본문이 답하는 질문일 때만 적용 — 비교·절세계좌 글에는 어울리지 않아 제외."""
    if stock_topic == "종목분석":
        is_individual = True
    elif stock_topic == "etf포트폴리오" and isinstance(fact_data, dict):
        is_individual = fact_data.get("_etf_content_type") in _INDIVIDUAL_ETF_TYPES
    else:
        is_individual = False
    if not is_individual or random.random() >= 0.5:
        return keyword
    base = keyword.replace(" 분석", "").strip()
    return f"{base} 지금 사도 될까?"


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
    """같은 날·같은 소분류(stock_topic) 1회만 — posted/pending 모두 차단(ETF 4중복 방지)."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("status") in ("posted", "pending"):
            return True
    return False


def _reserve_today_slot(history: list, stock_topic: str, topic_name: str) -> list:
    """동시 실행·연속 재시도 시 중복 발행 방지 — pending 선기록."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    history = [h for h in history if not (h.get("date") == today and h.get("status") == "pending")]
    history.insert(
        0,
        {
            "date": today,
            "timestamp": datetime.now(KST).isoformat(),
            "stock_topic": stock_topic,
            "topic_name": topic_name,
            "status": "pending",
        },
    )
    return history


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

    if not force and not draft and not dry_run:
        history = _reserve_today_slot(history, STOCK_TOPIC, topic_name)
        _save_history(history)
        logger.info(f"[{topic_name}] 오늘 슬롯 pending 선점 — 중복 실행 방지")

    from generator.stock_collector import StockDataCollector

    if STOCK_TOPIC == "종목분석":
        recent_names = {h.get("stock_name") for h in history[:20] if h.get("stock_name")}
        fact_data = StockDataCollector.pick_featured_stock(recent_names=recent_names, history_len=len(history))
    elif STOCK_TOPIC == "etf포트폴리오":
        from generator.etf_collector import EtfDataCollector

        force_content_type = os.environ.get("ETF_CONTENT_TYPE", "").strip()
        fact_data = EtfDataCollector.pick_etf_topic(history=history, force_content_type=force_content_type or None)
    else:
        fact_data = StockDataCollector.collect(STOCK_TOPIC)
    if not fact_data:
        # 상한가 0건인 날·휴장 등 데이터가 없을 수 있음 → 빨간 실패 대신 조용히 건너뜀.
        # (force/draft로 강제 실행한 경우엔 원인 확인을 위해 실패로 종료)
        logger.warning(f"[{topic_name}] 팩트 데이터 없음 — 이번 슬롯 건너뜀 (skip)")
        sys.exit(1 if (force or draft) else 0)
    logger.info(f"팩트 데이터 수집 완료: {type(fact_data).__name__}")

    # ── 최근 뉴스·이슈 검색 보강 (종목분석·ETF 개별분석) ──
    # 기존 '최근뉴스'(국내 종목 상세 페이지 스크랩)와 같은 키로 병합 — 프롬프트 규칙 공유.
    if isinstance(fact_data, dict):
        news_queries: list[str] = []
        if STOCK_TOPIC == "종목분석" and fact_data.get("종목명"):
            news_queries = [f"{fact_data['종목명']} 주가"]
        elif STOCK_TOPIC == "etf포트폴리오" and fact_data.get("_etf_content_type") in _INDIVIDUAL_ETF_TYPES:
            subject = fact_data.get("_etf_subject") or ""
            if subject:
                news_queries = [f"{subject} ETF"]
        if news_queries:
            try:
                extra_news = StockDataCollector.get_search_news(news_queries)
                if extra_news:
                    merged = list(fact_data.get("최근뉴스") or []) + extra_news
                    fact_data["최근뉴스"] = merged[:6]
            except Exception as e:
                logger.warning(f"뉴스 검색 보강 실패(무시): {e}")

    # ── 종목분석: 연간 매출·영업이익 추이 보강 (본문 인용 + [사진3] 재무 차트와 동일 소스) ──
    if STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict):
        fin_tickers: list[tuple[str, bool]] = []
        if fact_data.get("시장") == "미국" and fact_data.get("티커"):
            fin_tickers = [(fact_data["티커"], False)]
        elif fact_data.get("_code"):
            fin_tickers = [(f"{fact_data['_code']}.KS", True), (f"{fact_data['_code']}.KQ", True)]
        for yft, is_krw in fin_tickers:
            try:
                fin = StockDataCollector.get_financial_trend(yft, is_krw=is_krw)
            except Exception as e:
                logger.warning(f"재무 추이 보강 실패(무시): {e}")
                fin = {}
            if fin:
                fact_data.update(fin)
                fact_data["_fin_ticker"] = yft
                fact_data["_fin_is_krw"] = is_krw
                logger.info(f"재무 추이 보강: {yft}")
                break

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
    if isinstance(fact_data, dict) and fact_data.get("_header_keyword"):
        keyword = fact_data["_header_keyword"]
    elif STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict) and fact_data.get("종목명"):
        keyword = f"{fact_data['종목명']} 분석"

    card_cat = _CARD_CATEGORY.get(STOCK_TOPIC, "주식etf")
    card_keyword = _card_hook_keyword(keyword, fact_data, STOCK_TOPIC)
    from generator.content import extract_summary_bullets
    bullets = extract_summary_bullets(post.get("summary_text", "")) or None
    header_path = None
    # HTML/CSS 인포그래픽 우선(gov/info와 동일 시스템), 실패 시 기존 PIL 카드 폴백
    try:
        from poster.infographic_html import create_infographic_via_html

        header_path = create_infographic_via_html(
            title=post["title"], keyword=card_keyword, category=card_cat, bullets=bullets
        )
        if header_path:
            logger.info(f"HTML 인포그래픽 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"HTML 인포그래픽 실패 — PIL 폴백: {e}")

    if not header_path:
        try:
            from poster.naver_blog import create_health_header_card

            header_path = create_health_header_card(
                title=post["title"], keyword=card_keyword, category=card_cat, bullets=bullets
            )
        except Exception as e:
            logger.warning(f"PIL 헤더 카드 생성 실패 (무시): {e}")

    if header_path:
        images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
        logger.info(f"주식 헤더 카드 생성: {header_path}")

    # ── 섹터·테마 비교: 헤더 다음 [사진2]에 비교 인포그래픽(월부 벤치마킹) ──
    if (STOCK_TOPIC == "etf포트폴리오" and isinstance(fact_data, dict)
            and fact_data.get("_etf_content_type") in ("sector_compare_kr", "sector_compare_us")):
        try:
            targets = fact_data.get("비교대상")
            group = fact_data.get("그룹명")
            if targets and group:
                from poster.infographic_html import create_comparison_infographic

                cmp_path = create_comparison_infographic(group, targets, category=card_cat)
                if cmp_path:
                    images.append({
                        "local_path": cmp_path, "url": "",
                        "alt_text": f"{group} ETF 비교", "label": f"{group} 비교",
                    })
                    logger.info(f"비교 인포그래픽 생성: {cmp_path}")
        except Exception as e:
            logger.warning(f"비교 인포그래픽 생성 실패(무시): {e}")

    if STOCK_TOPIC == "etf포트폴리오" and isinstance(fact_data, dict):
        try:
            chart_mode = fact_data.get("_chart_mode")
            tickers = fact_data.get("_chart_tickers") or []
            labels = fact_data.get("_chart_labels") or {}
            title = fact_data.get("_chart_title") or ""
            chart_path = None
            if chart_mode == "single" and tickers:
                from generator.stock_chart import generate_price_chart

                chart_path = generate_price_chart(tickers[0], label=labels.get(tickers[0], tickers[0]), period="6mo")
            elif chart_mode == "compare" and len(tickers) >= 2:
                from generator.stock_chart import generate_comparison_chart

                chart_path = generate_comparison_chart(tickers, labels=labels, period="3mo", title=title)
            if chart_path:
                images.append({
                    "local_path": chart_path, "url": "",
                    "alt_text": title or "ETF 차트",
                    "label": title or "차트",
                })
                logger.info(f"ETF 차트 생성: {chart_path}")

            # ── 배당 심층 차트 2장 ([사진3] 배당성장, [사진4] 재투자 비교) ──
            # ★가격차트([사진2])가 성공했을 때만 — 실패 시 이미지 인덱스가 밀려
            #   배당 차트가 [사진2] 자리(가격차트 해석 문장)에 들어가는 캡션 불일치 방지.
            # [사진3]은 배당차트 성공이 전제이므로 배당차트 실패 시 재투자 차트도 생략.
            # 배당 차트 2장은 배당·인컴형(dividend)에만 — growth/bond는 배당데이터가 있어도
            # 구조에 배당 섹션([사진3][사진4])이 없어 삽입 안 됨(생성 낭비 방지).
            _is_div_type = fact_data.get("_etf_type", "dividend") == "dividend"
            if chart_path and chart_mode == "single" and tickers and _is_div_type and fact_data.get("연도별배당(주당USD)"):
                from generator.stock_chart import (
                    generate_dividend_history_chart,
                    generate_total_return_chart,
                )

                div_label = labels.get(tickers[0], tickers[0])
                div_path = generate_dividend_history_chart(tickers[0], label=div_label)
                if div_path:
                    images.append({
                        "local_path": div_path, "url": "",
                        "alt_text": f"{div_label} 연도별 주당 배당금 추이",
                        "label": "연도별 주당 배당금",
                    })
                    logger.info(f"배당 이력 차트 생성: {div_path}")
                    tr_path = generate_total_return_chart(tickers[0], label=div_label)
                    if tr_path:
                        images.append({
                            "local_path": tr_path, "url": "",
                            "alt_text": f"{div_label} 배당 재투자 총수익 vs 주가 비교",
                            "label": "배당 재투자 vs 주가",
                        })
                        logger.info(f"총수익 비교 차트 생성: {tr_path}")
        except Exception as e:
            logger.warning(f"ETF 차트 생성 실패 (무시): {e}")

    if STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict):
        try:
            from generator.stock_chart import generate_price_chart

            stock_name = fact_data.get("종목명", "")
            chart_path = None
            if fact_data.get("시장") == "미국" and fact_data.get("티커"):
                chart_path = generate_price_chart(fact_data["티커"], label=stock_name, period="6mo")
            elif fact_data.get("시장") == "국내" and fact_data.get("_code"):
                code = fact_data["_code"]
                for suffix in (".KS", ".KQ"):
                    chart_path = generate_price_chart(f"{code}{suffix}", label=stock_name, period="6mo")
                    if chart_path:
                        break
            if chart_path:
                images.append({
                    "local_path": chart_path, "url": "",
                    "alt_text": f"{stock_name} 6개월 가격 추이 차트",
                    "label": f"{stock_name} 가격 추이",
                })
                logger.info(f"종목 가격 차트 생성: {chart_path}")

            # ── 네이버금융 공식 실시간 차트(국내 종목만) — 가격차트 성공 시에만(인덱스 밀림 방지) ──
            # 프롬프트(_stock_photo_blocks)가 has_naver_chart를 같은 조건(시장=국내+_code)으로
            # 판단해 [사진N] 자리를 미리 잡아두므로, 여기서도 같은 조건으로 삽입해야 순서가 맞는다.
            if chart_path and fact_data.get("시장") == "국내" and fact_data.get("_code"):
                from generator.stock_chart import get_naver_official_chart

                naver_chart_path = get_naver_official_chart(fact_data["_code"])
                if naver_chart_path:
                    images.append({
                        "local_path": naver_chart_path, "url": "",
                        "alt_text": f"{stock_name} 네이버금융 실시간 차트",
                        "label": f"{stock_name} 네이버금융 차트",
                    })
                    logger.info(f"네이버금융 공식 차트 다운로드: {naver_chart_path}")

            # ── [사진N] 연간 실적 추이 차트 — 가격차트 성공 + 재무 팩트 존재 시에만(인덱스 밀림 방지) ──
            if chart_path and fact_data.get("_fin_ticker"):
                from generator.stock_chart import generate_financials_chart

                fin_path = generate_financials_chart(
                    fact_data["_fin_ticker"], label=stock_name,
                    is_krw=bool(fact_data.get("_fin_is_krw")),
                )
                if fin_path:
                    images.append({
                        "local_path": fin_path, "url": "",
                        "alt_text": f"{stock_name} 연간 매출·영업이익 추이 차트",
                        "label": f"{stock_name} 연간 실적 추이",
                    })
                    logger.info(f"재무 추이 차트 생성: {fin_path}")
        except Exception as e:
            logger.warning(f"종목 가격 차트 생성 실패 (무시): {e}")

    # 실제로 준비된 이미지 수보다 큰 [사진N] 마커는 게시 불가하므로 제거,
    # 같은 번호가 중복 출현하면(줄 단독이 아닌 문장 안 삽입 포함) 첫 등장만 남기고 제거.
    # (중복 마커가 남으면 같은 이미지 인덱스에 앵커가 2개 잡혀, 그중 하나가
    #  본문 내 동일 텍스트가 표 안에도 있는 경우 커서가 표로 잘못 들어가 삽입이
    #  통째로 실패하는 사례가 실제 라이브 발행에서 확인됨)
    img_count = len(images)
    if post.get("body"):
        seen_markers: set[str] = set()

        def _strip_marker(m: "re.Match[str]") -> str:
            n = m.group(1)
            if int(n) > img_count or n in seen_markers:
                return ""
            seen_markers.add(n)
            return m.group(0)

        cleaned = re.sub(r"\[사진(\d+)\]", _strip_marker, post["body"])
        if cleaned != post["body"]:
            logger.info("중복/초과 [사진N] 마커 정리됨")
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
        "stock_name": fact_data.get("종목명") if isinstance(fact_data, dict) else None,
        "etf_content_type": fact_data.get("_etf_content_type") if isinstance(fact_data, dict) else None,
        "etf_subject": fact_data.get("_etf_subject") if isinstance(fact_data, dict) else None,
    }

    history = _load_history()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    history = [h for h in history if not (h.get("date") == today and h.get("status") == "pending")]
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"[{topic_name}] 포스팅 완료: {post_url}")
    else:
        logger.error(f"[{topic_name}] 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
