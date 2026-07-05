"""
HTML/CSS 템플릿 + Playwright 스크린샷으로 고품질 인포그래픽 생성.
가로로 긴 캔버스(1600×900), 중앙 900×900이 썸네일 크롭 영역 — 제목은 항상 그 안에.

썸네일 가독성 최우선 재설계(2026-07-04, 실물 피드백):
- 다크 그라디언트 배경 + 흰색 초대형 제목(최대 2줄, 라인당 실측 폭 기준 90~165px)
  → 150px 축소 썸네일에서도 제목이 읽히는 것이 목표.
- 크롭 영역(가운데 900×900) 안에는 핵심 키워드·작은 브랜드·카테고리 칩만.
  차트 막대 장식은 저투명도 배경 요소로 깔림(텍스트가 항상 위).
- 불릿 날개(오른쪽 작은 요약 텍스트)는 제거(2026-07-05 피드백) — 본문 표시 크기에서
  읽히지 않고 헤더 바로 아래 요약블록과 중복이라 제목 중심 구성만 유지.
- 카테고리별 강조색 시스템(빨강/보라/파랑 등)은 유지.
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


# 크롭 영역(900px) 안에서 제목이 쓸 수 있는 실제 폭. 좌우 24px 여유.
_TITLE_SAFE_PX = 850


def _char_units(text: str) -> float:
    """Noto Sans KR 기준 대략적인 문자 폭(em 단위) 추정. 한글/CJK≈1.0em, 영문/숫자는 더 좁음."""
    u = 0.0
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F or 0x4E00 <= o <= 0x9FFF or ch in "…％":
            u += 1.0
        elif ch == " ":
            u += 0.30
        elif ch.isdigit():
            u += 0.62
        elif ch.isupper():
            u += 0.74
        else:
            u += 0.55
    return max(u, 0.5)


def _layout_title(text: str) -> tuple[list[str], int]:
    """
    제목을 1~2줄로 배치하고 폰트 크기(px)를 결정.
    목표: 크롭 폭의 80%+ 를 채우는 초대형 폰트(90px+), 150px 축소에서도 판독 가능.
    """
    one_line_font = _TITLE_SAFE_PX / _char_units(text)
    words = text.split()

    # 한 줄로도 충분히 크면 한 줄 유지
    if one_line_font >= 104 or len(words) <= 1:
        if len(words) <= 1 and one_line_font < 88 and len(text) > 8:
            # 공백 없는 긴 덩어리 → 글자 단위로 반 나눔
            mid = len(text) // 2
            lines = [text[:mid], text[mid:]]
        else:
            lines = [text]
    else:
        # 두 줄 분할: 양쪽 줄 폭이 가장 균형 잡히는 공백 위치 선택
        best_lines, best_max = [text], _char_units(text)
        for i in range(1, len(words)):
            l1, l2 = " ".join(words[:i]), " ".join(words[i:])
            m = max(_char_units(l1), _char_units(l2))
            if m < best_max:
                best_max, best_lines = m, [l1, l2]
        lines = best_lines

    max_units = max(_char_units(ln) for ln in lines)
    font = int(_TITLE_SAFE_PX / max_units)
    font = max(72, min(font, 170))  # 하한 72는 안전장치 — 키워드 절단 로직상 실제론 85px+
    return lines, font


def _build_html(display_title: str, bullets: list[str] | None, style: dict) -> str:
    bg_dark   = style["bg"]          # 구 PIL 카드의 다크 그라디언트 재활용
    accent    = style["accent"]
    tag_color = style["tag_color"]
    label     = style["label"]
    icons     = style.get("icons", ["💡", "📌", "✅", "🔑"])

    lines, tf = _layout_title(display_title)
    title_html = "<br>".join(escape(ln) for ln in lines)

    # ── 배경 장식: 저투명도 차트 막대(카테고리 색) — 텍스트 뒤에 깔리는 분위기 요소 ──
    bar_heights = [22, 34, 28, 46, 38, 58, 50, 72, 62, 84, 74, 92, 82, 96]
    bars_html = "".join(
        f'<div class="bar" style="height:{h}%;"></div>' for h in bar_heights
    )

    # 불릿 날개 제거(2026-07-05 사용자 피드백): 21px 텍스트는 본문 표시 크기에서
    # 읽히지 않고, 같은 내용이 헤더 바로 아래 요약블록에 크게 나와 중복 — 제목 중심 유지.
    # (bullets 인자는 호출부 호환을 위해 유지하되 렌더하지 않음)
    _ = bullets

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
  background:{bg_dark};
  font-family:'Noto Sans KR','Malgun Gothic','맑은 고딕',sans-serif;
  overflow:hidden;
}}

/* 카테고리 색 인지용 하단 액센트 바 — 축소돼도 색 정체성이 남는다 */
.edge{{
  position:absolute;left:0;right:0;bottom:0;height:18px;
  background:{accent};
}}

/* ── 배경 장식(저투명도) — 텍스트 아래 레이어 ── */
.glow{{
  position:absolute;
  left:50%;top:44%;transform:translate(-50%,-50%);
  width:1100px;height:700px;border-radius:50%;
  background:radial-gradient(closest-side, rgba(255,255,255,.10), transparent 70%);
  pointer-events:none;
}}
.bars{{
  position:absolute;left:0;right:0;bottom:18px;height:46%;
  display:flex;align-items:flex-end;gap:34px;
  padding:0 60px;
  opacity:.13;
  pointer-events:none;
}}
.bar{{
  flex:1;
  background:linear-gradient(to top, {accent}, transparent 130%);
  border-radius:10px 10px 0 0;
}}
/* 카테고리 아이콘 — 크롭 바깥 왼쪽 날개, 전체보기 전용 장식 */
.sideicon{{
  position:absolute;
  left:40px;top:50%;transform:translateY(-50%);
  font-size:260px;line-height:1;
  opacity:.12;
  pointer-events:none;user-select:none;
}}

/* ── 크롭 안전영역(가운데 900×900) 안: 칩 + 초대형 제목 + 브랜드만 ── */
.center{{
  position:absolute;
  left:{(W - H) // 2}px;width:{H}px;top:0;height:{H}px;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:34px;
  padding:0 24px 30px;
}}
.chip{{
  background:{accent};
  color:{tag_color};
  font-size:30px;font-weight:800;
  padding:10px 34px;
  border-radius:999px;
  letter-spacing:.5px;
}}
.title{{
  font-size:{tf}px;font-weight:900;
  color:#FFFFFF;
  line-height:1.14;
  letter-spacing:-2px;
  text-align:center;
  word-break:keep-all;
  white-space:nowrap;
  text-shadow:0 4px 24px rgba(0,0,0,.45);
}}
.underline{{
  width:150px;height:12px;border-radius:6px;
  background:{accent};
}}
.brand{{
  position:absolute;
  left:50%;bottom:52px;transform:translateX(-50%);
  font-size:26px;font-weight:700;
  color:rgba(255,255,255,.60);
  letter-spacing:2px;
}}

</style>
</head>
<body>
<div class="wrap">
  <div class="glow"></div>
  <div class="bars">{bars_html}</div>
  <div class="sideicon">{icons[0] if icons else "💡"}</div>

  <div class="center">
    <div class="chip">{escape(label)}</div>
    <div class="title">{title_html}</div>
    <div class="underline"></div>
    <div class="brand">현지언니</div>
  </div>


  <div class="edge"></div>
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
    다크 배경 + 초대형 흰 제목(최대 2줄) — 썸네일 가독성 최우선. 실패 시 None 반환.
    """
    import re

    style = _STYLES.get(category, _DEFAULT)

    display = keyword.strip() if keyword and keyword.strip() else title.split("|")[0].strip()
    # 썸네일엔 핵심 키워드만: 앞머리 날짜("2026년 7월 4일" 등)와 괄호 부연은 제거
    display = re.sub(r"^\s*\d{4}년\s*\d{1,2}월(\s*\d{1,2}일)?[\s,·:~-]*", "", display)
    display = re.sub(r"\([^)]*\)", "", display).strip(" ,·|-") or display
    # 폰트가 90px 아래로 내려가지 않도록 길이 자체를 제한(단어경계+말줄임표)
    if len(display) > 18:
        cut = display[:18]
        sp = cut.rfind(" ")
        if sp >= 9:
            cut = cut[:sp]
        display = cut.rstrip(" ,·") + "…"

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
