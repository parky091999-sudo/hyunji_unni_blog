"""
HTML/CSS 템플릿 + Playwright 스크린샷으로 고품질 인포그래픽 생성.
PIL 대비 장점: backdrop-filter blur, CSS gradient, box-shadow, 완벽한 한국어 폰트.
"""
import asyncio
import logging
import tempfile
from html import escape

logger = logging.getLogger(__name__)

W, H = 900, 500

_STYLES: dict[str, dict] = {
    "금융재테크": {
        "bg":          "linear-gradient(145deg, #071543 0%, #0D2B7E 45%, #1055BE 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0D1B3E",
        "card_border": "#1E78FF",
        "badge":       "현지언니  생활금융",
        "footer":      "금융·재테크 총정리",
    },
    "세금절세": {
        "bg":          "linear-gradient(145deg, #3D0C00 0%, #7A1500 45%, #C43800 100%)",
        "accent":      "#FFD740",
        "tag_color":   "#2D0900",
        "card_border": "#FF6D00",
        "badge":       "현지언니  세금·절세",
        "footer":      "세금·절세 총정리",
    },
    "보험": {
        "bg":          "linear-gradient(145deg, #00222E 0%, #00474F 45%, #006064 100%)",
        "accent":      "#80FFEA",
        "tag_color":   "#00222E",
        "card_border": "#00BFA5",
        "badge":       "현지언니  보험 가이드",
        "footer":      "보험 핵심 정리",
    },
    "부동산주거": {
        "bg":          "linear-gradient(145deg, #0D0028 0%, #2D0076 45%, #5500CC 100%)",
        "accent":      "#CCFF90",
        "tag_color":   "#0D0028",
        "card_border": "#AA00FF",
        "badge":       "현지언니  부동산·주거",
        "footer":      "부동산·주거 총정리",
    },
    "정부지원혜택": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
    },
    "gov": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
    },
    "health": {
        "bg":          "linear-gradient(145deg, #071A07 0%, #1B5E20 45%, #2E7D32 100%)",
        "accent":      "#B9F6CA",
        "tag_color":   "#071A07",
        "card_border": "#4CAF50",
        "badge":       "현지언니  건강·의료",
        "footer":      "건강 정보 총정리",
    },
}
_DEFAULT = _STYLES["금융재테크"]


def _build_html(
    display_title: str,
    badge: str,
    footer: str,
    bullets: list[str] | None,
    style: dict,
) -> str:
    acc        = style["accent"]
    tag_c      = style["tag_color"]
    bg         = style["bg"]
    card_top_c = style["card_border"]

    n    = len(bullets) if bullets else 0
    cols = 3 if n == 3 else 2
    rows = max(1, (n + cols - 1) // cols) if n else 0
    # 2행이면 카드 높이 줄여서 여백 확보
    card_h = 70 if rows > 1 else 88

    # 카드 HTML
    cards_html = ""
    if bullets:
        for i, b in enumerate(bullets, 1):
            cards_html += f"""
        <div class="info-card">
          <div class="num">{"0" if i < 10 else ""}{i}</div>
          <div class="card-text">{escape(b)}</div>
        </div>"""

    cards_block = f"""
    <div class="cards" style="grid-template-columns:repeat({cols},1fr);">
      {cards_html}
    </div>""" if n > 0 else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@500;700;900&display=swap');

*{{margin:0;padding:0;box-sizing:border-box;}}
body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent;}}

.wrap{{
  width:{W}px;height:{H}px;
  background:{bg};
  position:relative;overflow:hidden;
  font-family:'Noto Sans KR','Malgun Gothic','맑은 고딕','NanumGothicBold',sans-serif;
}}

/* 배경 보케 */
.wrap::before{{
  content:'';position:absolute;
  width:400px;height:400px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,255,255,.08) 0%,transparent 65%);
  top:-120px;right:-80px;pointer-events:none;
}}
.wrap::after{{
  content:'';position:absolute;
  width:260px;height:260px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,255,255,.04) 0%,transparent 65%);
  bottom:-80px;left:90px;pointer-events:none;
}}

/* 상하 액센트 라인 */
.line-top{{position:absolute;top:0;left:0;right:0;height:5px;background:{acc};}}
.line-bot{{position:absolute;bottom:0;left:0;right:0;height:5px;background:{acc};}}

/* 귀퉁이 다이아몬드 */
.corner{{position:absolute;color:{acc};font-size:13px;opacity:.9;line-height:1;}}
.tl{{top:18px;left:34px;}} .tr{{top:18px;right:34px;}}
.bl{{bottom:10px;left:34px;}} .br{{bottom:10px;right:34px;}}

/* 배지 */
.badge{{
  position:absolute;top:14px;left:50%;transform:translateX(-50%);
  background:{acc};color:{tag_c};
  padding:7px 28px;border-radius:999px;
  font-size:14px;font-weight:700;white-space:nowrap;letter-spacing:.3px;
  box-shadow:0 3px 12px rgba(0,0,0,.3);
  z-index:10;
}}

/* 메인 콘텐츠: 배지 아래~푸터 위를 flexbox로 수직 균등 배분 */
.main{{
  position:absolute;
  top:54px;bottom:30px;left:0;right:0;
  display:flex;flex-direction:column;
  align-items:center;
  justify-content:{'space-evenly' if n > 0 else 'center'};
  padding:0 46px;
}}

/* 제목 */
.title{{
  text-align:center;
  color:{acc};font-size:52px;font-weight:900;
  line-height:1.22;
  word-break:keep-all;
  text-shadow:2px 3px 14px rgba(0,0,0,.55);
  width:100%;
}}

/* 카드 그리드 */
.cards{{
  width:100%;
  display:grid;gap:10px;
}}

.info-card{{
  background:rgba(255,255,255,.10);
  backdrop-filter:blur(18px);
  -webkit-backdrop-filter:blur(18px);
  border:1px solid rgba(255,255,255,.18);
  border-top:4px solid {card_top_c};
  border-radius:13px;
  padding:0 20px;
  height:{card_h}px;
  display:flex;align-items:center;gap:14px;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.2),
    0 6px 28px rgba(0,0,0,.25);
}}

.num{{
  min-width:30px;height:30px;border-radius:50%;
  background:{acc};color:{tag_c};
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:800;flex-shrink:0;
  box-shadow:0 2px 8px rgba(0,0,0,.2);
}}

.card-text{{
  color:rgba(238,248,255,.95);
  font-size:17px;font-weight:600;
  line-height:1.4;word-break:keep-all;
}}

/* 푸터 */
.footer{{
  position:absolute;bottom:11px;left:0;right:0;
  text-align:center;
  color:rgba(200,225,255,.65);
  font-size:14px;font-weight:500;letter-spacing:.5px;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="line-top"></div>
  <div class="line-bot"></div>
  <span class="corner tl">◆</span>
  <span class="corner tr">◆</span>
  <span class="corner bl">◆</span>
  <span class="corner br">◆</span>
  <div class="badge">{escape(badge)}</div>
  <div class="main">
    <div class="title">{escape(display_title)}</div>
    {cards_block}
  </div>
  <div class="footer">{escape(footer)}</div>
</div>
</body>
</html>"""


async def _pw_screenshot(html: str) -> bytes:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
        )
        try:
            ctx = await browser.new_context(
                viewport={"width": W, "height": H},
                device_scale_factor=2,  # 레티나 품질
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=18000)
            await page.wait_for_timeout(400)  # 폰트 렌더 안정화
            data = await page.screenshot(
                clip={"x": 0, "y": 0, "width": W, "height": H},
                type="png",
            )
            return data
        finally:
            await browser.close()


def create_infographic_via_html(
    title: str,
    keyword: str = "",
    category: str = "금융재테크",
    bullets: list[str] | None = None,
) -> str | None:
    """
    HTML/CSS + Playwright 스크린샷 인포그래픽. 실패 시 None 반환.
    호출자가 PIL 폴백을 처리해야 함.
    """
    style = _STYLES.get(category, _DEFAULT)

    display = keyword.strip() if keyword and keyword.strip() else title.split("|")[0].strip()
    if len(display) > 22:
        display = display[:22]

    clean_bullets = [b[:28] for b in (bullets or [])[:4]] or None
    html = _build_html(display, style["badge"], style["footer"], clean_bullets, style)

    try:
        screenshot = asyncio.run(_pw_screenshot(html))
    except RuntimeError as e:
        logger.warning(f"asyncio 루프 충돌 — HTML 인포그래픽 스킵: {e}")
        return None
    except Exception as e:
        logger.warning(f"Playwright 스크린샷 실패: {e}")
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(screenshot)
    tmp.close()
    logger.info(f"HTML 인포그래픽 생성: {display!r} [{category}] → {tmp.name}")
    return tmp.name
