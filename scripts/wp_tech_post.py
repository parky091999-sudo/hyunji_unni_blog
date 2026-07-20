"""tech.hyunjiunni.com 심층 가이드 발행 (2026-07-19 신설, 사용자 승인).

형수테크 네이버 가이드 트랙의 WP 특화판 — 같은 주제 풀(tech_guide_pool.json)을 쓰되
원고는 별도 생성(중복 텍스트 방지), 구글·빙 검색을 정조준하는 HTML 심층 가이드.
발행: WP REST API(앱 비밀번호). 이력: data/wp_tech_history.json
환경: TECH_WP_URL, TECH_WP_APP_USER, TECH_WP_APP_PW (EC2 .env)
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from generator.content import _gen_text  # noqa: E402

KST = timezone(timedelta(hours=9))
POOL_PATH = os.path.join(ROOT, "data", "tech_guide_pool.json")
HIST_PATH = os.path.join(ROOT, "data", "wp_tech_history.json")
# 같은 풀을 쓰는 네이버 가이드 트랙(tech_guide_post)과 동일 주제가 같은 시기에 양 채널
# 발행되는 것 방지 (07-19 윈도우11·07-20 챗GPT 2일 연속 동일일 충돌 — §7 0-m)
CROSS_HIST_PATH = os.path.join(ROOT, "data", "tech_guide_history.json")
CROSS_EXCLUDE_DAYS = 14
# 하루 발행 상한(2026-07-20 발행량 확대). EC2 .env에서 2로 상향 + 크론 2슬롯.
TECH_WP_DAILY_MAX = int(os.environ.get("TECH_WP_DAILY_MAX", "1"))

WP_URL = os.environ.get("TECH_WP_URL", "https://tech.hyunjiunni.com").rstrip("/")
WP_USER = os.environ.get("TECH_WP_APP_USER", "hyungsu_admin")
WP_PW = os.environ.get("TECH_WP_APP_PW", "")

WP_CATEGORY_MAP = {
    "PC 오류해결·설정": "PC 오류해결", "AI 활용·자동화": "AI 활용", "오피스·툴 활용": "오피스·툴 활용",
    # 2026-07-19 확장: 네이버 블로그 카테고리 5종 — WP엔 뉴스 미러가 아니라 심층 가이드로 발행
    "스마트폰·모바일": "스마트폰·모바일", "PC·노트북": "PC·노트북", "가전·디지털": "가전·디지털",
    "자동차·모빌리티": "자동차·모빌리티", "AI·IT": "AI·IT",
}
BODY_MIN = 4500  # HTML 기준 하한(태그 포함) — "길고 상세" 지시

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wp_tech_post")

_SYSTEM = """너는 IT 전문 블로그 'tech.hyunjiunni.com(형수의 테크공장)'의 수석 필자다.
페르소나: 10년차 IT 엔지니어 — 원리를 이해시키고, 실무에서 검증한 순서로 해결한다.
독자: 구글에서 문제를 검색해 들어온 사람. 광고 없는 담백한 전문가 문서 톤(존댓말).

[정확성 — 최우선]
- ★검색으로 확인된 사실만. 메뉴 경로·명령어·버전은 근거 있을 때만 구체적으로,
  불확실하면 "버전에 따라 다를 수 있음"으로 일반화. 지어낸 경로·명령은 최악의 오류.
- 명령어는 <pre><code> 블록에 한 줄씩.

[출력 — 반드시 이 형식]
TITLE: {검색 키워드 선두 배치, 45자 이내}
SLUG: {english-lowercase-3-5words}
EXCERPT: {검색결과 스니펫용 요약 2문장}
---
{본문 HTML}

[본문 HTML 규칙]
- 허용 태그만: h2 h3 p ul ol li pre code table thead tbody tr th td strong em blockquote
- 구조는 주제 성격에 맞게 둘 중 하나(2026-07-19: 카테고리 8종 확장):
  ①문제해결형(오류·고장·설정 문제): 도입 2~3문단(문제 정의+결론 예고) → <h2>왜 이런 문제가
  생기는가(원리 4~6문단) → <h2>해결 방법(효과 큰 순서, <h3>단계별 — '무엇을/어디서/왜')
  → <h2>전문가 팁·예방 → <h2>그래도 안 될 때(체크 항목 — 명사형 짧게)
  ②선택·활용 가이드형(구매 기준·비교·활용법): 도입 2~3문단(결론 요약 — 뭘 기준으로 고르면
  되는지 먼저) → <h2>고르기 전에 알아야 할 원리(스펙 읽는 법 4~6문단) → <h2>기준별 상세
  (<h3>기준마다 — 왜 중요한지/어떤 상황에 뭘 볼지) → <h2>상황별 추천 기준(가격대·용도별,
  특정 제품 광고성 추천 금지 — '이런 조건이면 이런 스펙' 형식) → <h2>구매·사용 전 체크리스트
  공통 마무리: <h2>자주 묻는 질문(<h3>질문 + 답 2~3문단, 3개) → 마무리 2문단
- 분량: 본문 텍스트 3,000자 이상(한국어 기준). 같은 말 반복으로 늘리기 금지 — 깊이로 늘려라.
- 표는 필요할 때만 1개(설정값·방법 비교). 이모지·마크다운·인라인 style 금지.
"""


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _pick_topic() -> dict | None:
    pool = _load(POOL_PATH, {}).get("topics", [])
    hist = _load(HIST_PATH, [])
    done = {h.get("id") for h in hist}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    # 하루 상한 가드 (2026-07-20: 발행량 확대 — 크론 2슬롯 운영. 슬롯이 겹쳐도 상한까지만 발행.
    # 기본 1건, TECH_WP_DAILY_MAX로 상향. 각 슬롯은 직전 발행분을 이력에서 보고 다른 주제·카테고리를 뽑음.)
    today_cnt = sum(1 for h in hist if h.get("date") == today and h.get("status") == "posted")
    if today_cnt >= TECH_WP_DAILY_MAX:
        logger.info(f"오늘 WP 가이드 {today_cnt}건 발행 — 하루 상한({TECH_WP_DAILY_MAX}) 도달, 스킵")
        return None
    cutoff = (datetime.now(KST) - timedelta(days=CROSS_EXCLUDE_DAYS)).strftime("%Y-%m-%d")
    cross = {h.get("id") for h in _load(CROSS_HIST_PATH, []) if h.get("date", "") >= cutoff}
    fresh = [t for t in pool if t.get("id") not in done and t.get("id") not in cross]
    if cross:
        logger.info(f"교차 배제: 네이버 트랙 최근 {CROSS_EXCLUDE_DAYS}일 주제 {len(cross)}건 제외")
    if not fresh:
        logger.warning("주제 풀 소진(WP) — 보충 필요")
        return None
    last_cat = next((h.get("category") for h in reversed(hist) if h.get("status") == "posted"), "")
    alt = [t for t in fresh if t.get("category") != last_cat]
    # 풀 뒤에서부터 소비: 네이버 트랙(앞에서부터)과 이력 커밋 유실 시에도 동일 주제 충돌 없음
    return (alt or fresh)[-1]


def _generate(topic: dict, api_key: str) -> dict | None:
    user = (f"주제: {topic['keyword']}\n카테고리: {topic['category']}\n"
            f"포인트 힌트: {topic.get('hint', '')}\n\n"
            "구글 검색 유입 독자가 끝까지 읽고 해결하는 심층 가이드를 작성하라. "
            "최신 정보는 검색으로 확인해 반영하라.")
    extra = ""
    for attempt in range(1, 4):
        raw = _gen_text(api_key, user + extra, _SYSTEM, 8192, 0.7, use_search=True)
        if not raw:
            continue
        m = re.search(r"TITLE:\s*(.+)", raw)
        s = re.search(r"SLUG:\s*([a-z0-9-]+)", raw)
        e = re.search(r"EXCERPT:\s*(.+)", raw)
        body = raw.split("---", 1)[1].strip() if "---" in raw else ""
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
        body = re.sub(r"```html|```", "", body).strip()
        if not (m and s and body):
            extra = "\n\n[재작성] 출력 형식(TITLE/SLUG/EXCERPT/---/HTML)을 정확히 지켜라."
            continue
        text_len = len(re.sub(r"<[^>]+>", "", body))
        h2s = body.count("<h2")
        if text_len < 3000 or h2s < 4:
            extra = (f"\n\n[재작성] 직전 원고 본문 {text_len}자·h2 {h2s}개로 부족. 구조 유지하며 "
                     "각 섹션을 더 깊게 3,200자 이상으로 다시 써라.")
            logger.warning(f"WP 가이드 짧음({text_len}자, h2 {h2s}) — 재생성")
            continue
        return {"title": m.group(1).strip(), "slug": s.group(1).strip(),
                "excerpt": (e.group(1).strip() if e else ""), "html": body, "chars": text_len}
    return None


def _auth():
    return (WP_USER, WP_PW)


_CAT_ACCENT = {"PC 오류해결·설정": (59, 130, 246), "AI 활용·자동화": (168, 85, 247),
               "오피스·툴 활용": (16, 185, 129),
               "스마트폰·모바일": (14, 165, 233), "PC·노트북": (99, 102, 241),
               "가전·디지털": (245, 158, 11), "자동차·모빌리티": (239, 68, 68),
               "AI·IT": (20, 184, 166)}

_FONT_CANDS = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
               "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
               "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]


def _make_featured(title: str, category: str) -> str | None:
    """대표 이미지(1200×630, og 규격) PIL 생성 — 다크 그라디언트+카테고리 액센트+제목.
    2026-07-19 사용자 피드백(이미지 0장): 목록·공유 썸네일 공백 해소. Playwright 없이 경량."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import tempfile
        W, H = 1200, 630
        img = Image.new("RGB", (W, H), (17, 24, 39))
        dr = ImageDraw.Draw(img)
        for y in range(H):  # 상→하 미묘한 그라디언트
            t = y / H
            dr.line([(0, y), (W, y)], fill=(int(17 + 10 * t), int(24 + 12 * t), int(39 + 22 * t)))
        ac = _CAT_ACCENT.get(category, (59, 130, 246))
        dr.rectangle([0, 0, 14, H], fill=ac)
        font_path = next((f for f in _FONT_CANDS if os.path.exists(f)), None)
        if not font_path:
            logger.warning("한글 폰트 없음 — 대표 이미지 생략")
            return None
        f_label = ImageFont.truetype(font_path, 34)
        f_title = ImageFont.truetype(font_path, 64)
        f_brand = ImageFont.truetype(font_path, 30)
        dr.rounded_rectangle([70, 70, 70 + f_label.getlength(category) + 44, 128],
                             radius=14, fill=(31, 41, 59), outline=ac, width=2)
        dr.text((92, 82), category, font=f_label, fill=(229, 231, 235))
        # 제목 워드랩(공백 우선)
        words, lines, cur = title.split(), [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if f_title.getlength(trial) > W - 160 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        lines.append(cur)
        y = 210
        for ln in lines[:4]:
            dr.text((74, y), ln, font=f_title, fill=(249, 250, 251))
            y += 84
        dr.text((74, H - 78), "형수의 테크공장  ·  tech.hyunjiunni.com", font=f_brand, fill=(148, 163, 184))
        out = os.path.join(tempfile.gettempdir(), "wp_tech_featured.png")
        img.save(out, "PNG")
        return out
    except Exception as ex:
        logger.warning(f"대표 이미지 생성 실패(이미지 없이 진행): {ex}")
        return None


def _upload_featured(path: str, slug: str) -> int | None:
    try:
        with open(path, "rb") as fh:
            r = requests.post(f"{WP_URL}/wp-json/wp/v2/media", auth=_auth(), timeout=60,
                              headers={"Content-Disposition": f'attachment; filename="{slug}.png"',
                                       "Content-Type": "image/png"},
                              data=fh.read())
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.warning(f"미디어 업로드 실패: {r.status_code}")
    except Exception as ex:
        logger.warning(f"미디어 업로드 예외: {ex}")
    return None


def _ensure_category(name: str) -> int | None:
    try:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/categories", params={"search": name, "per_page": 20},
                         auth=_auth(), timeout=20)
        for c in r.json():
            if c.get("name") == name:
                return c["id"]
        r = requests.post(f"{WP_URL}/wp-json/wp/v2/categories", json={"name": name},
                          auth=_auth(), timeout=20)
        if r.status_code in (200, 201):
            return r.json()["id"]
        logger.warning(f"카테고리 생성 실패: {r.status_code} {r.text[:100]}")
    except Exception as ex:
        logger.warning(f"카테고리 처리 실패: {ex}")
    return None


def main():
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key or not WP_PW:
        logger.error("GOOGLE_API_KEY 또는 TECH_WP_APP_PW 없음")
        sys.exit(1)
    dry = os.environ.get("DRY_RUN", "false").lower() == "true"
    forced = os.environ.get("FORCE_TOPIC_ID", "").strip()
    if forced:
        topic = next((t for t in _load(POOL_PATH, {}).get("topics", []) if t.get("id") == forced), None)
    else:
        topic = _pick_topic()
    if not topic:
        return
    logger.info(f"주제: [{topic['category']}] {topic['keyword']}")
    post = _generate(topic, api_key)
    if not post:
        logger.error("생성 실패")
        sys.exit(1)
    logger.info(f"제목: {post['title']} ({post['chars']}자)")
    if dry:
        logger.info("[DRY_RUN] 발행 생략")
        return
    cat_id = _ensure_category(WP_CATEGORY_MAP.get(topic["category"], topic["category"]))
    payload = {"title": post["title"], "slug": post["slug"], "content": post["html"],
               "excerpt": post["excerpt"], "status": os.environ.get("WP_STATUS", "publish")}
    if cat_id:
        payload["categories"] = [cat_id]
    card = _make_featured(post["title"], topic["category"])
    if card:
        media_id = _upload_featured(card, post["slug"])
        if media_id:
            payload["featured_media"] = media_id
            logger.info(f"대표 이미지 첨부(media {media_id})")
    r = requests.post(f"{WP_URL}/wp-json/wp/v2/posts", json=payload, auth=_auth(), timeout=60)
    ok = r.status_code in (200, 201)
    link = r.json().get("link", "") if ok else ""
    hist = _load(HIST_PATH, [])
    hist.append({"id": topic["id"], "date": datetime.now(KST).strftime("%Y-%m-%d"),
                 "timestamp": datetime.now(KST).isoformat(timespec="seconds"),
                 "keyword": topic["keyword"], "category": topic["category"],
                 "title": post["title"], "post_url": link,
                 "status": "posted" if ok else "failed"})
    json.dump(hist, open(HIST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    logger.info(f"발행 {'성공' if ok else '실패 ' + str(r.status_code)}: {link}")
    if not ok:
        sys.exit(1)
    # IndexNow 핑(빙) — 키가 서버 공용이라 러너에서 처리, 여기선 URL만 로그
    print(f"POST_URL={link}")


if __name__ == "__main__":
    main()
