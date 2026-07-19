"""청약 공고 건별 분석 — 네이버(현지언니 부동산·주거) 발행 (2026-07-17).

WP(cheongyak_post)와 같은 수집·팩트(공고 API+공고문 PDF+실거래)를 재사용, 네이버 SE ONE
형식으로 발행: 헤더카드 [사진1] + 요약 인용구 + 소제목 회색바 + 표 + FAQ 인용구 +
공고문 금액표·평면도 캡처를 관련 소제목 위치에 사진으로 삽입.

WP 트랙과 독립 이력(data/cheongyak_naver_history.json) — 같은 공고를 양쪽에 각각 발행.
사용: python -m scripts.cheongyak_naver_post  (CHEONGYAK_NOTICE / DRAFT / DRY_RUN 지원)
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

from config import (DATA_DIR, GOOGLE_API_KEY,
                    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("cheongyak_naver_post")

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "cheongyak_naver_history.json")
# 2026-07-19 수정: 실제 블로그 카테고리명은 "부동산, 주거"(쉼표) — 가운뎃점(·) 표기가
# 매칭에 실패해 발행 패널 기본(직전) 카테고리로 나가던 버그(공모주 오분류 실사고).
BLOG_CATEGORY = "부동산, 주거"


def _load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_history(h: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)


def _next_sub_after(subs: list[str], *kws) -> str:
    """kws가 들어간 소제목의 '다음' 소제목 — 캡처를 그 앞(=해당 섹션 끝)에 삽입하기 위함."""
    for i, s in enumerate(subs):
        if any(k in s for k in kws):
            return subs[i + 1] if i + 1 < len(subs) else s
    return ""


def run():
    from generator.cheongyak_collector import (
        fetch_new_apt_notices, fetch_new_remainder_notices, fetch_house_types,
        fetch_notice_pdf, pdf_excerpt, pdf_capture_key_pages,
        build_facts, notice_key,
    )

    draft = os.environ.get("DRAFT", "false").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    forced = os.environ.get("CHEONGYAK_NOTICE", "").strip()

    history = _load_history()
    notices = fetch_new_apt_notices() + fetch_new_remainder_notices()
    if forced:
        notices = [n for n in notices if forced in (n.get("HOUSE_MANAGE_NO", ""), notice_key(n))]
    else:
        notices = [n for n in notices if notice_key(n) not in history]
    if not notices:
        logger.info("발행할 신규 청약 공고 없음(네이버 트랙) — 종료")
        return

    notices.sort(key=lambda n: n.get("RCRIT_PBLANC_DE", ""), reverse=True)
    detail = notices[0]
    key = notice_key(detail)
    name = detail.get("HOUSE_NM", "").strip()
    logger.info(f"[네이버] 대상 공고: [{key}] {name} ({detail.get('SUBSCRPT_AREA_CODE_NM')})")

    types = fetch_house_types(detail.get("HOUSE_MANAGE_NO", ""),
                              remainder=bool(detail.get("_remainder")))
    pdf = fetch_notice_pdf(detail)
    excerpt = pdf_excerpt(pdf) if pdf else ""
    captures = pdf_capture_key_pages(pdf) if pdf else []

    facts = build_facts(detail, types, excerpt)
    try:
        from generator.rt_price import build_trade_facts
        rt = build_trade_facts(detail.get("HSSPLY_ADRES", ""), types)
        if rt:
            facts["주변 아파트 실거래 시세(국토교통부, 최근 6개월)"] = rt
    except Exception as e:
        logger.warning(f"실거래 시세 수집 실패(무시): {e}")

    topic = {"keyword": f"{name} 청약", "facts": facts}

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)
    from generator.cheongyak_naver_content import generate_cheongyak_naver_post
    post = generate_cheongyak_naver_post(topic, GOOGLE_API_KEY)
    if not post:
        sys.exit(1)

    if dry_run:
        logger.info(f"[DRY_RUN] 생성만 완료: {post['title']!r} — 발행 생략")
        print(post.get("body", "")[:800])
        return

    # ── 이미지: [사진1] 헤더카드 + 공고문 캡처(관련 소제목 앞 삽입) ──
    images: list[dict] = []
    subs = post.get("subheadings", [])
    try:
        from generator.content import extract_summary_bullets
        from poster.infographic_html import create_infographic_via_html
        bullets = extract_summary_bullets(post.get("summary_text", "")) or None
        header = create_infographic_via_html(
            title=post["title"], keyword=name, category="부동산주거", bullets=bullets)
        if header:
            images.append({"local_path": header, "url": "",
                           "alt_text": f"{name} 청약", "label": ""})
    except Exception as e:
        logger.warning(f"헤더카드 실패(사진 없이 진행): {e}")

    # 캡처는 [사진N] 마커를 본문에 직접 주입해야 삽입된다 — 포스터는 마커 수만큼만 이미지를
    # 넣고 insert_before는 위치 보정용(2026-07-17 CI 실측: 마커 없인 캡처가 통째로 유실).
    # 마커는 대상 섹션 '끝'(다음 소제목의 [구분선] 바로 앞) + 캡션 실패 대비 출처 줄을 본문에 동봉.
    money_anchor = _next_sub_after(subs, "현금", "분양가", "필요")
    plan_anchor = _next_sub_after(subs, "타입", "유리")
    body = post.get("body", "")
    marker_n = 2

    # 데이터 인포카드 3종(2026-07-19 벤치마킹: 섹션마다 카드) — 팩트만 렌더라 수치 오류 불가.
    # 요약 카드=요약 직후(첫 소제목 앞), 일정 카드=일정 섹션 끝, 분양가 카드=현금 섹션 끝(캡처 위).
    try:
        from poster.cheongyak_cards import create_cheongyak_cards
        cards = create_cheongyak_cards(facts)
    except Exception as e:
        cards = []
        logger.warning(f"청약 인포카드 실패(캡처만으로 진행): {e}")
    card_anchor = {
        "overview": subs[0] if subs else "",
        "schedule": _next_sub_after(subs, "일정"),
        "price": money_anchor,
    }
    for c in cards:
        anchor = card_anchor.get(c.get("anchor_hint", ""), "")
        block = f"[사진{marker_n}]\n"
        pat = f"[구분선]\n{anchor}\n" if anchor else ""
        if pat and pat in body:
            body = body.replace(pat, block + pat, 1)
        else:
            body += "\n" + block
        img = {"local_path": c["local_path"], "url": "",
               "alt_text": c.get("label", ""), "label": ""}
        if anchor:
            img["insert_before"] = anchor
        images.append(img)
        marker_n += 1
    if cards:
        logger.info(f"청약 인포카드 {len(cards)}장 삽입: "
                    + ", ".join(c.get("anchor_hint", "?") for c in cards))

    for c in captures:
        anchor = plan_anchor if "평면" in c["label"] else money_anchor
        # 출처는 본문에 안 적고 말미 '자료 출처' 섹션에 몰아서(2026-07-17 사용자 피드백)
        block = f"[사진{marker_n}]\n"
        pat = f"[구분선]\n{anchor}\n" if anchor else ""
        if pat and pat in body:
            body = body.replace(pat, block + pat, 1)
        else:
            body += "\n" + block
        img = {
            "local_path": c["path"], "url": "",
            "alt_text": f"{name} {c['label']}",
            "label": f"{name} {c['label']} — 입주자모집공고문 (출처: 청약홈)",
        }
        if anchor:
            img["insert_before"] = anchor
        images.append(img)
        marker_n += 1

    # 말미 '자료 출처' 섹션 — 본문 곳곳의 출처 표기를 여기로 일원화
    src_lines = ["· 입주자모집공고문 원문: 청약홈(applyhome.co.kr)"]
    if captures:
        pages = "·".join(f"p.{c.get('page', '')}" for c in captures)
        src_lines.append(f"· 본문 표 이미지: 입주자모집공고문 {pages} 캡처 (출처: 청약홈)")
    if "주변 아파트 실거래 시세(국토교통부, 최근 6개월)" in facts:
        src_lines.append("· 실거래가: 국토교통부 실거래가 공개시스템")
    body += "\n\n[구분선]\n자료 출처\n" + "\n".join(src_lines) + "\n"
    post.setdefault("subheadings", subs).append("자료 출처")
    post["body"] = body
    logger.info(f"이미지 구성: 헤더 1장 + 공고문 캡처 {len(captures)}장 "
                f"(마커 [사진2]~, 금액표→'{money_anchor[:14]}' 앞)")

    # ── 발행 ──
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
            subheadings=subs,
            faq_questions=post.get("faq_questions", []),
            category=BLOG_CATEGORY,
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
            # 2026-07-19 사용자 지시로 가운데 정렬 철회(전부 좌측) — 07-17 옵션이 설명 문단까지
            # 전부 가운데로 만들어 가독성 저하. 되돌리려면 True.
            center_align=False,
            style_line_markers=True,  # [[미니 소제목]]·{{음영 강조}} 줄 마커 스타일링
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)

    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return

    post_url = (result or {}).get("post_url", "")
    if not post_url or "Redirect=Write" in post_url:
        logger.error(f"발행 실패 — URL: {post_url}")
        sys.exit(1)
    history[key] = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "house_nm": name,
        "region": detail.get("SUBSCRPT_AREA_CODE_NM", ""),
        "post_url": post_url,
        "remainder": bool(detail.get("_remainder")),
    }
    _save_history(history)
    logger.info(f"[네이버] 청약 분석글 발행 완료: {post_url}")


if __name__ == "__main__":
    run()
