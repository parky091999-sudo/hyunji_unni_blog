"""청약 공고 건별 분석글 발행 — 청약홈 신규 공고 감지 → 심층분석 → WP 주거·청약 (2026-07-17).

정규 로테이션(wp_post)과 별개 트랙: 새 공고가 있을 때만 추가 발행(하루 1건 가드 미적용),
run당 최대 1건(비용·품질 통제). 잔여 신규 공고는 다음 크론이 순차 소화.

사용:
  python -m scripts.cheongyak_post                 # 신규 공고 1건 발행
  CHEONGYAK_NOTICE=2026000123 ...                  # 특정 공고(HOUSE_MANAGE_NO) 강제
  WP_STATUS=draft DRY_RUN=true ...                 # 검증 모드
필요 키: PUBLIC_DATA_KEY(청약홈 API), GOOGLE_API_KEY, WP_*(발행)
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
logger = logging.getLogger("cheongyak_post")

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "cheongyak_history.json")
HUB_ID = "housing-plan"

# 청약 건별 분석 구조 (2026-07-17 사용자 지시: 일정·현금·타입·유형·가격적정성·판단)
_EXTRA_INSTRUCTIONS = """\
- 이 글은 특정 단지 '입주자모집공고' 건별 분석이다. 아래 흐름을 반드시 갖춰라(소제목 문구는 자연스럽게, 순서 유지):
  ① 어떤 단지인가 — 위치·규모·시공사·공급유형을 한눈에
  ② 청약 일정 — 특별공급/1·2순위/당첨자 발표/계약을 표로
  ③ 현금은 얼마나 필요한가 — 타입별 분양가와 계약금 계산. 계약금 비율·중도금 대출 조건은
     '모집공고문 발췌' 원문에 있는 내용만 근거로 쓰고, 발췌에 없으면 '공고문 확인 필요'로 처리
  ④ 어떤 타입이 유리한가 — 세대수·면적·가격을 비교해 경쟁률 관점 코멘트
  ⑤ 신청 유형별 체크 — 특별공급 종류·1순위 요건·규제(투기과열/조정대상/분양가상한) 적용 여부
  ⑥ 가격은 적당한가 — 팩트에 '주변 아파트 실거래 시세(국토교통부)'가 있으면 그것을 1순위
     근거로 삼아 분양가와 직접 비교하라(예: 84㎡ 최고분양가가 같은 구 준신축 평균 대비 몇 %
     수준인지 계산, 최근 실거래 사례 1~2건 인용). 검색 정보는 보조로만, '~로 알려져 있다' 톤,
     확인 안 되면 단정 금지
  ⑦ 마지막 소제목은 '현지언니의 판단' — [해볼 만하다 / 조건부 추천 / 보류] 셋 중 하나를 첫 문장에서
     명확히 고르고, 근거 3가지 + '이런 분께 맞다/이런 분은 보류' 를 불릿으로
- 판단은 투자 권유 단정이 아니라 조건 중심으로. 글 끝에 '청약 자격·자금 사정은 사람마다 달라
  최종 판단 전 입주자모집공고문 원문을 꼭 확인하라'는 면책 1줄.
- 검색(그라운딩) 정보와 공고 팩트를 섞지 마라 — 수치는 팩트 데이터·공고문 발췌가 우선."""


def _load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_history(h: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)


def _related_housing_posts(limit: int = 3) -> list[dict]:
    """기발행 주거·청약 허브 글을 관련글로 (내부링크·체류시간)."""
    try:
        from generator.wp_topics import TOPICS
        wp_hist_path = os.path.join(DATA_DIR, "wp_post_history.json")
        hist = json.load(open(wp_hist_path, encoding="utf-8")) if os.path.exists(wp_hist_path) else {}
        out = []
        for tid, meta in TOPICS.items():
            if meta.get("hub_id") == HUB_ID and tid in hist:
                out.append({"title": meta.get("keyword", tid),
                            "slug": meta.get("slug") or tid.replace("_", "-")})
        return out[:limit]
    except Exception:
        return []


def _notice_block_html(name: str, captures: list[dict], upload) -> str:
    """공고문 캡처(금액표·평면도) → 본문 삽입용 figure 블록. 출처 표기 필수."""
    figs = ""
    for c in captures:
        info = upload(c["path"], alt_suffix=c["label"], page=c.get("page", 0))
        if not info:
            continue
        cap = f"{name} {c['label']} (출처: 입주자모집공고문·청약홈)"
        figs += (
            f'<figure class="wp-block-image size-large hj-notice-capture">'
            f'<img src="{info["source_url"]}" alt="{name} {c["label"]}" loading="lazy"/>'
            f"<figcaption>{cap}</figcaption></figure>\n"
        )
    if not figs:
        return ""
    return (
        '<h2 id="sec-notice">모집공고문 원문 자료</h2>\n'
        "<p>계약 조건·금액의 최종 기준은 아래 공고문 원문입니다. 표가 잘 안 보이면 눌러서 확대해 보세요.</p>\n"
        + figs
    )


def run():
    from generator.cheongyak_collector import (
        fetch_new_apt_notices, fetch_new_remainder_notices, fetch_house_types,
        fetch_notice_pdf, pdf_excerpt, pdf_capture_key_pages,
        build_facts, build_key_stats, notice_key,
    )
    from generator.wp_topics import hub_display

    status = os.environ.get("WP_STATUS", "publish").strip().lower()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    forced = os.environ.get("CHEONGYAK_NOTICE", "").strip()

    history = _load_history()
    notices = fetch_new_apt_notices() + fetch_new_remainder_notices()
    if forced:
        notices = [n for n in notices if forced in (n.get("HOUSE_MANAGE_NO", ""), notice_key(n))]
    else:
        notices = [n for n in notices if notice_key(n) not in history]
    if not notices:
        logger.info("발행할 신규 청약 공고 없음 — 종료")
        return

    # 공고일 최신순 1건만 (잔여는 다음 크론)
    notices.sort(key=lambda n: n.get("RCRIT_PBLANC_DE", ""), reverse=True)
    detail = notices[0]
    key = notice_key(detail)
    name = detail.get("HOUSE_NM", "").strip()
    logger.info(f"대상 공고: [{key}] {name} ({detail.get('SUBSCRPT_AREA_CODE_NM')}, "
                f"{detail.get('RCRIT_PBLANC_DE')}) 잔여 신규 {len(notices) - 1}건")

    types = fetch_house_types(detail.get("HOUSE_MANAGE_NO", ""),
                              remainder=bool(detail.get("_remainder")))
    pdf = fetch_notice_pdf(detail)
    excerpt = pdf_excerpt(pdf) if pdf else ""
    captures = pdf_capture_key_pages(pdf) if pdf else []

    # 주변 실거래 시세(국토부) — 가격 적정성의 확정 팩트 근거 (2026-07-17, 실패해도 발행)
    rt_facts = None
    try:
        from generator.rt_price import build_trade_facts
        rt_facts = build_trade_facts(detail.get("HSSPLY_ADRES", ""), types)
    except Exception as e:
        logger.warning(f"실거래 시세 수집 실패(무시): {e}")

    facts = build_facts(detail, types, excerpt)
    if rt_facts:
        facts["주변 아파트 실거래 시세(국토교통부, 최근 6개월)"] = rt_facts
    topic = {
        "keyword": f"{name} 청약",
        "category": hub_display(HUB_ID),
        "hub_id": HUB_ID,
        "facts": facts,
        "key_stats": build_key_stats(detail, types),
        "sources": [(f"{name} 입주자모집공고 (청약홈)", detail.get("PBLANC_URL", "") or "https://www.applyhome.co.kr"),
                    ("청약홈 청약일정", "https://www.applyhome.co.kr")],
        "use_search": True,  # 주변 시세·여건 맥락 보강 (톤 가드는 extra_instructions)
        "extra_instructions": _EXTRA_INSTRUCTIONS,
    }

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)

    from generator.deep_content import generate_deep_post
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("청약 분석글 생성 실패")
        sys.exit(1)

    if dry_run:
        logger.info(f"[DRY_RUN] 생성만 완료: {post['title']!r} "
                    f"(본문 {len(post.get('body', ''))}자, 캡처 {len(captures)}장) — 발행 생략")
        return

    from generator.wp_render import render_wordpress_post
    from poster.wp_publish import (publish_wordpress, check_connection,
                                   upload_media_info, set_featured_image)
    if not check_connection():
        logger.error("WP 연결 실패")
        sys.exit(1)

    slug = f"cheongyak-{detail.get('HOUSE_MANAGE_NO', key)}"
    post_url = f"{WP_URL.rstrip('/')}/{slug}/"
    r = render_wordpress_post(
        post, category=topic["category"], base_url=post_url, slug_override=slug,
        related_posts=_related_housing_posts(), site_url=WP_URL, category_slug=HUB_ID,
    )

    # 공고문 캡처(금액표·평면도) 섹션 — 출처·확대 안내 포함, 관련글/출처 앞에 삽입
    def _upload(path, alt_suffix="", page=0):
        return upload_media_info(path, f"{slug}-notice-p{page}.png",
                                 alt_text=f"{name} {alt_suffix}")

    block = _notice_block_html(name, captures, _upload)
    if block:
        anchor = r.get("sources_html") or ""
        if anchor and anchor in r["content_html"]:
            r["content_html"] = r["content_html"].replace(anchor, block + anchor, 1)
        else:
            r["content_html"] += "\n" + block
        logger.info("공고문 원문 자료 섹션 삽입 완료")
    else:
        # 캡처가 없으면 본문 일러스트로 시각 요소 보강 (금액표 있으면 원문이 우선)
        try:
            from generator.wp_body_images import add_body_illustrations
            r["content_html"] = add_body_illustrations(
                r["content_html"], topic["keyword"], topic["category"], GOOGLE_API_KEY, slug=slug)
        except Exception as e:
            logger.warning(f"본문 일러스트 실패(무시): {e}")

    res = publish_wordpress(r, title=post["title"], status=status, category=topic["category"])
    if not res:
        logger.error("발행 실패")
        sys.exit(1)
    logger.info(f"발행 완료 [{res['status']}] id={res['id']} {res['link']}")

    # 대표 이미지 (best-effort)
    try:
        from generator.wp_featured import build_featured_image
        img = build_featured_image(post["title"], topic["keyword"], topic["category"],
                                   HUB_ID, api_key=GOOGLE_API_KEY)
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
        history[key] = {
            "date": datetime.now(KST).strftime("%Y-%m-%d"),
            "house_nm": name,
            "region": detail.get("SUBSCRPT_AREA_CODE_NM", ""),
            "slug": slug,
            "post_url": res.get("link", ""),
            "remainder": bool(detail.get("_remainder")),
        }
        _save_history(history)


if __name__ == "__main__":
    run()
