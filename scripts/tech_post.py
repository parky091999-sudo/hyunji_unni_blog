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
HISTORY_PATH = os.path.join(DATA_DIR, "tech_history.json")

# 형식 로테이션 순서 — 매 발행 다음 형식으로 (지루함 방지)
FMT_ROTATION = ["breaking", "explain", "pick", "compare"]

# 카테고리별 하루 1편 발행 순서 (2026-07-17 사용자 지시) — 크론 슬롯마다
# '오늘 아직 안 나간 카테고리' 중 첫 번째를 발행. 뉴스 없으면 다음 카테고리로 넘어감.
CATEGORY_ORDER = ["스마트폰·모바일", "PC·노트북", "가전·디지털", "자동차·모빌리티", "AI·IT"]

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


def _posted_categories_today(history: list) -> set:
    """오늘 이미 발행된 블로그 카테고리 집합. 구 이력(category 필드 없음)은 seed로 역추론."""
    from generator.tech_content import SEED_CATEGORY
    today = datetime.now(KST).strftime("%Y-%m-%d")
    cats = set()
    for h in history:
        if h.get("date") == today and h.get("status") == "posted":
            cat = h.get("category") or SEED_CATEGORY.get(h.get("seed", ""), "")
            if cat:
                cats.add(cat)
    return cats


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


def _extract_summary_for_postit(post: dict):
    """본문의 '핵심 요약' 소제목+불릿 섹션을 인용구용으로 분리 (2026-07-17 사용자 지시).
    성공 시 post['summary_text']를 채우고 본문 자리는 [요약삽입] 마커로 교체
    → poster가 도입부 뒤 '포스트잇' 인용구 블록으로 삽입한다."""
    body = post.get("body", "")
    m = re.search(r"\[구분선\]\n([^\n]*(?:요약|핵심만)[^\n]*)\n((?:·[^\n]+\n?)+)", body)
    if not m:
        # 폴백(07-17 draft 실측): 모델이 요약 소제목에 제품명을 넣어 '요약' 단어가 빠지는 경우 —
        # '첫 번째 섹션이 불릿 2~4줄로만 구성'이면 구조상 핵심 요약(_BENCH_OPEN 고정 위치)으로 간주.
        cand = re.search(r"\[구분선\]\n([^\n]+)\n((?:·[^\n]+\n?)+)", body)
        if cand:
            n_bullets = len([l for l in cand.group(2).splitlines() if l.strip()])
            nxt = body[cand.end():].lstrip("\n")
            if (cand.start() == body.find("[구분선]") and 2 <= n_bullets <= 4
                    and (not nxt or nxt.startswith(("[구분선]", "[사진", "[표", "[FAQ")))):
                m = cand
    if not m:
        logger.info("핵심 요약 섹션 미검출 — 포스트잇 인용구 생략(본문 그대로)")
        return
    post["summary_text"] = m.group(2).strip()
    post["body"] = body[:m.start()] + "[요약삽입]\n" + body[m.end():]
    sub = m.group(1).strip()
    post["subheadings"] = [s for s in post.get("subheadings", []) if s != sub]
    logger.info(f"핵심 요약 {len(post['summary_text'].splitlines())}줄 → 포스트잇 인용구로 분리 ('{sub}')")


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

    # ── 1. 카테고리(하루 1편) + 형식 + 주제 선정 ──
    from generator.tech_content import generate_tech_post, pick_tech_topic, SEED_CATEGORY

    forced_fmt = os.environ.get("FORCE_FMT", "").strip()
    fmt = forced_fmt if forced_fmt in FMT_ROTATION else _next_format(history)

    # 카테고리별 하루 1편(2026-07-17 사용자 지시): 크론 슬롯마다 '오늘 미발행 카테고리'를
    # 순서대로 시도 → 뉴스 없는 카테고리는 건너뛰어 슬롯을 낭비하지 않는다.
    forced_cat = os.environ.get("TECH_CATEGORY", "").strip()
    posted_today = set() if force else _posted_categories_today(history)
    if forced_cat:
        cats_to_try = [forced_cat]
    else:
        cats_to_try = [c for c in CATEGORY_ORDER if c not in posted_today]
    if not cats_to_try:
        logger.info(f"오늘 카테고리별 1편({len(CATEGORY_ORDER)}편) 전부 발행 완료 — 슬롯 {run_slot} 건너뜀")
        return

    # 최근 발행 헤드라인은 후보에서 원천 제외 — 같은 뉴스가 연일 상위여도 재발행 안 함(2026-07-16)
    recent_heads = _recent_headlines(history)
    # 당일 이슈 우선(2026-07-17 벤치마킹): 잔여 카테고리를 전부 탐색해 '지금 가장 뜨거운'
    # 헤드라인의 카테고리부터 발행 — 검색 피크(이슈 당일)를 로테이션 순서 때문에 놓치지 않는다.
    # 카테고리별 하루 1편 원칙은 그대로(순서만 이슈 온도로 재정렬).
    probes = []
    for cat in cats_to_try:
        cat_seeds = [s for s, c in SEED_CATEGORY.items() if c == cat]
        t = pick_tech_topic(exclude_headlines=recent_heads, seeds=cat_seeds)
        if t:
            probes.append((t.get("score", 0), cat, t))
        else:
            logger.info(f"카테고리 '{cat}' 최신 소비자 뉴스 없음")
    if not probes:
        # 뉴스 없음 또는 소비자 주제 점수 미달 — 억지 발행 대신 정상 스킵(2026-07-16)
        logger.warning("발행할 소비자 주제 없음(잔여 카테고리 전부 뉴스 부족/B2B성) — 이번 슬롯 스킵")
        sys.exit(0)
    probes.sort(key=lambda p: (-p[0], CATEGORY_ORDER.index(p[1])))
    _, _post_category, topic = probes[0]
    if len(probes) > 1:
        logger.info("카테고리 온도: " + " | ".join(f"{c}={s}" for s, c, _ in probes))

    logger.info(f"형식={fmt} | 카테고리={_post_category} | 시드={topic['seed']} | 주제={topic['headline'][:40]}")

    # ── 2. 글 생성 ──
    post = generate_tech_post(GOOGLE_API_KEY, fmt=fmt, topic=topic)
    if not post:
        logger.error("테크글 생성 실패 — 종료")
        sys.exit(1)

    # 본문 사진 마커([사진2]+)·쇼핑 플레이스홀더 정리
    if post.get("body"):
        post["body"] = re.sub(r"^\s*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        post["body"] = _clean_shopping_placeholder(post["body"])

    # 핵심 요약 섹션 → 포스트잇 인용구로 분리 (2026-07-17 사용자 지시)
    _extract_summary_for_postit(post)

    # {{음영}} 마커는 본문 전용 — 별도 타이핑 경로(제목/요약/표/FAQ)에 섞이면 리터럴로
    # 노출되므로 방어적 평문화(포스터의 본문 추출은 body만 처리, 2026-07-17)
    _unbrace = lambda s: re.sub(r"\{\{(.+?)\}\}", r"\1", s or "")
    post["title"] = _unbrace(post.get("title", ""))
    post["summary_text"] = _unbrace(post.get("summary_text", ""))
    if post.get("table_str"):
        post["table_str"] = _unbrace(post["table_str"])
    if post.get("table_strs"):
        post["table_strs"] = [_unbrace(t) for t in post["table_strs"]]
    if post.get("faq_questions"):
        post["faq_questions"] = [_unbrace(q) for q in post["faq_questions"]]
    if post.get("faq_pairs"):
        post["faq_pairs"] = [[_unbrace(q), _unbrace(a)] for q, a in post["faq_pairs"]]

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:600] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 이미지: 실사진 전용 (07-17 저녁 사용자 피드백: 파스텔 AI 일러스트가 테크 톤과
    # 안 맞음 — 'AI 생성 티' 나는 이미지 금지) ──
    # 소스: 신뢰 언론사 og → 네이버쇼핑 상품 실사(tech_image 캐스케이드). 실사진이 없으면
    # 헤더는 다크 텍스트 카드, 섹션 이미지는 생략(무관·AI풍 이미지보다 무사진이 낫다).
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

    # 대표(헤더): 실사진 훅카드 → (실사진 없으면) 다크 텍스트 카드. AI 일러스트 금지(07-17).
    lead_local = _ensure_local(photos[0]) if photos else None
    lead_label = photos[0].get("label", "") if photos else ""
    lead_kind = "실사진"
    if lead_local:
        header_local = None
        try:
            from poster.infographic_html import create_photo_header_card
            header_local = create_photo_header_card(
                lead_local, post["title"], keyword=post.get("seed", "테크"), category="tech"
            )
        except Exception as e:
            logger.warning(f"헤더카드 실패 — 원본 이미지 사용: {e}")
        images.append({
            "local_path": header_local or lead_local, "url": "",
            "alt_text": post.get("seed", "테크"),
            # 카드는 이미지가 이미 박혀 있어 '출처' 캡션 불필요, 원본 폴백 시에만 캡션.
            "label": "" if header_local else lead_label,
        })
        logger.info(f"대표 헤더 확보: {lead_kind}{'+훅카드' if header_local else '(원본)'}")
    else:
        try:
            from poster.infographic_html import create_tech_header_card
            tc = create_tech_header_card(post["title"], keyword=post.get("seed", "테크"))
            if tc:
                images.append({"local_path": tc, "url": "",
                               "alt_text": post.get("seed", "테크"), "label": ""})
                logger.info("대표 헤더: 테크 텍스트 카드(최후 폴백)")
        except Exception as e:
            logger.warning(f"테크 텍스트 카드 실패 — 대표 이미지 없음: {e}")

    # 섹션 이미지 — 콘텐츠 소제목(핵심요약/목차/총평/FAQ 제외) 아래 [사진N] 주입.
    # 소스 풀: 실사진(og+쇼핑) 잔여분만 — AI 일러스트 채움 제거(07-17 사용자 피드백).
    if images:
        # 모델이 소제목 문구를 변형('핵심 요약'/'목차 정리' 등)해도 걸리도록 부분일치로 스킵(2026-07-16)
        _skip_kw = ("핵심 요약", "핵심만", "목차", "총평", "자주 묻는 질문", "요약")
        content_subs = [s for s in post.get("subheadings", [])
                        if not any(k in s.strip() for k in _skip_kw)]
        targets = content_subs[1:] or content_subs  # 첫 콘텐츠 섹션은 헤더와 가까워 두 번째부터
        pool: list[dict] = []
        for ph in photos[1:]:
            local = _ensure_local(ph)
            if local:
                pool.append({"local_path": local, "label": ph.get("label", ""), "kind": "실사진"})
        # 실사진 잔여분만, 상한 2장 — 부족하면 그만큼만 삽입(AI 일러스트 채움 폴백 삭제, 07-17)
        pool = pool[:2]
        body = post.get("body", "")
        marker_n = 2
        for i, im in enumerate(pool):
            if i >= len(targets):
                break
            sub = targets[i]
            pat = f"[구분선]\n{sub}\n"  # 실제 소제목([구분선] 뒤)만 매칭 — 목차 '· {sub}'는 안 걸림
            if pat not in body:
                continue
            # 소제목 바로 다음 줄이 표/요약/FAQ 플레이스홀더면 스킵 — [사진N] 다음 앵커가 산문이 아니라
            # following-anchor가 비어 소제목 텍스트 폴백(목차 충돌 위험)을 타는 경로 차단(2026-07-16)
            after = body.split(pat, 1)[1].lstrip("\n")
            if after.startswith(("[표삽입]", "[요약삽입]", "[FAQ삽입]", "[표시작]")):
                logger.info(f"섹션 이미지 스킵: '{sub[:15]}' 다음이 플레이스홀더({after[:8]}…)")
                continue
            # ★소제목 '다음 줄'에 [사진N] 주입 → 마커 다음의 '고유한 본문 첫 줄'이 앵커가 되어 그 앞에 삽입.
            #   insert_before(소제목 텍스트)는 목차에도 같은 텍스트가 있어 목차 항목에 먼저 걸리므로 쓰지 않는다.
            body = body.replace(pat, f"{pat}[사진{marker_n}]\n", 1)
            images.append({
                "local_path": im["local_path"], "url": "",
                "alt_text": post.get("seed", "테크"), "label": im["label"],
            })
            logger.info(f"섹션 이미지 예약: [사진{marker_n}] → '{sub[:15]}' 섹션 ({im['kind']})")
            marker_n += 1
        post["body"] = body

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
            summary_quote_style="포스트잇",  # 핵심 요약=포스트잇 인용구 (2026-07-17 사용자 지시)
            set_representative=True,  # 헤더카드를 홈판 대표 썸네일로(tech 전용 opt-in)
            style_line_markers=True,  # {{음영}} 형광펜 + [[단독줄]] 미니소제목 (2026-07-17 벤치마킹)
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
        "category": _post_category,  # 카테고리별 하루 1편 가드 기준(2026-07-17)
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
