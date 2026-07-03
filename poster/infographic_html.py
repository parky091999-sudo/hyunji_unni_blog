"""
HTML/CSS 템플릿 + Playwright 스크린샷으로 고품질 인포그래픽 생성.
정방형 900×900, 흰색 모던. 벤치마크: 온숨(onsumway) 스타일.
구조: 배지 → 3단 제목(회색/대형색상/다크) → 키워드바 → 4아이콘카드 → CTA
"""
import asyncio
import logging
import tempfile
from html import escape

logger = logging.getLogger(__name__)

S = 900  # 정방형

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
}
_DEFAULT = _STYLES["금융재테크"]


def _title_fontsize(text: str) -> int:
    n = len(text)
    if n <= 4:  return 100
    if n <= 6:  return 88
    if n <= 8:  return 76
    if n <= 11: return 62
    return 52


def _build_html(display_title: str, bullets: list[str] | None, style: dict) -> str:
    color    = style["color"]
    bg_light = style["bg_light"]
    label    = style["label"]
    icons    = style.get("icons", ["💡", "📌", "✅", "🔑"])
    cta      = style.get("cta", "지금 바로 확인해보세요!")
    sub_below = style.get("sub_below", "핵심 가이드 총정리")

    n = min(len(bullets) if bullets else 0, 4)

    # 3단 제목 분리: [회색 소자] / [대형 강조색] / [다크 소자]
    words = display_title.split()
    if len(words) >= 2:
        mid = max(1, len(words) // 2)
        t_small  = " ".join(words[:mid])    # 회색 소자 (상단)
        t_accent = " ".join(words[mid:])    # 대형 강조색 (중단)
    else:
        t_small  = label                    # 카테고리명 fallback
        t_accent = display_title
    tf = _title_fontsize(t_accent)

    # 구분바 키워드 (불릿 첫 단어들)
    if bullets and n > 0:
        kws = " · ".join(b.split()[0] for b in bullets[:n])
        divider_text = f"📌 {kws}까지!"
    else:
        divider_text = f"📌 {label} 핵심 정보 한눈에 확인!"

    # 하단 아이콘 카드 — 카드 폭에 여유가 있어(2줄 래핑 가능) 18자 컷은 과도했음.
    # 26자까지 허용하고, 정말 넘치면 단어 경계에서 자르고 말줄임표를 붙인다(숫자·단위가
    # 중간에 잘려 의미가 바뀌는 것 방지: 예 "15%"→"15").
    def _short_bullet(b: str, limit: int = 26) -> str:
        if len(b) <= limit:
            return b
        cut = b[:limit]
        sp = cut.rfind(" ")
        if sp >= limit - 8:  # 너무 앞쪽이면 단어경계 포기하고 그냥 자름
            cut = cut[:sp]
        return cut.rstrip() + "…"

    cards_html = ""
    if n > 0:
        for i, b in enumerate(bullets[:n], 1):
            icon  = icons[i - 1] if i <= len(icons) else "💡"
            short = _short_bullet(b)
            cards_html += f"""
      <div class="bcard">
        <div class="bicon">{icon}</div>
        <div class="blabel">핵심 0{i}</div>
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
body{{width:{S}px;height:{S}px;overflow:hidden;}}

.wrap{{
  width:{S}px;height:{S}px;
  background:{bg_light};
  display:flex;flex-direction:column;
  font-family:'Noto Sans KR','Malgun Gothic','맑은 고딕',sans-serif;
  overflow:hidden;
}}

/* ── 상단 배지 ── */
.topbadge{{
  margin:30px 42px 0;
  display:inline-flex;align-items:center;gap:9px;
  background:white;
  border:2px solid {color};
  color:#1A1A2E;
  padding:10px 24px;border-radius:999px;
  font-size:15px;font-weight:700;
  align-self:flex-start;
  box-shadow:0 3px 14px {color}22;
}}
.chk{{color:{color};font-size:17px;font-weight:900;}}

/* ── 히어로 (flex 나머지 공간 모두 차지) ── */
.hero{{
  flex:1;
  position:relative;
  padding:0 54px;
  display:flex;flex-direction:column;
  justify-content:center;
  overflow:hidden;
}}
/* 짧은 제목만 있을 때 남는 공간이 휑해 보이지 않도록 배경에 큰 아이콘을 흐리게 배치 */
.herobg{{
  position:absolute;
  right:-40px;top:50%;transform:translateY(-50%);
  font-size:340px;line-height:1;
  opacity:.10;
  pointer-events:none;
  user-select:none;
}}

/* 3단 제목 */
.ts{{               /* 소자 상단 (회색) */
  font-size:28px;font-weight:800;
  color:#8492A6;
  letter-spacing:-0.3px;
  margin-bottom:2px;
}}
.ta{{               /* 대자 강조색 */
  font-size:{tf}px;font-weight:900;
  color:{color};
  line-height:1.05;
  letter-spacing:-2px;
  word-break:keep-all;
  margin-bottom:8px;
}}
.tb{{               /* 소자 하단 (다크) */
  font-size:30px;font-weight:800;
  color:#1A1A2E;
  letter-spacing:-0.5px;
}}

/* ── 키워드 구분바 ── */
.divrow{{
  margin:0 42px;
  padding:14px 26px;
  background:white;
  border-left:7px solid {color};
  border-radius:0 14px 14px 0;
  font-size:15px;font-weight:600;color:#555;
  flex-shrink:0;
  box-shadow:0 2px 10px rgba(0,0,0,.06);
  line-height:1.5;
}}

/* ── 하단 아이콘 카드 ── */
.bcards{{
  display:grid;
  flex-shrink:0;
  margin-top:14px;
  border-top:1.5px solid #D8E2F0;
}}
.bcard{{
  padding:18px 10px 16px;
  display:flex;flex-direction:column;
  align-items:center;gap:7px;
  background:white;
  border-right:1.5px solid #D8E2F0;
  text-align:center;
}}
.bcard:last-child{{border-right:none;}}
.bicon{{
  width:52px;height:52px;border-radius:50%;
  background:{color}14;
  border:2px solid {color}33;
  display:flex;align-items:center;justify-content:center;
  font-size:22px;
}}
.blabel{{font-size:11px;font-weight:800;color:{color};letter-spacing:.5px;}}
.btext{{font-size:13px;font-weight:700;color:#1A1A2E;line-height:1.4;word-break:keep-all;}}

/* ── CTA 푸터 ── */
.cta{{
  background:{color};
  padding:18px 46px;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;
}}
.ctat{{color:white;font-size:18px;font-weight:800;}}
.ctab{{color:white;font-size:15px;font-weight:900;opacity:.85;letter-spacing:1px;}}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbadge">
    <span class="chk">✓</span>
    현지언니 · {escape(label)}
  </div>

  <div class="hero">
    <div class="herobg">{icons[0] if icons else "💡"}</div>
    <div class="ts">{escape(t_small)}</div>
    <div class="ta">{escape(t_accent)}</div>
    <div class="tb">{escape(sub_below)}</div>
  </div>

  <div class="divrow">{divider_text}</div>

  {cards_section}

  <div class="cta">
    <div class="ctat">{escape(cta)}</div>
    <div class="ctab">현지언니 ✦</div>
  </div>

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
                viewport={"width": S, "height": S},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=18000)
            await page.wait_for_timeout(400)
            data = await page.screenshot(
                clip={"x": 0, "y": 0, "width": S, "height": S},
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
    HTML/CSS + Playwright 정방형 인포그래픽. 실패 시 None 반환.
    """
    style = _STYLES.get(category, _DEFAULT)

    display = keyword.strip() if keyword and keyword.strip() else title.split("|")[0].strip()
    if len(display) > 28:
        display = display[:28]

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
