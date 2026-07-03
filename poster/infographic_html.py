"""
HTML/CSS 템플릿 + Playwright 스크린샷으로 고품질 인포그래픽 생성.
가로로 긴 캔버스(1600×900), 중앙 900×900이 썸네일 크롭 영역 — 제목은 항상 그 안에.
구조: 컬러 테두리 프레임 → 가운데 정렬 1줄 제목 → 키워드바 → 핵심 통계 카드 3~4개(아이콘/라벨 없이 텍스트만).
"""
import asyncio
import logging
import tempfile
from html import escape

logger = logging.getLogger(__name__)

W = 1600  # 캔버스 폭(가로로 김)
H = 900   # 캔버스 높이 — 썸네일 크롭은 가운데 900×900(x: (W-H)/2 ~ (W+H)/2)

_STYLES: dict[str, dict] = {
    "금융재테크": {
        # PIL 폴백용 보존
        "bg":          "linear-gradient(145deg, #071543 0%, #0D2B7E 45%, #1055BE 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0D1B3E",
        "card_border": "#1E78FF",
        "badge":       "현지언니  생활금융",
        "footer":      "금융·재테크 총정리",
        # 라이트 스타일
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "금융·재테크",
        "icons":     ["💰", "🏦", "💳", "📈"],
        "cta":       "지금 바로 확인해보세요!",
        "sub_below": "핵심 가이드 총정리",
    },
    "세금절세": {
        "bg":          "linear-gradient(145deg, #3D0C00 0%, #7A1500 45%, #C43800 100%)",
        "accent":      "#FFD740",
        "tag_color":   "#2D0900",
        "card_border": "#FF6D00",
        "badge":       "현지언니  세금·절세",
        "footer":      "세금·절세 총정리",
        "color":     "#C62828",
        "bg_light":  "#FFF4F2",
        "label":     "세금·절세",
        "icons":     ["📋", "💹", "📊", "💡"],
        "cta":       "놓치지 말고 확인하세요!",
        "sub_below": "절세 전략 총정리",
    },
    "보험": {
        "bg":          "linear-gradient(145deg, #00222E 0%, #00474F 45%, #006064 100%)",
        "accent":      "#80FFEA",
        "tag_color":   "#00222E",
        "card_border": "#00BFA5",
        "badge":       "현지언니  보험 가이드",
        "footer":      "보험 핵심 정리",
        "color":     "#00695C",
        "bg_light":  "#EDFAFA",
        "label":     "보험 가이드",
        "icons":     ["🛡️", "💊", "📝", "✅"],
        "cta":       "보험료 아끼는 방법 확인!",
        "sub_below": "보험 핵심 총정리",
    },
    "부동산주거": {
        "bg":          "linear-gradient(145deg, #0D0028 0%, #2D0076 45%, #5500CC 100%)",
        "accent":      "#CCFF90",
        "tag_color":   "#0D0028",
        "card_border": "#AA00FF",
        "badge":       "현지언니  부동산·주거",
        "footer":      "부동산·주거 총정리",
        "color":     "#4527A0",
        "bg_light":  "#F4EEFF",
        "label":     "부동산·주거",
        "icons":     ["🏠", "📜", "🔑", "✅"],
        "cta":       "꼭 알아야 할 핵심 정보!",
        "sub_below": "부동산 정보 총정리",
    },
    "정부지원혜택": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "정부지원",
        "icons":     ["🏛️", "💰", "📋", "✅"],
        "cta":       "혜택 놓치지 마세요!",
        "sub_below": "정부지원 혜택 총정리",
    },
    "gov": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "정부지원",
        "icons":     ["🏛️", "💰", "📋", "✅"],
        "cta":       "혜택 놓치지 마세요!",
        "sub_below": "정부지원 혜택 총정리",
    },
    "health": {
        "bg":          "linear-gradient(145deg, #071A07 0%, #1B5E20 45%, #2E7D32 100%)",
        "accent":      "#B9F6CA",
        "tag_color":   "#071A07",
        "card_border": "#4CAF50",
        "badge":       "현지언니  건강·의료",
        "footer":      "건강 정보 총정리",
        "color":     "#1B5E20",
        "bg_light":  "#EDFAF5",
        "label":     "건강·의료",
        "icons":     ["❤️", "🏥", "💊", "✅"],
        "cta":       "건강 정보 확인하세요!",
        "sub_below": "건강 정보 총정리",
    },
    "주식분석": {
        "bg":          "linear-gradient(145deg, #3D0A08 0%, #7A1510 45%, #C4341D 100%)",
        "accent":      "#FFB199",
        "tag_color":   "#3D0A08",
        "card_border": "#E74C3C",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "주식 분석",
        "color":     "#C0392B",
        "bg_light":  "#FFEEEA",
        "label":     "주식분석",
        "icons":     ["📈", "🔍", "💹", "✅"],
        "cta":       "오늘의 종목 확인하세요!",
        "sub_below": "종목 심층 분석",
    },
    "공모주": {
        "bg":          "linear-gradient(145deg, #23073D 0%, #4B1580 45%, #7B2FC4 100%)",
        "accent":      "#E0B3FF",
        "tag_color":   "#23073D",
        "card_border": "#8E44AD",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "공모주 캘린더",
        "color":     "#7B2FA0",
        "bg_light":  "#F7EEFA",
        "label":     "공모주",
        "icons":     ["🎟️", "📅", "💰", "✅"],
        "cta":       "청약 일정 확인하세요!",
        "sub_below": "공모주 캘린더",
    },
    "주식etf": {
        "bg":          "linear-gradient(145deg, #06213D 0%, #0E4B80 45%, #1878C4 100%)",
        "accent":      "#A8DBFF",
        "tag_color":   "#06213D",
        "card_border": "#2980B9",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "ETF 인사이트",
        "color":     "#1F6FAE",
        "bg_light":  "#EAF4FC",
        "label":     "ETF",
        "icons":     ["📊", "💼", "📈", "✅"],
        "cta":       "핵심 ETF 확인하세요!",
        "sub_below": "ETF 인사이트",
    },
}
_DEFAULT = _STYLES["금융재테크"]


def _title_fontsize(text: str) -> int:
    # 제목을 3줄→1줄로 합치면서 실측 폭 기준으로 재조정. 썸네일 크롭 영역(가운데 900px
    # 폭)을 절대 벗어나면 안 되므로 여유를 두고 계산(한글 위주 텍스트가 더 넓게 잡힘).
    n = len(text)
    if n <= 4:  return 150
    if n <= 6:  return 130
    if n <= 8:  return 108
    if n <= 10: return 92
    if n <= 13: return 74
    if n <= 18: return 58
    return 46


def _build_html(display_title: str, bullets: list[str] | None, style: dict) -> str:
    color    = style["color"]
    bg_light = style["bg_light"]
    label    = style["label"]
    icons    = style.get("icons", ["💡", "📌", "✅", "🔑"])

    n = min(len(bullets) if bullets else 0, 4)
    tf = _title_fontsize(display_title)

    # 구분바 키워드 (불릿 첫 단어들)
    if bullets and n > 0:
        kws = " · ".join(b.split()[0] for b in bullets[:n])
        divider_text = f"📌 {kws}까지!"
    else:
        divider_text = f"📌 {label} 핵심 정보 한눈에 확인!"

    # 하단 카드 — 아이콘·"핵심 0N" 라벨 없이 텍스트만 크게 채운다.
    def _short_bullet(b: str, limit: int = 30) -> str:
        if len(b) <= limit:
            return b
        cut = b[:limit]
        sp = cut.rfind(" ")
        if sp >= limit - 8:
            cut = cut[:sp]
        return cut.rstrip() + "…"

    cards_html = ""
    if n > 0:
        for b in bullets[:n]:
            short = _short_bullet(b)
            cards_html += f"""
      <div class="bcard">
        <div class="btext">{escape(short)}</div>
      </div>"""

    cards_section = f"""
  <div class="bcards" style="grid-template-columns:repeat({n},1fr);">
    {cards_html}
  </div>""" if n > 0 else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900&display=swap');

*{{margin:0;padding:0;box-sizing:border-box;}}
body{{width:{W}px;height:{H}px;overflow:hidden;}}

.wrap{{
  position:relative;
  width:{W}px;height:{H}px;
  background:{bg_light};
  border:16px solid {color};
  display:flex;flex-direction:column;
  font-family:'Noto Sans KR','Malgun Gothic','맑은 고딕',sans-serif;
  overflow:hidden;
}}

/* 브랜드 워터마크 — 크롭 안전영역(가운데 정사각형) 바깥에 둬 썸네일 가독성엔 영향 없이
   전체보기에서만 "현지언니" 브랜드를 각인시킨다(배지 삭제로 사라진 브랜딩 최소 복원). */
.brand{{
  position:absolute;
  left:38px;top:30px;
  font-size:22px;font-weight:800;
  color:{color};
  opacity:.5;
  letter-spacing:.3px;
}}

/* ── 히어로: 가운데 정렬 1줄 제목 (위아래 여백 최소) ── */
.hero{{
  flex:1;
  position:relative;
  padding:0 40px;
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;
}}
/* 남는 공간이 휑해 보이지 않도록 배경에 큰 아이콘을 흐리게 배치.
   썸네일 크롭 영역(가운데 정사각형) 바깥쪽에 위치해 축소본엔 안 나옴 — 전체보기 전용 장식. */
.herobg{{
  position:absolute;
  right:60px;top:50%;transform:translateY(-50%);
  font-size:300px;line-height:1;
  opacity:.10;
  pointer-events:none;
  user-select:none;
}}
.title{{
  font-size:{tf}px;font-weight:900;
  color:{color};
  line-height:1;
  letter-spacing:-1.5px;
  text-align:center;
  word-break:keep-all;
  white-space:nowrap;
}}

/* ── 키워드 구분바 ── */
.divrow{{
  margin:0 42px;
  padding:14px 26px;
  background:white;
  border-left:7px solid {color};
  border-radius:0 14px 14px 0;
  font-size:16px;font-weight:600;color:#555;
  flex-shrink:0;
  box-shadow:0 2px 10px rgba(0,0,0,.06);
  line-height:1.5;
}}

/* ── 하단 통계 카드 (아이콘·라벨 없이 텍스트가 칸을 꽉 채움) ── */
.bcards{{
  display:grid;
  flex-shrink:0;
  margin:16px 42px 26px;
  gap:14px;
}}
.bcard{{
  padding:20px 14px;
  min-height:110px;
  display:flex;align-items:center;justify-content:center;
  background:white;
  border-radius:14px;
  box-shadow:0 2px 10px rgba(0,0,0,.06);
  text-align:center;
}}
.btext{{
  font-size:26px;font-weight:800;color:{color};
  line-height:1.3;word-break:keep-all;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">현지언니</div>

  <div class="hero">
    <div class="herobg">{icons[0] if icons else "💡"}</div>
    <div class="title">{escape(display_title)}</div>
  </div>

  <div class="divrow">{divider_text}</div>

  {cards_section}

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
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=18000)
            await page.wait_for_timeout(400)
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
    HTML/CSS + Playwright 인포그래픽(1600×900, 가운데 900×900이 썸네일 크롭 영역).
    실패 시 None 반환.
    """
    style = _STYLES.get(category, _DEFAULT)

    display = keyword.strip() if keyword and keyword.strip() else title.split("|")[0].strip()
    if len(display) > 22:
        cut = display[:22]
        sp = cut.rfind(" ")
        if sp >= 10:
            cut = cut[:sp]
        display = cut.rstrip() + "…"

    # 자르기는 _build_html의 _short_bullet(단어경계+말줄임표)이 담당하므로 여기선 개수만 제한
    clean_bullets = (bullets or [])[:4] or None
    html = _build_html(display, clean_bullets, style)

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
