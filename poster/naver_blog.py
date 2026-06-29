"""
Playwright로 네이버 블로그 자동 포스팅
SE3/SE4 에디터 기반 — 쿠키 세션 재사용으로 로그인 최소화

[핵심 발견사항]
- www.naver.com, GoBlogWrite.naver 는 Akamai CDN이 클라우드 IP 차단
- section.blog.naver.com/BlogHome.naver 는 접근 가능
- 글쓰기 버튼을 BlogHome에서 직접 클릭해야 에디터 진입 가능 (Referer 필요)
- 새 탭이 열리면 그 탭을 에디터 페이지로 사용
- [사진N] 마커: content.py가 body에 삽입 → 마커 위치에 이미지 삽입
"""
import asyncio
import base64
import json
import logging
import os
import random
import re
import tempfile
import urllib.request
from PIL import Image, ImageDraw, ImageFont

from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

ROOT        = os.path.dirname(os.path.dirname(__file__))
COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")
SHOT_DIR    = os.path.join(ROOT, "data", "screenshots")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def _delay(ms_min: int = 300, ms_max: int = 800):
    await asyncio.sleep(random.uniform(ms_min / 1000, ms_max / 1000))


async def _screenshot(page: Page, name: str, full_page: bool = False):
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        path = os.path.join(SHOT_DIR, f"{name}.png")
        await page.screenshot(path=path, full_page=full_page)
        logger.info(f"스크린샷: {path}")
    except Exception as e:
        logger.warning(f"스크린샷 실패: {e}")


async def _save_cookies(ctx: BrowserContext):
    os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
    cookies = await ctx.cookies()
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info(f"쿠키 저장 완료 ({len(cookies)}개)")


async def _load_cookies(ctx: BrowserContext, cookies_json: str = "") -> bool:
    raw = None
    if cookies_json.strip():
        try:
            clean = cookies_json.strip().lstrip('﻿').strip()
            raw = json.loads(clean)
            logger.info(f"환경변수 쿠키 파싱 성공 ({len(raw)}개)")
        except Exception as e:
            logger.warning(f"NAVER_COOKIES JSON 파싱 실패: {e}")

    if raw is None and os.path.exists(COOKIE_PATH):
        try:
            with open(COOKIE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            logger.info(f"파일 쿠키 로드 ({len(raw)}개)")
        except Exception as e:
            logger.warning(f"쿠키 파일 로드 실패: {e}")

    if not raw:
        return False

    clean = []
    for c in raw:
        entry = {k: c[k] for k in ("name", "value", "domain", "path") if k in c}
        if "expires" in c and c["expires"] != -1:
            entry["expires"] = c["expires"]
        if "httpOnly" in c:
            entry["httpOnly"] = c["httpOnly"]
        if "secure" in c:
            entry["secure"] = c["secure"]
        if "sameSite" in c:
            entry["sameSite"] = c["sameSite"]
        clean.append(entry)

    await ctx.add_cookies(clean)
    logger.info(f"쿠키 {len(clean)}개 로드")
    return True


async def _is_logged_in(page: Page) -> bool:
    cookies = await page.context.cookies()
    names = {c["name"] for c in cookies}
    logged = "NID_AUT" in names
    logger.info(f"로그인 쿠키 체크: {'OK' if logged else 'FAIL'} (쿠키: {sorted(names)[:8]})")
    return logged


async def _login(page: Page, naver_id: str, naver_pw: str) -> bool:
    logger.info("네이버 ID/PW 로그인 시도")
    await page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=30000)
    await _delay(1000, 2000)

    await page.locator("#id").fill(naver_id)
    await _delay(300, 600)
    await page.locator("#pw").fill(naver_pw)
    await _delay(400, 700)
    await page.locator("button[type='submit'].btn_login").click()
    await _delay(4000, 6000)
    await _screenshot(page, "after_login")

    cookies = await page.context.cookies()
    if any(c["name"] == "NID_AUT" for c in cookies):
        logger.info("로그인 성공 (NID_AUT 확인)")
        return True

    logger.error(f"로그인 실패 — URL: {page.url}")
    return False


def _is_editor_page(url: str) -> bool:
    """에디터 페이지인지 URL로 판별 (느슨하게)"""
    if not url or "about:blank" in url:
        return False
    good = ["postwrite", "PostWrite", "Redirect=Write", "editForm"]
    return any(g in url for g in good)


async def _navigate_to_write_page(ctx: BrowserContext, page: Page, naver_id: str, blog_id: str) -> Page | None:
    """
    글쓰기 에디터 페이지 진입.
    새 탭이 열리면 그 탭을 반환하고, 현재 페이지면 page 반환.
    실패 시 None 반환.

    핵심: BlogHome에서 직접 CLICK만 사용 (CDN 차단 때문에 goto 불가)
    """
    blog_home_url = "https://section.blog.naver.com/BlogHome.naver"
    logger.info(f"BlogHome 접속: {blog_home_url}")
    await page.goto(blog_home_url, wait_until="domcontentloaded", timeout=30000)
    await _delay(2000, 3000)
    await _screenshot(page, "blog_home")
    logger.info(f"BlogHome URL: {page.url}")

    if "nidlogin" in page.url or "login" in page.url.lower():
        logger.warning("BlogHome이 로그인 페이지로 리다이렉트 — 세션 만료")
        return None

    write_btn_sels = [
        "a:has-text('글쓰기')",
        ".btn_write",
        "a.write_btn",
        "button:has-text('글쓰기')",
        "[href*='GoBlogWrite']",
        "[href*='PostWriteForm']",
    ]

    for sel in write_btn_sels:
        try:
            el = page.locator(sel).first
            if not await el.count():
                continue

            href = await el.get_attribute("href") or ""
            logger.info(f"글쓰기 버튼 발견: {sel} | href={href!r}")

            pages_before = len(ctx.pages)

            try:
                async with ctx.expect_page(timeout=8000) as new_page_info:
                    await el.click()
                new_pg = await new_page_info.value
                await new_pg.wait_for_load_state("domcontentloaded", timeout=20000)
                await _delay(2000, 3000)
                await _screenshot(new_pg, "write_new_tab")
                logger.info(f"새 탭 열림: {new_pg.url}")
                try:
                    await new_pg.wait_for_selector(
                        "div[contenteditable='true'], .se-title-text, .se-main-container",
                        timeout=15000,
                    )
                    logger.info(f"새 탭 에디터 확인 완료: {new_pg.url}")
                    return new_pg
                except Exception:
                    logger.info(f"새 탭 에디터 요소 없음 — URL: {new_pg.url}")
                    if _is_editor_page(new_pg.url):
                        return new_pg
                    await new_pg.close()
            except Exception as e:
                logger.info(f"새 탭 없음 ({e.__class__.__name__}) — 현재 페이지 확인")

            await _delay(3000, 5000)
            cur = page.url
            logger.info(f"클릭 후 현재 URL: {cur}")
            await _screenshot(page, "after_click_write")

            if "Redirect=Write" in cur or _is_editor_page(cur):
                logger.info(f"에디터 리다이렉트 감지: {cur}")
                try:
                    await page.wait_for_selector(
                        "div[contenteditable='true'], .se-title-text, .se-main-container",
                        timeout=15000,
                    )
                    logger.info("현재 페이지에서 에디터 요소 확인")
                    return page
                except Exception:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await _delay(2000, 3000)
                    await _screenshot(page, "after_redirect_write")
                    ed_count = await page.locator("div[contenteditable='true'], .se-title-text").count()
                    if ed_count > 0:
                        logger.info(f"에디터 요소 {ed_count}개 확인")
                        return page

            break
        except Exception as e:
            logger.warning(f"글쓰기 버튼 시도 실패 ({sel}): {e}")

    # 방법 2: 구형 PostWriteForm 시도
    for bid in dict.fromkeys(filter(None, [blog_id, naver_id])):
        url = f"https://blog.naver.com/PostWriteForm.naver?blogId={bid}"
        logger.info(f"[레거시] PostWriteForm: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await _delay(2000, 3000)
            cur = page.url
            await _screenshot(page, f"legacy_{bid}")
            logger.info(f"레거시 결과: {cur}")
            ed_count = await page.locator("div[contenteditable='true'], .se-title-text").count()
            if ed_count > 0:
                logger.info(f"레거시 에디터 {ed_count}개 확인")
                return page
        except Exception as e:
            logger.warning(f"레거시 실패: {e}")

    logger.error("모든 방법으로 글쓰기 페이지 진입 실패")
    return None


async def _get_editor_frame(page: Page) -> Page:
    """에디터가 iframe 안에 있으면 해당 frame 반환"""
    await _delay(500, 800)
    for frame in page.frames:
        url = frame.url or ""
        if any(kw in url for kw in ["editor", "se.naver", "postwrite", "editForm"]):
            logger.info(f"에디터 frame (URL): {url}")
            return frame  # type: ignore
        try:
            count = await frame.locator("div[contenteditable='true']").count()
            if count > 0:
                logger.info(f"에디터 frame (contenteditable): {url}")
                return frame  # type: ignore
        except Exception:
            continue
    return page


async def _dismiss_draft_popup(page: Page):
    """'작성 중인 글이 있습니다' 팝업 → 취소 클릭"""
    targets = [page] + [f for f in page.frames if f.url != page.url]
    for t in targets:
        try:
            result = await t.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    const cancel = btns.find(b => b.textContent.trim() === '취소');
                    if (cancel) { cancel.click(); return '취소_clicked'; }
                    return null;
                }
            """)
            if result:
                await _delay(800, 1200)
                logger.info(f"임시저장 팝업 취소: {result}")
                return
        except Exception:
            continue


async def _close_help_panel(page: Page):
    """도움말 패널 닫기 — slick-arrow 제외하고 실제 × 버튼만 클릭"""
    targets = [page] + [f for f in page.frames if f.url != page.url]

    close_sels = [
        "button[aria-label*='닫기']",
        "button[aria-label*='닫']",
        "button[aria-label*='close' i]",
        ".se-help-panel-close",
        ".se-help-panel > button",
        "button.se-close-btn",
    ]
    for t in targets:
        for sel in close_sels:
            try:
                btn = t.locator(sel).first
                if await btn.count():
                    await btn.click()
                    await _delay(500, 800)
                    logger.info(f"도움말 패널 닫음 (CSS): {sel}")
                    return
            except Exception:
                continue

    for t in targets:
        try:
            result = await t.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    const closeBtn = btns.find(b => {
                        const cls = b.className || '';
                        if (cls.includes('slick')) return false;
                        const label = (b.getAttribute('aria-label') || '').toLowerCase();
                        const txt = b.textContent.trim();
                        return label.includes('닫') || label.includes('close') ||
                               txt === '×' || txt === '✕' || txt === 'X' ||
                               cls.toLowerCase().includes('close') ||
                               cls.toLowerCase().includes('dismiss');
                    });
                    if (closeBtn) {
                        closeBtn.click();
                        return closeBtn.className + '|' + closeBtn.textContent.trim().slice(0, 10);
                    }
                    return null;
                }
            """)
            if result:
                await _delay(500, 800)
                logger.info(f"도움말 패널 JS 닫기: {result}")
                return
        except Exception:
            continue


async def _fill_title(page: Page, title: str):
    """제목 입력 — 메인 페이지와 iframe 모두 탐색. 입력 후 Tab으로 본문 포커스 이동"""
    target = await _get_editor_frame(page)

    title_sels = [
        ".se-title-text",
        "[data-se-type='title']",
        ".se-section-title [contenteditable='true']",
        "div[contenteditable='true']",
        "input[name='title']",
        "[placeholder='제목']",
        "[data-placeholder='제목']",
    ]

    for search_target in [page, target]:
        for sel in title_sels:
            try:
                t = search_target.locator(sel).first
                if await t.count():
                    await t.click()
                    await _delay(300, 500)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(title, delay=20)
                    await _delay(200, 400)
                    await page.keyboard.press("Tab")
                    await _delay(300, 500)
                    logger.info(f"제목 입력 + Tab 완료 ({sel}): {title[:40]}")
                    return
            except Exception:
                continue

    logger.warning("제목 입력 영역을 찾지 못함")


async def _type_in_editor(page: Page, text: str):
    """
    본문 타이핑.
    _fill_title()이 Tab으로 본문 포커스를 이미 이동했으므로,
    .se-section-text 내부 요소만 클릭해 제목 재클릭을 방지한다.
    이미지 삽입 후에도 커서가 문서 끝에 위치하도록 Ctrl+End 사용.
    """
    target = await _get_editor_frame(page)

    # 먼저 Ctrl+End로 문서 끝으로 이동 (이미지 삽입 후 커서 위치 보정)
    try:
        await page.keyboard.press("Control+End")
        await _delay(150, 250)
    except Exception:
        pass

    body_sels = [
        ".se-section-text .se-text-paragraph",
        ".se-section-text [contenteditable='true']",
        ".se-main-container .se-text-paragraph:not(.se-title-text)",
        "div[contenteditable='true']:not([data-se-type='title'])",
        ".se-component-content",
        ".se-main-container",
        "[contenteditable='true']",
    ]
    clicked = False
    for sel in body_sels:
        try:
            # .last 로 가장 마지막 단락 클릭 (이미지 뒤 새 단락에 커서 위치)
            loc = target.locator(sel).last
            if await loc.count():
                await loc.click()
                clicked = True
                logger.info(f"에디터 본문 클릭: {sel}")
                # 클릭 후 End 키로 해당 단락 끝으로 커서 이동
                await page.keyboard.press("End")
                await _delay(100, 200)
                break
        except Exception:
            continue

    if not clicked:
        logger.info("본문 셀렉터 없음 — Tab 포커스 유지로 타이핑 진행")

    await _delay(400, 700)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        lines = para.split("\n")
        for j, line in enumerate(lines):
            raw_stripped = line.strip()
            # [구분선] 마커: 소제목 앞 구분선 삽입 후 다음 줄로
            if raw_stripped == "[구분선]":
                await _insert_divider(page)
                continue
            is_centered = raw_stripped.startswith("[가운데]")
            stripped_line = raw_stripped[len("[가운데]"):].strip() if is_centered else raw_stripped
            if stripped_line:
                char_delay = random.randint(12, 35)
                if is_centered:
                    await page.keyboard.press("Control+e")  # 가운데 정렬
                    await _delay(80, 150)
                # **bold** 파싱: **텍스트** → Ctrl+B 토글
                if "**" in stripped_line:
                    parts = re.split(r"(\*\*[^*]+\*\*)", stripped_line)
                    for part in parts:
                        if part.startswith("**") and part.endswith("**"):
                            inner = part[2:-2]
                            await page.keyboard.press("Control+b")
                            await page.keyboard.type(inner, delay=char_delay)
                            await page.keyboard.press("Control+b")
                        elif part:
                            await page.keyboard.type(part, delay=char_delay)
                else:
                    await page.keyboard.type(stripped_line, delay=char_delay)

                # URL 감지 시 네이버 에디터가 링크 카드로 렌더링하도록 3~4초간 대기
                if stripped_line.startswith("http://") or stripped_line.startswith("https://"):
                    logger.info(f"URL 감지 → 링크 카드 생성 대기: {stripped_line[:40]}...")
                    await page.keyboard.press("Enter")
                    await _delay(3500, 4500)
                    # 링크 카드 생성 후 남아있는 '생 URL 텍스트 단락'만 제거(카드는 유지).
                    # 카드(.se-oglink)는 도메인만 표시하므로, 전체 URL과 일치하는 텍스트 단락만 안전히 삭제.
                    try:
                        _tgt = await _get_editor_frame(page)
                        _url_p = _tgt.locator(
                            f".se-text-paragraph:has-text('{stripped_line}')"
                        ).first
                        if await _url_p.count():
                            await _url_p.click(click_count=3)   # 단락 전체 선택
                            await _delay(120, 220)
                            await page.keyboard.press("Delete")
                            await page.keyboard.press("Backspace")  # 남은 빈 줄 정리
                            await _delay(150, 300)
                            logger.info("생 URL 텍스트 단락 제거 완료 (링크 카드만 유지)")
                    except Exception as _e:
                        logger.info(f"생 URL 텍스트 제거 스킵: {_e.__class__.__name__}")
                    if is_centered:
                        await page.keyboard.press("Control+l")  # 왼쪽 정렬 복귀
                        await _delay(80, 150)
                elif j < len(lines) - 1:
                    await _delay(80, 250)
            if j < len(lines) - 1 and not (stripped_line.startswith("http://") or stripped_line.startswith("https://")):
                await page.keyboard.press("Enter")
                if is_centered:
                    await page.keyboard.press("Control+l")  # 왼쪽 정렬 복귀
                    await _delay(80, 150)
        if i < len(paragraphs) - 1:
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
            # 단락 사이 더 긴 자연스러운 멈춤
            await _delay(200, 600)


async def _apply_size_to_selection(page: Page, size_label: str = "19", dump: bool = False):
    """현재 선택 영역에 글자 크기 적용 (네이버 SE 내부 모델 반영 위해 툴바 드롭다운 사용)."""
    target = await _get_editor_frame(page)
    try:
        await target.locator("[data-name='font-size']").first.click(timeout=2000)
        await _delay(300, 550)
        if dump:
            try:
                opts = await target.evaluate(
                    r"""() => [...document.querySelectorAll('button,li,[role=option]')]
                        .filter(e=>e.offsetParent)
                        .map(e=>({txt:(e.textContent||'').trim().slice(0,8),
                                  cls:(e.className&&e.className.toString?e.className.toString():'').slice(0,45),
                                  dn:e.getAttribute('data-value')||e.getAttribute('data-name')}))
                        .filter(o=>/^\d{1,3}$/.test(o.txt) || /size|fs|font/i.test(o.cls))
                        .slice(0,30)"""
                )
                logger.info(f"[크기옵션] {opts}")
            except Exception:
                pass
        # 옵션 클릭: 정확히 size_label 인 옵션 (data-value 우선, 없으면 텍스트 일치)
        opt = target.locator(
            f"[data-value='{size_label}'], [data-name='{size_label}'], .se-toolbar-option-size-code-button[data-value='{size_label}']"
        ).first
        if not await opt.count():
            opt = target.get_by_text(re.compile(rf"^{size_label}$")).first
        await opt.click(timeout=1500)
        await _delay(200, 400)
    except Exception as e:
        logger.info(f"크기 적용 실패: {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass


async def _apply_font_all(page: Page, font_dn: str = "nanummaruburi") -> bool:
    """본문 전체 선택 후 글꼴 변경. 네이버 SE는 내부 문서모델을 직렬화하므로 DOM 직접수정
    대신 툴바 드롭다운을 써야 저장에 반영된다.
    핵심: 글꼴 옵션의 코드는 data-name이 아니라 data-value 에 있다(data-name은 전부 'font-family').
    또 보이는 툴바 버튼만 열리므로 :visible 로 한정한다. Ctrl+A 2회=문서 전체 선택."""
    target = await _get_editor_frame(page)
    try:
        await page.keyboard.press("Control+End")
        await _delay(150, 250)
        await page.keyboard.press("Control+a")
        await _delay(200, 300)
        await page.keyboard.press("Control+a")  # SE: 1회=현재블록, 2회=전체
        await _delay(300, 500)
        await target.locator("[data-name='font-family']:visible").first.click(timeout=3000)
        await _delay(450, 700)
        opt = target.locator(f".se-toolbar-option-text-button[data-value='{font_dn}']").first
        await opt.wait_for(state="visible", timeout=2500)
        await opt.click(timeout=2000)
        await _delay(300, 500)
        await page.keyboard.press("Control+End")
        logger.info(f"글꼴 전체 적용: {font_dn}")
        return True
    except Exception as e:
        logger.warning(f"글꼴 적용 실패(무시): {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def _style_paragraphs(
    page: Page,
    texts: list[str],
    size_label: str | None = "19",
    bold: bool = True,
    label: str = "스타일",
    style_type: str | None = None,
):
    """텍스트가 일치하는 본문 단락을 찾아 스타일(heading/quotation/quotation_vertical/글자크기/굵게) 적용."""
    items = [s.strip() for s in (texts or []) if s and s.strip()]
    if not items:
        return
    target = await _get_editor_frame(page)
    paras = target.locator(".se-section-text .se-text-paragraph")
    styled = 0
    dumped = False
    for tx in items:
        try:
            n = await paras.count()
        except Exception:
            n = 0
        idx = -1
        for i in range(n):
            try:
                t = (await paras.nth(i).inner_text()).strip()
            except Exception:
                continue
            if t == tx:
                idx = i
                break
        if idx < 0:
            logger.info(f"{label} 단락 못 찾음(스킵): {tx[:20]}")
            continue
        try:
            await paras.nth(idx).click(timeout=4000)
            await _delay(120, 220)
            await page.keyboard.press("Home")
            await page.keyboard.down("Shift")
            await page.keyboard.press("End")
            await page.keyboard.up("Shift")
            await _delay(150, 260)
            
            ok_styled = False
            if style_type == "heading":
                ok_styled = await _apply_paragraph_style(page, "제목 2")
            elif style_type in ["quotation", "quotation_vertical"]:
                await page.keyboard.press("Backspace")
                await _delay(150, 250)
                q_type = "버티컬 라인" if style_type == "quotation_vertical" else ""
                ok_styled = await _apply_quotation(page, quote_type=q_type)
                if ok_styled:
                    await page.keyboard.type(tx, delay=random.randint(10, 20))
                    await _delay(300, 500)
                    await page.keyboard.press("Escape")
                    await _delay(150, 250)
                
            if not ok_styled:
                if size_label:
                    await _apply_size_to_selection(page, size_label, dump=not dumped)
                    dumped = True
                if bold:
                    await page.keyboard.press("Control+b")
            await _delay(150, 250)
            styled += 1
        except Exception as e:
            logger.info(f"{label} 적용 실패(스킵): {e}")
    try:
        await page.keyboard.press("Control+End")
    except Exception:
        pass
    logger.info(f"{label} 적용 {styled}/{len(items)}개 (크기 {size_label}, 굵게 {bold}, 타입 {style_type})")


def _preceding_text_at(body: str, pos: int) -> str:
    """body의 pos 위치 바로 이전 비어있지 않은 단락/라인 텍스트를 반환(마커 제거)."""
    preceding_part = re.sub(r"\[사진\d+\]|\[표삽입\]|\[FAQ삽입\]|\[요약삽입\]|\[구분선\]", "", body[:pos])
    lines = [ln.strip() for ln in preceding_part.split("\n") if ln.strip()]
    return lines[-1] if lines else ""


def _get_preceding_text(body: str, marker_str: str) -> str:
    """
    body에서 marker_str 바로 이전에 나타나는 비어있지 않은 단락/라인 텍스트를 찾아 반환합니다.
    """
    pos = body.find(marker_str)
    if pos == -1:
        return ""
    return _preceding_text_at(body, pos)


def _compute_image_text_anchors(body: str) -> list[tuple[str, int]]:
    """
    [사진N] 마커의 바로 전 단락 텍스트와 이미지 인덱스(0-based)를 매핑해 반환합니다.
    반환: [(anchor_text, image_index_0based), ...]
    """
    marker = re.compile(r"\[사진(\d+)\]")
    anchors: list[tuple[str, int]] = []
    for m in marker.finditer(body):
        img_idx = int(m.group(1)) - 1
        anchor_text = _get_preceding_text(body, m.group(0))
        anchors.append((anchor_text, img_idx))
    return anchors


def _wrap_korean_text(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """한글 텍스트를 글자 단위로 측정하여 지정된 너비 이내로 줄바꿈 처리합니다."""
    lines = []
    current_line = ""
    for char in text:
        test_line = current_line + char
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            w = bbox[2] - bbox[0]
        except AttributeError:
            w, _ = draw.textsize(test_line, font=font)
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
    if current_line:
        lines.append(current_line)
    return lines


def _parse_table_rows(table_str: str) -> list[list[str]]:
    """파이프 구분 표 문자열 → 셀 2차원 리스트 (구분선 행 제거)."""
    rows: list[list[str]] = []
    for r in table_str.strip().split("\n"):
        r = r.strip()
        if not r or re.match(r"^[\s|—\-]+$", r):  # 구분선/빈 행 제외
            continue
        cells = [c.strip() for c in r.split("|")]
        # 양 끝 빈 셀 제거
        while cells and cells[0] == "":
            cells.pop(0)
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            rows.append(cells)
    return rows


async def _move_cursor_after_text(page: Page, anchor_text: str) -> bool:
    """
    에디터 본문에서 anchor_text와 일치하거나 포함하는 단락을 찾아 그 끝으로 커서를 이동합니다.
    anchor_text가 비어있으면 문서 맨 끝으로 이동합니다.
    """
    if not anchor_text:
        try:
            await page.keyboard.press("Control+End")
            await _delay(150, 300)
            return True
        except Exception:
            return False

    target = await _get_editor_frame(page)
    try:
        clean_anchor = anchor_text.strip()

        # 1차: 일반 텍스트 단락 검색
        # 2차: quotation 블록 포함 확장 검색 (소제목이 스타일 적용 후 quotation 블록이 되는 경우 대비)
        SELECTORS = [
            ".se-section-text .se-text-paragraph",
            ".se-text-paragraph",
            "[class*='se-quotation'] .se-text-paragraph",
            "[class*='se-quotation-content']",
            "[class*='se-paragraph']",
        ]

        best_loc = None
        for sel in SELECTORS:
            paras = target.locator(sel)
            cnt = await paras.count()
            if cnt == 0:
                continue
            for i in range(cnt):
                try:
                    p_text = (await paras.nth(i).inner_text()).strip()
                    if not p_text:
                        continue
                    if p_text == clean_anchor:
                        best_loc = paras.nth(i)
                        break
                    if clean_anchor in p_text or p_text in clean_anchor:
                        best_loc = paras.nth(i)
                except Exception:
                    continue
            if best_loc:
                break

        # 3차 폴백: Playwright get_by_text (CSS 클래스 무관 전체 텍스트 검색)
        if best_loc is None and len(clean_anchor) >= 4:
            try:
                loc = target.get_by_text(clean_anchor, exact=False).first
                if await loc.count():
                    best_loc = loc
                    logger.info(f"get_by_text 폴백 매칭: {clean_anchor[:30]}")
            except Exception:
                pass

        if best_loc is not None:
            logger.info(f"앵커 단락 발견: {clean_anchor[:40]}")
            clicked = False
            try:
                box = await best_loc.bounding_box()
                if box and box["width"] > 6 and box["height"] > 6:
                    await best_loc.click(position={"x": box["width"] - 3, "y": box["height"] - 3})
                    clicked = True
            except Exception as e:
                logger.warning(f"단락 박스 클릭 실패: {e}")
            if not clicked:
                await best_loc.click()
            await page.keyboard.press("End")
            await _delay(200, 400)
            return True

        logger.warning(f"앵커 텍스트 매칭 단락을 찾지 못함: {clean_anchor[:40]}")
        await page.keyboard.press("Control+End")
        await _delay(150, 300)
        return False
    except Exception as e:
        logger.warning(f"텍스트 기반 커서 이동 중 예외 발생: {e}")
        try:
            await page.keyboard.press("Control+End")
        except Exception:
            pass
        return False


def _load_card_font(size: int):
    """카드뉴스용 한글 폰트 로드 (Windows 로컬 + Linux 러너 fonts-nanum)."""
    font_paths = [
        "C:\\Windows\\Fonts\\malgunbd.ttf",
        "C:\\Windows\\Fonts\\malgun.ttf",
        "C:\\Windows\\Fonts\\NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    logger.warning(
        "카드뉴스 한글 폰트를 찾지 못함 — load_default()로 폴백(한글 □ 깨짐 위험). "
        "러너에 fonts-nanum 설치 또는 폰트 번들 필요."
    )
    return ImageFont.load_default()


def _parse_card_content(content: str) -> tuple[str, list[str]]:
    """카드 라벨 파싱. '제목 :: 요점1 · 요점2 · 요점3' 형태를 (제목, [요점...])로 분해.
    '::' 없으면 전체를 제목으로, 요점 없음. (구버전 라벨 호환)"""
    content = (content or "").strip()
    if "::" in content:
        title, rest = content.split("::", 1)
        title = title.strip()
        # 요점 구분자: 가운뎃점(·), 슬래시(/), 세미콜론(;)
        points = [p.strip() for p in re.split(r"[·/;]", rest) if p.strip()]
    else:
        title, points = content, []
    return title, points


def _create_card_news(content: str) -> str | None:
    """소주제 요약 카드뉴스 생성: 상단 제목(핵심 결론) + 하단 요약 요점(2~3줄).
    content 형식: '제목 :: 요점1 · 요점2 · 요점3' (요점 없으면 제목만 크게).
    한눈에 보는 정보 시각화가 목적 — 큰 글자만 박지 않는다."""
    try:
        width, height = 800, 800
        bg = (250, 248, 245, 255)
        accent = (210, 122, 90, 255)      # 테라코타 포인트
        title_col = (40, 38, 36, 255)
        point_col = (74, 70, 66, 255)
        img = Image.new("RGBA", (width, height), bg)
        draw = ImageDraw.Draw(img)

        margin = 40
        draw.rounded_rectangle(
            [(margin, margin), (width - margin, height - margin)],
            radius=24, outline=(228, 222, 214, 255), width=4,
        )

        title, points = _parse_card_content(content)

        def text_size(s, font):
            try:
                b = draw.textbbox((0, 0), s, font=font)
                return b[2] - b[0], b[3] - b[1]
            except AttributeError:
                return draw.textsize(s, font=font)

        # 상단 브랜드
        brand_text = "현지언니의 살림 가이드"
        brand_font = _load_card_font(24)
        bw, _ = text_size(brand_text, brand_font)
        draw.text(((width - bw) // 2, 88), brand_text, font=brand_font, fill=(150, 128, 108, 255))

        max_w = width - 150

        # 제목 (핵심 결론) — 요점이 있으면 위쪽, 없으면 중앙 크게
        title_size = 52 if points else 60
        title_font = _load_card_font(title_size)
        t_lines = _wrap_korean_text(title, draw, title_font, max_w)
        if len(t_lines) > 2:
            title_size = 42
            title_font = _load_card_font(title_size)
            t_lines = _wrap_korean_text(title, draw, title_font, max_w)

        # 요점 폰트/줄
        point_font = _load_card_font(30)
        wrapped_points: list[str] = []
        for p in points[:3]:
            for wl in _wrap_korean_text("• " + p, draw, point_font, max_w):
                wrapped_points.append(wl)

        # 세로 중앙 정렬 계산
        t_lh = title_size + 16
        p_lh = 46
        block_h = len(t_lines) * t_lh + (28 + len(wrapped_points) * p_lh if wrapped_points else 0)
        y = (height - block_h) // 2 + 10

        # 제목 그리기 (가운데)
        for ln in t_lines:
            lw, _ = text_size(ln, title_font)
            draw.text(((width - lw) // 2, y), ln, font=title_font, fill=title_col)
            y += t_lh

        # 제목-요점 사이 포인트 바
        if wrapped_points:
            bar_w = 70
            draw.line([((width - bar_w) // 2, y + 6), ((width + bar_w) // 2, y + 6)],
                      fill=accent, width=4)
            y += 28
            # 요점 (좌측 정렬, 블록을 가운데로)
            left_x = 130
            for ln in wrapped_points:
                draw.text((left_x, y), ln, font=point_font, fill=point_col)
                y += p_lh

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        img.save(tmp.name, "PNG")
        logger.info(f"카드뉴스 생성: 제목='{title}' 요점{len(points)}개 -> {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.warning(f"카드뉴스 자체 생성 중 예외 발생: {e}")
        return None


def create_health_header_card(title: str, keyword: str = "", category: str = "health") -> str | None:
    """다크 브랜드 헤더 카드 이미지 생성.
    category='health': 현지언니 HEALTH (청록), category='gov': 현지언니 정부혜택 (금색).
    다크 네이비 배경, 상단 현지언니 브랜딩, 중앙 대형 토픽 텍스트."""
    try:
        width, height = 800, 450
        bg = (22, 32, 48)          # 다크 네이비
        accent = (52, 183, 163) if category == "health" else (212, 175, 55)  # 청록 or 금색
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # 상단/하단 액센트 라인
        draw.rectangle([(0, 0), (width, 7)], fill=accent)
        draw.rectangle([(0, height - 7), (width, height)], fill=accent)

        # 브랜드 텍스트
        brand_font = _load_card_font(26)
        brand_text = "현지언니  H E A L T H" if category == "health" else "현지언니  정부혜택  가이드"
        try:
            bw = draw.textbbox((0, 0), brand_text, font=brand_font)[2]
        except AttributeError:
            bw, _ = draw.textsize(brand_text, font=brand_font)
        draw.text(((width - bw) // 2, 52), brand_text, font=brand_font, fill=accent)

        # 구분선
        draw.line([(width // 2 - 80, 100), (width // 2 + 80, 100)], fill=(70, 90, 115), width=1)

        # 토픽 텍스트: 제목의 | 앞부분 사용, 없으면 keyword
        topic = title.split("|")[0].strip() if title and "|" in title else title.strip()
        display = topic if topic else keyword
        if len(display) > 20:
            display = display[:20]

        title_font = _load_card_font(58)
        t_lines = _wrap_korean_text(display, draw, title_font, width - 120)
        if len(t_lines) > 2:
            title_font = _load_card_font(46)
            t_lines = _wrap_korean_text(display, draw, title_font, width - 120)

        lh = int(title_font.size * 1.3) if hasattr(title_font, "size") else 70
        total_h = len(t_lines) * lh
        y = (height - total_h) // 2 + 15

        for line in t_lines:
            try:
                lw = draw.textbbox((0, 0), line, font=title_font)[2]
            except AttributeError:
                lw, _ = draw.textsize(line, font=title_font)
            draw.text(((width - lw) // 2, y), line, font=title_font, fill=(255, 255, 255))
            y += lh

        # 하단 서브텍스트
        sub_font = _load_card_font(22)
        sub_text = "건강 정보 총정리" if category == "health" else "정부지원 혜택 총정리"
        try:
            sw = draw.textbbox((0, 0), sub_text, font=sub_font)[2]
        except AttributeError:
            sw, _ = draw.textsize(sub_text, font=sub_font)
        draw.text(((width - sw) // 2, height - 50), sub_text, font=sub_font, fill=(140, 160, 185))

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.close()
        img.save(tmp.name, "PNG")
        logger.info(f"헬스 헤더 카드 생성: {display!r} → {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.warning(f"헬스 헤더 카드 생성 실패: {e}")
        return None


def _download_image_to_temp(url: str, label: str = None) -> str | None:
    """Pexels URL 다운로드 우선 → 실패 시 label로 카드뉴스 폴백."""
    # 1. Pexels 이미지 URL 다운로드 우선
    if url:
        try:
            import ssl
            context = ssl._create_unverified_context()
            suffix = ".jpg" if "jpg" in url.lower() else ".png"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=context, timeout=15) as resp:
                tmp.write(resp.read())
            tmp.close()
            logger.info(f"Pexels 이미지 다운로드 완료: {tmp.name}")
            return tmp.name
        except Exception as e:
            logger.warning(f"Pexels 이미지 다운로드 실패 (카드뉴스 폴백): {e}")

    # 2. 폴백: label이 있으면 카드뉴스 자체 생성
    if label:
        logger.info(f"카드뉴스 폴백 생성: '{label}'")
        return _create_card_news(label)

    return None


async def _caret_in_table(page: Page) -> bool:
    """현재 캐럿(선택)이 표 셀 안에 있는지. 이미지가 표 안에 삽입되는 것을 막기 위함."""
    target = await _get_editor_frame(page)
    try:
        return await target.evaluate("""() => {
            const sel = document.getSelection();
            if (!sel || !sel.anchorNode) return false;
            const node = sel.anchorNode;
            const el = node.nodeType === 1 ? node : node.parentElement;
            return !!(el && el.closest('.se-section-table, .se-table, table'));
        }""")
    except Exception:
        return False


async def _count_editor_images(target) -> int:
    """에디터 본문에 실제 삽입된 이미지 컴포넌트 수."""
    try:
        return await target.evaluate(
            "() => document.querySelectorAll('.se-section-image, .se-image-resource, .se-module-image').length"
        )
    except Exception:
        return 0


async def _editor_text_length(page: Page) -> int:
    """에디터 본문(제목 제외)에 실제 입력된 텍스트 길이. 발행 전 본문 소실 검증용."""
    target = await _get_editor_frame(page)
    try:
        return await target.evaluate("""
            () => {
                const root = document.querySelector('.se-main-container') || document.body;
                let total = 0;
                root.querySelectorAll('.se-text-paragraph, .se-component-content .se-text').forEach(p => {
                    // 제목 영역 제외
                    if (p.closest('.se-section-title')) return;
                    total += (p.textContent || '').trim().length;
                });
                return total;
            }
        """)
    except Exception:
        return 0


async def _click_photo_button(page: Page) -> bool:
    """SE ONE 툴바 사진 버튼 Playwright 실제 클릭. 성공 시 True."""
    target = await _get_editor_frame(page)
    # Playwright 실제 클릭 (JS click보다 다이얼로그 트리거 신뢰성 높음)
    selectors = [
        ".se-toolbar-item-image",
        "button[data-name='image']",
        ".se-toolbar button:has-text('사진')",
        "[title='사진']",
        "[aria-label='사진']",
        "[aria-label*='image' i]",
        ".se-toolbar-item:has-text('사진')",
    ]
    for t in [target, page]:
        for sel in selectors:
            try:
                loc = t.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                    await loc.click(timeout=3000)
                    logger.info(f"사진 버튼 Playwright 클릭: {sel}")
                    return True
            except Exception:
                continue
    # fallback: JS 클릭
    for t in [target, page]:
        try:
            result = await t.evaluate("""
                () => {
                    const candidates = [
                        ...document.querySelectorAll('.se-toolbar-item, button')
                    ];
                    const btn = candidates.find(b => {
                        const txt = (b.textContent || '').trim();
                        const cls = b.className || '';
                        return txt === '사진' || cls.includes('image') || cls.includes('photo');
                    });
                    if (btn) { btn.dispatchEvent(new MouseEvent('click', {bubbles:true})); return btn.className; }
                    return null;
                }
            """)
            if result:
                logger.info(f"사진 버튼 JS fallback 클릭: {result}")
                return True
        except Exception:
            continue
    return False


async def _insert_divider(page: Page) -> bool:
    """SE ONE 에디터에 구분선(가로줄) 삽입. 툴바 버튼 → 텍스트 폴백 순으로 시도."""
    target = await _get_editor_frame(page)
    try:
        # SE ONE 툴바의 구분선 버튼 — 에디터 버전마다 셀렉터가 다를 수 있으므로 다중 시도
        for sel in [
            "button[data-name='horizontalLine']",
            "button[data-name='line']",
            "button[title='구분선']",
            "button[aria-label='구분선']",
            ".se-toolbar-item-horizontalLine button",
            "[data-log-actionid='divider']",
        ]:
            try:
                btn = target.locator(sel).first
                if await btn.count() and await btn.is_visible(timeout=600):
                    await btn.click(timeout=1500)
                    await _delay(300, 500)
                    logger.info(f"구분선 삽입(툴바): {sel}")
                    return True
            except Exception:
                continue

        # 폴백: box-drawing character로 시각적 구분선 삽입
        await page.keyboard.type("─" * 28, delay=5)
        await page.keyboard.press("Enter")
        await _delay(100, 200)
        logger.info("구분선 삽입(텍스트 폴백)")
        return True
    except Exception as e:
        logger.warning(f"구분선 삽입 실패: {e}")
        return False


async def _fill_image_caption(page: Page, alt_text: str) -> bool:
    """방금 삽입된 이미지(가장 마지막 이미지)의 캡션 입력창을 찾아 alt_text 타이핑"""
    if not alt_text:
        return False
    target = await _get_editor_frame(page)
    try:
        # 스마트에디터 ONE의 이미지 캡션 영역 셀렉터들
        caption_sels = [
            ".se-component-image .se-image-caption",
            ".se-image-caption",
            "[placeholder*='사진 설명을']",
            "[data-placeholder*='사진 설명을']",
        ]
        caption_loc = None
        for sel in caption_sels:
            loc = target.locator(sel).last
            if await loc.count() and await loc.is_visible(timeout=1500):
                caption_loc = loc
                break
                
        if caption_loc:
            await caption_loc.click(timeout=2000)
            await _delay(200, 450)
            # 기존 텍스트 제거
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            await _delay(100, 200)
            # 타이핑
            await page.keyboard.type(alt_text, delay=random.randint(15, 30))
            await _delay(300, 500)
            # 포커스 해제
            await page.keyboard.press("Escape")
            await page.keyboard.press("Control+End")
            logger.info(f"이미지 캡션(Alt) 입력 성공: '{alt_text}'")
            return True
            
        logger.warning("이미지 캡션 입력 영역을 찾지 못함")
    except Exception as e:
        logger.warning(f"이미지 캡션 입력 예외(무시): {e}")
    return False


async def _insert_image_file(page: Page, local_path: str, alt_text: str = "") -> bool:
    """
    SE ONE 에디터에 이미지 삽입 (3단계 Fallback).

    방법1: expect_file_chooser 인터셉터 + 사진 버튼 클릭 → 다이얼로그 '내 PC에서' 클릭
           (파일 선택창이 15초 내에 뜨면 성공)
    방법2: 모든 프레임 input[type='file'] 직접 set_input_files
    방법3: DataTransfer dragdrop 이벤트로 이미지 주입
    """
    def _all_frames():
        return [page] + [f for f in page.frames if f is not page]

    try:
        target = await _get_editor_frame(page)
        before = await _count_editor_images(target)

        # ── 방법 1: 사진 버튼 → '파일 불러오기' 팝업 → '내 컴퓨터' 클릭을 file_chooser 로 감쌈 ──
        # ★핵심: expect_file_chooser 윈도우는 '내 컴퓨터' 클릭 '직전'에 열어야 한다.
        #   팝업 띄우기/버튼탐색까지 윈도우 안에서 하면 12초가 소진돼 클릭 직후 타임아웃 났었음.
        try:
            # 1a. 에디터 포커스 + 사진 버튼 클릭 (팝업 열기) — file_chooser 윈도우 '밖'에서
            try:
                ed = target.locator("[contenteditable='true']").first
                if await ed.count():
                    await ed.click()
                    await _delay(200, 400)
            except Exception:
                pass
            if not await _click_photo_button(page):
                raise RuntimeError("사진 버튼 없음")

            # 1b. '내 컴퓨터' 버튼이 뜰 때까지 폴링 (최대 ~8초, 모든 프레임)
            pc_btn = None
            pc_sels = (
                "text=내 컴퓨터", "text=내컴퓨터", "button:has-text('내 컴퓨터')",
                "[class*='file-source']", "text=내 PC에서",
            )
            for _ in range(16):
                for fr in _all_frames():
                    for sel in pc_sels:
                        try:
                            loc = fr.locator(sel).first
                            if await loc.count() and await loc.is_visible(timeout=300):
                                pc_btn = loc
                                break
                        except Exception:
                            continue
                    if pc_btn:
                        break
                if pc_btn:
                    break
                await asyncio.sleep(0.5)

            await _screenshot(page, "after_photo_btn", full_page=True)

            # 1c. file_chooser 윈도우로 '내 컴퓨터' 클릭'만' 감싸기 (올바른 타이밍)
            if pc_btn is not None:
                logger.info("'내 컴퓨터' 클릭 → 파일창 대기")
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await pc_btn.click(timeout=3000)
                fc = await fc_info.value
            else:
                # 팝업 없이 사진 버튼이 곧장 파일창을 여는 변형 대비
                logger.info("'내 컴퓨터' 못 찾음 — 사진 버튼 직접 파일창 트리거 재시도")
                async with page.expect_file_chooser(timeout=8000) as fc_info:
                    await _click_photo_button(page)
                fc = await fc_info.value

            await fc.set_files(local_path)
            await asyncio.sleep(3)

            # 확인 버튼 (있는 경우)
            for ok_sel in ["text=확인", "text=삽입", "text=적용", "text=올리기", "text=등록"]:
                try:
                    ok = page.locator(ok_sel).first
                    if await ok.count() and await ok.is_visible(timeout=2000):
                        await ok.click()
                        await asyncio.sleep(1.5)
                        break
                except Exception:
                    continue

            after1 = await _count_editor_images(target)
            await _screenshot(page, f"img_ok_{alt_text[:8] if alt_text else 'img'}")
            if after1 > before:
                logger.info(f"이미지 삽입 성공 (방법1 file_chooser) — 이미지 {before}→{after1}")
                await _fill_image_caption(page, alt_text)
                return True
            logger.warning(f"방법1 후 이미지 수 변화 없음 ({before}→{after1}) — 방법2 시도")

        except Exception as e:
            logger.warning(f"방법1 실패 ({e.__class__.__name__}: {str(e)[:60]}) — 방법2 시도")
            # 방법1이 사진 업로드 팝업을 열었을 수 있으므로 Escape로 닫기
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # ── 방법 2: 모든 프레임 file input 직접 설정 ───────────────
        for frame in _all_frames():
            try:
                inputs = frame.locator("input[type='file']")
                cnt = await inputs.count()
                for j in range(cnt):
                    try:
                        await inputs.nth(j).set_input_files(local_path)
                        await asyncio.sleep(3)
                        after2 = await _count_editor_images(target)
                        if after2 > before:
                            logger.info(f"이미지 삽입 성공 (방법2 file input) — 이미지 {before}→{after2}")
                            await _fill_image_caption(page, alt_text)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

        # ── 모든 방법 실패: 본문 포커스를 깨지 않도록 정리만 하고 실패 반환 ──
        # (예전 DataTransfer 합성 drop 방식은 거짓 성공 + 포커스 파괴로 본문 소실을 유발해 제거)
        after = await _count_editor_images(target)
        logger.warning(f"이미지 삽입 실패 (이미지 수 {before}→{after} 변화 없음) — 건너뜀, 본문은 유지")
        await _screenshot(page, "image_all_failed", full_page=True)
        return False

    except Exception as e:
        logger.warning(f"이미지 삽입 예외 (계속 진행): {e}")
        return False
    finally:
        # '파일 불러오기' 업로드 다이얼로그가 남아있으면 X로 닫기 (Escape로는 안 닫힘 — 다음 이미지 시도 방해 방지)
        try:
            target = await _get_editor_frame(page)
            for fr in [target, page]:
                try:
                    await fr.evaluate("""
                        () => {
                            const btns = [...document.querySelectorAll('button, a, [role=button]')];
                            const x = btns.find(b => {
                                const t = (b.textContent || '').trim();
                                const a = (b.getAttribute('aria-label') || '').toLowerCase();
                                return t === '×' || t === '✕' || a.includes('닫기') || a.includes('close');
                            });
                            if (x) x.click();
                        }
                    """)
                except Exception:
                    pass
        except Exception:
            pass
        # 어떤 경로로 종료되어도 사진 팝업이 남아있지 않도록 Escape
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass
        try:
            if local_path and os.path.exists(local_path):
                os.unlink(local_path)
        except Exception:
            pass


async def _add_tags(page: Page, tags: list[str]):
    target = await _get_editor_frame(page)
    tag_sels = [
        ".tag_input input",
        ".se-tag input",
        "[placeholder*='태그']",
        "input[class*='tag']",
        ".HashTagArea input",
    ]
    for sel in tag_sels:
        try:
            tag_box = target.locator(sel).first
            if await tag_box.count():
                for tag in tags[:10]:
                    await tag_box.click()
                    await _delay(200, 400)
                    await tag_box.fill(tag)
                    await page.keyboard.press("Enter")
                    await _delay(300, 500)
                logger.info(f"태그 {len(tags)}개 입력 완료")
                return
        except Exception:
            continue
    logger.warning("태그 입력 영역 없음 — 태그 생략")


async def _delete_table_last_col(page: Page, cur_grid_cols: int) -> bool:
    """현재(마지막) 표의 마지막 열을 SE ONE 컨텍스트 메뉴로 삭제.
    JS로 직접 셀에 이벤트를 발생시켜 에디터 포커스 문제를 우회. 성공 시 True."""
    target = await _get_editor_frame(page)
    try:
        # ① JS로 마지막 표의 마지막 열 첫 셀에 포커스·click 이벤트 발생 (nth() 타임아웃 우회)
        await target.evaluate("""() => {
            const tables = document.querySelectorAll('.se-section-table table, .se-table table, table');
            if (!tables.length) return;
            const t = tables[tables.length - 1];
            const firstRow = t.querySelector('tr');
            if (!firstRow) return;
            const cells = [...firstRow.querySelectorAll('td, th')];
            const lastCell = cells[cells.length - 1];
            if (!lastCell) return;
            const editable = lastCell.querySelector('[contenteditable]') || lastCell;
            editable.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            editable.dispatchEvent(new MouseEvent('mouseup',   {bubbles: true}));
            editable.dispatchEvent(new MouseEvent('click',     {bubbles: true}));
            if (editable.focus) editable.focus();
        }""")
        await _delay(300, 500)

        # ② 컨트롤바 / data-name 버튼 시도
        del_sels = [
            ".se-cell-controlbar-column .se-cell-delete-button",
            "[data-name='deleteCol']", "[data-name='delete-column']", "[data-name='columnDelete']",
            "button[aria-label*='열 삭제']", "button[aria-label*='열삭제']",
        ]
        for sel in del_sels:
            for fr in [target, page]:
                try:
                    btn = fr.locator(sel).first
                    if await btn.count() and await btn.is_visible(timeout=400):
                        await btn.click(timeout=1500)
                        await _delay(400, 600)
                        logger.info(f"열 삭제 성공(셀렉터): {sel}")
                        return True
                except Exception:
                    continue

        # ③ JS로 마지막 열 셀에 contextmenu 이벤트 발생
        await target.evaluate("""() => {
            const tables = document.querySelectorAll('.se-section-table table, .se-table table, table');
            if (!tables.length) return;
            const t = tables[tables.length - 1];
            const firstRow = t.querySelector('tr');
            if (!firstRow) return;
            const cells = [...firstRow.querySelectorAll('td, th')];
            const lastCell = cells[cells.length - 1];
            if (!lastCell) return;
            const r = lastCell.getBoundingClientRect();
            lastCell.dispatchEvent(new MouseEvent('contextmenu', {
                bubbles: true, cancelable: true,
                clientX: r.left + r.width / 2, clientY: r.top + r.height / 2
            }));
        }""")
        await _delay(700, 1000)

        # ④ 컨텍스트 메뉴에서 "열 삭제" 텍스트 버튼 탐색
        for fr in [target, page]:
            try:
                items = fr.locator("button, [role='menuitem'], .se-popup-item, .se-context-menu-item")
                cnt = await items.count()
                for i in range(cnt):
                    try:
                        item = items.nth(i)
                        if not await item.is_visible(timeout=200):
                            continue
                        txt = (await item.inner_text()).strip()
                        if '열 삭제' in txt:
                            await item.click(timeout=2000)
                            await _delay(400, 600)
                            logger.info(f"열 삭제 성공(컨텍스트): {txt}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

        # ⑤ 실패 디버그 덤프
        try:
            visible = await target.evaluate("""() =>
                [...document.querySelectorAll('button,[role=menuitem]')]
                  .filter(b => b.offsetParent && (b.textContent||'').trim())
                  .map(b => ({txt:(b.textContent||'').trim().slice(0,25), dn:b.getAttribute('data-name'), cls:(b.className||'').slice(0,40)}))
                  .slice(0,20)
            """)
            logger.info(f"[열삭제 실패 가시버튼] {visible}")
        except Exception:
            pass
        await page.keyboard.press("Escape")
        return False
    except Exception as e:
        logger.warning(f"열 삭제 예외: {e}")
        return False


async def _insert_table(page: Page, table_str: str, anchor_text: str) -> bool:
    """table_str(파이프 구분 행) → 네이버 SE 진짜 표 삽입. best-effort + 디버그 DOM 로그."""
    rows = _parse_table_rows(table_str)
    if not rows:
        return False
    n_rows = len(rows)
    n_cols = max(len(r) for r in rows)
    logger.info(f"표 삽입 시도: {n_rows}행 x {n_cols}열 (앵커: {anchor_text[:30]})")
    target = await _get_editor_frame(page)
    cell_sel = ".se-cell [contenteditable], .se-table-cell [contenteditable], table td, table th"
    # 삽입 전 셀 수 기록 — 다중 표 삽입 시 이전 표 셀을 건드리지 않도록 오프셋으로 사용
    try:
        pre_insert_cells = await target.locator(cell_sel).count()
    except Exception:
        pre_insert_cells = 0

    await _move_cursor_after_text(page, anchor_text)
    await _delay(300, 500)

    # ── 표 버튼 클릭 ──
    clicked = False
    for sel in [".se-table-toolbar-button", "[data-name='table']", "button[data-name='table']",
                ".se-toolbar-item-table", "button[data-log='ttb.table']", "[aria-label='표']",
                "[title='표']", ".se-toolbar button:has-text('표')"]:
        try:
            for fr in [target, page]:
                loc = fr.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=2500):
                    await loc.click(timeout=3000)
                    clicked = True
                    logger.info(f"표 버튼 클릭: {sel}")
                    break
            if clicked:
                break
        except Exception:
            continue
    if not clicked:
        logger.warning("표 버튼 못 찾음 — 후보 DOM 덤프")
        for fr in [target, page]:
            try:
                btns = await fr.evaluate("""() =>
                    [...document.querySelectorAll('button,[role=button]')]
                      .filter(b => /표|table/i.test((b.textContent||'')+(b.className||'')+(b.getAttribute('aria-label')||'')+(b.getAttribute('data-name')||'')))
                      .map(b => ({txt:(b.textContent||'').trim().slice(0,12), cls:(b.className||'').slice(0,45), al:b.getAttribute('aria-label'), dn:b.getAttribute('data-name')}))
                      .slice(0,10)
                """)
                if btns:
                    logger.info(f"[표버튼후보 {fr.url[:35]}] {btns}")
            except Exception:
                pass
        return False

    await asyncio.sleep(1.8)
    await _screenshot(page, "after_table_btn", full_page=True)

    # 네이버 SE ONE은 표 버튼 클릭 즉시 기본 3x3 표를 삽입한다(크기 선택 그리드 없음).
    # 따라서 부족한 행은 아래에서 좌측 행 컨트롤바의 add-button으로 채운다.
    await asyncio.sleep(1.5)
    try:
        tcount = await target.evaluate("() => document.querySelectorAll('.se-section-table, .se-table, table').length")
    except Exception:
        tcount = 0
    logger.info(f"표 삽입 후 테이블 수: {tcount}")
    await _screenshot(page, "after_table_insert", full_page=True)
    if tcount < 1:
        logger.warning("표 삽입 실패 — 표 컴포넌트 없음")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    # ── 실제 삽입된 표의 '열 수' 감지 ──
    # 네이버 SE는 표 버튼 클릭 시 항상 기본 3열 표를 삽입한다(데이터 열 수와 무관).
    # 따라서 셀 채우기·행 수 계산은 데이터의 n_cols 가 아니라 '실제 표의 열 수'에 맞춰야
    # 줄밀림이 안 생긴다(2열 데이터를 3열 표에 순차로 부으면 전부 어긋남).
    try:
        grid_cols = await target.evaluate("""() => {
            const tables = document.querySelectorAll('.se-section-table table, .se-table table, table');
            if (!tables.length) return 0;
            const t = tables[tables.length - 1];
            const row = t.querySelector('tr');
            return row ? row.children.length : 0;
        }""")
    except Exception:
        grid_cols = 0
    if not grid_cols or grid_cols < 1:
        grid_cols = n_cols if n_cols >= 1 else 3
    if grid_cols != n_cols:
        logger.info(f"표 실제 열 수={grid_cols} (데이터 열 수={n_cols}) — 실제 열 수에 맞춰 채움")

    # ── 표 편집 툴바 덤프 (디버그 — 행 추가 버튼 찾기) ──
    for fr in [target, page]:
        try:
            tbtns = await fr.evaluate("""() =>
                [...document.querySelectorAll('button,[role=button]')]
                  .filter(b => /행|열|추가|아래|row|col|insert/i.test((b.getAttribute('aria-label')||'')+(b.getAttribute('data-name')||'')+(b.className||'')))
                  .map(b => ({al:b.getAttribute('aria-label'), dn:b.getAttribute('data-name'), cls:(b.className||'').slice(0,45)})).slice(0,14)
            """)
            if tbtns:
                logger.info(f"[표툴바 {fr.url[:30]}] {tbtns}")
        except Exception:
            pass

    # ── 현재 행 수 확인 후 부족하면 행 추가 ──
    # 네이버 SE ONE 표 행 추가 = 표가 선택(se-table-control se-is-on)된 상태에서 좌측
    # '행 컨트롤바'의 se-cell-add-button('N번 아래에 행 추가'). 행 하나당 버튼 하나라
    # 맨 마지막 버튼을 누르면 표 맨 아래에 행이 추가된다. (상단 .se-cell-controlbar-column
    # 의 add-button은 '열 추가'이므로 반드시 -row 컨트롤바로 한정해야 함.)
    try:
        _total = await target.locator(cell_sel).count()
        cur_cells = _total - pre_insert_cells
    except Exception:
        cur_cells = 0
    cur_rows = (cur_cells // grid_cols) if grid_cols else 0
    logger.info(f"표 현재 셀 {cur_cells}개(≈{cur_rows}행), 목표 {n_rows}행 (오프셋={pre_insert_cells})")

    row_add_sel = ".se-cell-controlbar-row .se-cell-add-button"
    table_sel = ".se-section-table, table"

    async def _row_count() -> int:
        try:
            total = await target.locator(cell_sel).count()
            return ((total - pre_insert_cells) // grid_cols) if grid_cols else 0
        except Exception:
            return 0

    # 클릭마다 컨트롤바가 재렌더되어(특히 CI 헤드리스에서 느림) 다음 클릭이 같은 버튼을
    # 치는 레이스가 있다. 고정 횟수 대신 '행 수가 실제로 늘 때까지 폴링'하며 목표까지 반복.
    attempts = 0
    max_attempts = max(0, n_rows - cur_rows) + 5
    while attempts < max_attempts:
        cur = await _row_count()
        if cur >= n_rows:
            break
        attempts += 1
        btns = target.locator(row_add_sel)
        try:
            bc = await btns.count()
        except Exception:
            bc = 0
        if bc == 0:
            logger.warning("행 추가 버튼(se-cell-controlbar-row) 못 찾음 — 중단")
            break
        try:
            await btns.last.click(timeout=2000)          # 맨 아래 행 아래에 추가
        except Exception:
            try:  # 컨트롤바가 표 hover 시 노출되는 경우 대비
                await target.locator(table_sel).first.hover()
                await _delay(120, 200)
                await target.locator(row_add_sel).last.click(timeout=2000, force=True)
            except Exception as e:
                logger.warning(f"행 추가 클릭 실패: {e} — 중단")
                break
        # 행이 실제로 늘 때까지 대기 (race 방지)
        for _ in range(8):
            await _delay(140, 240)
            if await _row_count() > cur:
                break
    logger.info(f"행 추가 후 ≈{await _row_count()}행 (목표 {n_rows}, 시도 {attempts})")

    # ── nth-click 으로 셀별 채우기 ──
    # 각 행을 '실제 표의 열 수(grid_cols)'에 맞춰 패딩/절단 → 행 단위 정렬 보장(줄밀림 방지).
    flat = [c for row in rows for c in (row + [""] * grid_cols)[:grid_cols]]
    try:
        cell_loc = target.locator(cell_sel)
        ccount_total = await cell_loc.count()
        new_cell_count = ccount_total - pre_insert_cells
        logger.info(f"표 셀 {new_cell_count}개 (필요 {len(flat)}, 오프셋={pre_insert_cells})")
        filled = 0
        for i, text in enumerate(flat):
            cell_idx = pre_insert_cells + i
            if cell_idx >= ccount_total:
                break
            try:
                await cell_loc.nth(cell_idx).click()
                await _delay(90, 160)
                await page.keyboard.press("Control+a")
                if text:
                    await page.keyboard.type(text, delay=12)
                else:
                    await page.keyboard.press("Delete")
                filled += 1
            except Exception:
                continue

        # ── 첫 행(헤더)·첫 열(구분) 가운데정렬+볼드 패스 (채우기 완료 후 별도 처리) ──
        try:
            await _format_table_header(page, cell_loc, new_cell_count, grid_cols, n_rows, pre_insert_cells)
        except Exception as e:
            logger.warning(f"표 헤더 서식 패스 예외(계속): {e}")

        # ── 데이터 열 수보다 표 열 수가 많으면 초과 열 삭제 (SE ONE 기본 3열 → 데이터 열 수) ──
        if n_cols < grid_cols:
            cols_to_remove = grid_cols - n_cols
            logger.info(f"초과 열 {cols_to_remove}개 삭제 시도 ({grid_cols}열 → {n_cols}열)")
            removed = 0
            for _ in range(cols_to_remove):
                ok = await _delete_table_last_col(page, grid_cols - removed)
                if ok:
                    removed += 1
                else:
                    logger.warning(f"열 삭제 {removed}/{cols_to_remove} 후 중단 (best-effort 유지)")
                    break
            if removed:
                logger.info(f"초과 열 {removed}/{cols_to_remove}개 삭제 완료")

        await _screenshot(page, "after_table_fill", full_page=True)
        await page.keyboard.press("Escape")
        await page.keyboard.press("Control+End")
        logger.info(f"표 셀 채우기 완료 (nth 방식, {filled}/{len(flat)}, 오프셋={pre_insert_cells})")
        return filled > 0
    except Exception as e:
        logger.warning(f"표 셀 채우기 실패: {e}")
        return False





async def _insert_faq_pairs(page: Page, faq_pairs: list[tuple[str, str]], anchor_text: str) -> bool:
    """FAQ (질문/답변) 짝을 네이버 에디터 인용구 하나에 묶어서 개행 타이핑하여 삽입"""
    if not faq_pairs:
        return False
    logger.info(f"FAQ 인용구 삽입 시도 ({len(faq_pairs)}개 세트, 앵커텍스트: {anchor_text[:30]})")
    target = await _get_editor_frame(page)
    
    # 앵커 단락 뒤로 커서 이동
    await _move_cursor_after_text(page, anchor_text)
    await _delay(300, 500)
    
    # 새 줄 확보
    await page.keyboard.press("Enter")
    await _delay(200, 400)
    
    inserted = 0
    for q_text, a_text in faq_pairs:
        try:
            # 1. 인용구 툴바 버튼 클릭
            btn = target.locator("[data-name='quotation'], button.se-toolbar-item-quotation").first
            if await btn.count():
                await btn.click(timeout=3000)
                await _delay(1000, 1500)  # 인용구 렌더링 대기
                
                # 2. 질문(Q) 타이핑
                await page.keyboard.type(q_text, delay=random.randint(10, 20))
                await _delay(200, 400)
                
                # 3. Shift+Enter 로 인용구 내 강제 개행
                await page.keyboard.down("Shift")
                await page.keyboard.press("Enter")
                await page.keyboard.up("Shift")
                await _delay(200, 400)
                
                # 4. 답변(A) 타이핑
                await page.keyboard.type(a_text, delay=random.randint(10, 20))
                await _delay(300, 500)
                
                # 5. Escape 로 인용구 상자 탈출
                await page.keyboard.press("Escape")
                await _delay(200, 400)
                
                # 6. 다음 FAQ와 간격 확보 위해 Enter 입력
                await page.keyboard.press("Enter")
                await page.keyboard.press("Enter")
                await _delay(300, 500)
                inserted += 1
                logger.info(f"FAQ 세트 {inserted}번 삽입 완료")
        except Exception as e:
            logger.warning(f"FAQ 세트 {inserted+1}번 삽입 예외: {e}")
            continue
            
    await page.keyboard.press("Control+End")
    return inserted > 0


async def _apply_paragraph_style(page: Page, style_name: str = "제목 2") -> bool:
    """현재 선택 영역에 단락 스타일(제목 1, 제목 2 등) 적용"""
    target = await _get_editor_frame(page)
    try:
        # 단락 스타일(본문/제목) 버튼 클릭
        btn = target.locator("[data-name='paragraph-style'], button.se-toolbar-item-paragraph-style").first
        if await btn.count():
            await btn.click(timeout=3000)
            await _delay(300, 600)
            # 드롭다운 옵션 중 원하는 스타일 찾아서 클릭
            opt = target.locator(f"button:has-text('{style_name}'), li:has-text('{style_name}'), [role='option']:has-text('{style_name}')").first
            if await opt.count():
                await opt.click(timeout=2000)
                await _delay(350, 600)
                logger.info(f"단락 스타일 적용 완료: {style_name}")
                return True
    except Exception as e:
        logger.warning(f"단락 스타일 적용 실패 ({style_name}): {e}")
    return False


_align_dropdown_dumped = False


async def _apply_align_center(page: Page) -> bool:
    """셀/단락 텍스트를 가운데 정렬. 네이버는 '정렬 드롭다운'(align-drop-down-with-justify)을
    열어 가운데 옵션을 골라야 한다. (table-align[data-value=center]는 표 위치 정렬이라 오답)"""
    global _align_dropdown_dumped
    target = await _get_editor_frame(page)
    # 1) 정렬 드롭다운 열기
    opened = False
    for sel in ("[data-name='align-drop-down-with-justify']", "[data-name*='align-drop']",
                "button[class*='align'][class*='drop']"):
        try:
            dd = target.locator(sel).first
            if await dd.count() and await dd.is_visible(timeout=400):
                await dd.click(timeout=1000)
                await _delay(180, 320)
                opened = True
                break
        except Exception:
            continue
    if opened and not _align_dropdown_dumped:
        try:
            opts = await target.evaluate("""() =>
                [...document.querySelectorAll('button,[role=option],li,a')]
                  .filter(b => b.offsetParent && /align|center|가운데|정렬|left|right/i.test(
                    (b.getAttribute('aria-label')||'')+(b.getAttribute('data-name')||'')+(b.getAttribute('data-value')||'')+(b.className||'')))
                  .map(b => ({al:b.getAttribute('aria-label'), dn:b.getAttribute('data-name'), dv:b.getAttribute('data-value'), cls:(b.className||'').slice(0,45)})).slice(0,18)
            """)
            logger.info(f"[정렬드롭다운옵션] {opts}")
        except Exception:
            pass
        _align_dropdown_dumped = True
    # 2) 가운데 옵션 클릭 (table-align 류는 제외)
    for sel in ("[data-name='align-center']", "[data-value='center']:not([data-name='table-align'])",
                "button[aria-label*='가운데']", "[class*='align-center']"):
        try:
            loc = target.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=400):
                await loc.click(timeout=1200)
                await _delay(80, 160)
                logger.info(f"가운데정렬(텍스트) 적용: {sel}")
                return True
        except Exception:
            continue
    return False


async def _format_table_header(page: Page, cell_loc, ccount: int, grid_cols: int, n_rows: int, cell_offset: int = 0):
    """표 첫 행(헤더)+첫 열(구분) 셀에 가운데정렬+볼드 적용. 첫 셀에서 서식 툴바를 진단 덤프해
    실제 굵게/가운데 버튼 셀렉터를 로그로 남긴다(블라인드 iteration 단축용)."""
    target = await _get_editor_frame(page)
    idxs = set(range(min(grid_cols, ccount)))          # 첫 행
    for r in range(n_rows):                            # 각 행의 첫 열
        if r * grid_cols < ccount:
            idxs.add(r * grid_cols)
    idxs = sorted(idxs)

    async def _dump_toolbar(tag):
        for fr in (target, page):
            try:
                btns = await fr.evaluate("""() =>
                    [...document.querySelectorAll('button,[role=button]')]
                      .filter(b => b.offsetParent && /bold|align|center|justify|굵|가운데|정렬/i.test(
                        (b.getAttribute('aria-label')||'')+(b.getAttribute('data-name')||'')+(b.getAttribute('data-value')||'')+(b.className||'')+(b.textContent||'')))
                      .map(b => ({al:b.getAttribute('aria-label'), dn:b.getAttribute('data-name'), dv:b.getAttribute('data-value'), cls:(b.className||'').slice(0,45)})).slice(0,22)
                """)
                if btns:
                    logger.info(f"[표서식툴바 {tag} {fr.url[:22]}] {btns}")
            except Exception:
                pass

    bold_sels = ["[data-name='bold']", ".se-toolbar-item-bold",
                 "button[aria-label*='굵']", "[class*='toolbar'][class*='bold']"]
    applied = 0
    for n, i in enumerate(idxs):
        try:
            await cell_loc.nth(cell_offset + i).click()
            await _delay(80, 140)
            await page.keyboard.press("Control+a")     # 셀 내용 선택
            await _delay(60, 110)
            if n == 0:
                await _dump_toolbar("첫헤더셀")
            ok_bold = False
            for sel in bold_sels:
                try:
                    loc = target.locator(sel).first
                    if await loc.count() and await loc.is_visible(timeout=400):
                        await loc.click(timeout=1000)
                        ok_bold = True
                        break
                except Exception:
                    continue
            if not ok_bold:
                await page.keyboard.press("Control+b")
            await _apply_align_center(page)
            applied += 1
            await _delay(60, 110)
        except Exception:
            continue
    logger.info(f"표 헤더/첫열 서식 적용: {applied}/{len(idxs)}개 셀 (굵게+가운데 시도)")


async def _apply_quotation(page: Page, quote_type: str = "") -> bool:
    """현재 선택 영역 또는 위치에 인용구(Quotation) 적용"""
    target = await _get_editor_frame(page)
    try:
        # 툴바의 인용구 버튼 클릭
        btn = target.locator("[data-name='quotation'], button.se-toolbar-item-quotation").first
        if await btn.count():
            await btn.click(timeout=3000)
            await _delay(500, 800)
            
            if quote_type:
                # 네이버 인용구 스타일은 텍스트 라벨이 아닌 아이콘 버튼이라, 다양한 셀렉터로 탐색.
                # '버티컬 라인'(세로줄) 스타일을 우선 적용.
                style_sels = [
                    "[data-value='line']", "[data-name='quotation-line']",
                    ".se-quotation-style-line", "[class*='quotation-style-line']",
                    "[class*='quotation'][class*='line']", "[class*='vertical']",
                    "button[aria-label*='라인']", "[aria-label*='세로']",
                    f"button:has-text('{quote_type}')", f"[role='option']:has-text('{quote_type}')",
                ]
                applied = False
                for sel in style_sels:
                    try:
                        opt = target.locator(sel).first
                        if await opt.count() and await opt.is_visible(timeout=500):
                            await opt.click(timeout=1500)
                            await _delay(300, 550)
                            logger.info(f"인용구 버티컬라인 스타일 적용: {sel}")
                            applied = True
                            break
                    except Exception:
                        continue
                if not applied:
                    logger.info(f"인용구 타입 '{quote_type}' 못 찾음. 기본 적용.")
                    
            logger.info("인용구 컴포넌트 적용 완료")
            return True
    except Exception as e:
        logger.warning(f"인용구 컴포넌트 적용 실패: {e}")
    return False


async def _insert_summary_block(page: Page, summary_text: str, anchor_text: str) -> bool:
    """도입부 뒤 앵커 위치에 핵심 요약 버티컬라인 인용구 블록 삽입"""
    if not summary_text:
        return False
    try:
        if anchor_text:
            await _move_cursor_after_text(page, anchor_text)
        else:
            await page.keyboard.press("Control+Home")
            await _delay(150, 300)
        await page.keyboard.press("Enter")
        await _delay(300, 500)
        ok = await _apply_quotation(page, quote_type="버티컬 라인")
        if ok:
            await page.keyboard.type(summary_text, delay=random.randint(10, 20))
            await _delay(400, 600)
            await page.keyboard.press("Escape")
            await _delay(200, 350)
            await page.keyboard.press("Control+End")
            logger.info(f"요약 블록 삽입 성공 (앵커: {anchor_text[:25] if anchor_text else '없음'})")
            return True
        logger.warning("인용구 적용 실패로 요약 블록 미삽입")
    except Exception as e:
        logger.warning(f"요약 블록 삽입 실패(계속): {e}")
    return False


async def _simulate_human_review(page: Page):
    """실제 인간이 작성한 글을 다시 위아래로 훑어보며 마우스를 움직이는 제스처를 시뮬레이션"""
    logger.info("휴먼 검토 제스처 시뮬레이션 시작...")
    try:
        # 1. 마우스 랜덤 이동
        for _ in range(3):
            x = random.randint(200, 700)
            y = random.randint(150, 500)
            await page.mouse.move(x, y, steps=random.randint(8, 20))
            await _delay(200, 500)
        
        # 2. 본문 천천히 스크롤 다운 (1/3 정도 스크롤)
        for _ in range(4):
            scroll_amount = random.randint(250, 450)
            await page.evaluate(f"window.scrollBy({{top: {scroll_amount}, behavior: 'smooth'}})")
            await _delay(400, 800)
            
        await _delay(600, 1200)
        
        # 3. 본문 천천히 스크롤 업 (다시 맨 위 부근으로)
        for _ in range(4):
            scroll_amount = random.randint(250, 450)
            await page.evaluate(f"window.scrollBy({{top: -{scroll_amount}, behavior: 'smooth'}})")
            await _delay(300, 600)
            
        await _delay(500, 1000)
        logger.info("휴먼 검토 제스처 완료")
    except Exception as e:
        logger.warning(f"휴먼 검토 제스처 실패(계속 진행): {e}")


async def _save_draft(page: Page) -> str:
    """
    임시저장(저장) 버튼 클릭 — 공개 발행 없이 검증용.
    본문/이미지가 에디터에 제대로 들어갔는지 전체 스크린샷으로 확인하기 위함.
    성공 시 'DRAFT_SAVED', 버튼 못 찾으면 'DRAFT_NO_SAVE' 반환.
    """
    await _close_help_panel(page)
    await _delay(800, 1200)
    await _screenshot(page, "draft_before_save", full_page=True)
    target = await _get_editor_frame(page)
    for st, label in [(page, "메인페이지"), (target, "에디터프레임")]:
        try:
            res = await st.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    const save = btns.find(b => {
                        const t = (b.textContent || '').trim();
                        const rect = b.getBoundingClientRect();
                        return (t === '저장' || /^저장\\s*\\d*$/.test(t)) && rect.y < 120;
                    });
                    if (save) { save.click(); return (save.textContent || '저장').trim(); }
                    return null;
                }
            """)
            if res:
                logger.info(f"임시저장 클릭 ({label}): {res}")
                await _delay(2500, 3500)
                await _screenshot(page, "draft_after_save", full_page=True)
                return "DRAFT_SAVED"
        except Exception as e:
            logger.warning(f"임시저장 실패 ({label}): {e.__class__.__name__}")
    logger.warning("임시저장 버튼 못 찾음 — 검증 스크린샷만 저장")
    await _screenshot(page, "draft_no_save_btn", full_page=True)
    return "DRAFT_NO_SAVE"


async def _select_category(page: Page, category_name: str) -> bool:
    """발행 설정 패널에서 카테고리 선택. 패널은 에디터 프레임 안에 있고,
    드롭다운 버튼=[class*='option_category'] [class*='selectbox_button'],
    옵션=label[class*='radio_label'] (텍스트=카테고리명). 클래스 해시는 부분매치."""
    if not category_name:
        return False
    target = await _get_editor_frame(page)
    try:
        opener = target.locator(
            "[class*='option_category'] [class*='selectbox_button'], [class*='selectbox_button']"
        ).first
        await opener.click(timeout=2500)
        await _delay(400, 700)
        pat = re.compile(rf"^{re.escape(category_name)}$")
        clicked = False
        for sel in ["label[class*='radio_label']", "li[class*='item']", "span[class*='option']"]:
            opt = target.locator(sel).filter(has_text=pat).first
            if await opt.count():
                await opt.click(timeout=2000)
                clicked = True
                break
        if not clicked:
            logger.warning(f"카테고리 옵션 못 찾음(기본값 유지): {category_name}")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return False
        await _delay(300, 500)
        logger.info(f"카테고리 선택: {category_name}")
        return True
    except Exception as e:
        logger.warning(f"카테고리 선택 실패(무시): {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def _publish(page: Page, tags: list[str] | None = None, draft: bool = False, category: str = "") -> str | None:
    """
    SE ONE 에디터 발행 흐름:
    1. 도움말 패널 닫기
    2. 상단 '발행' 버튼 클릭 (설정 패널 열림)
    3. 설정 패널에 태그 입력
    4. 패널 하단 '✓ 발행' 버튼 클릭 (Y좌표로 상단 버튼과 구분)
    5. 게시 완료 후 URL 반환

    draft=True 이면 공개 발행 대신 임시저장만 하고 검증용 sentinel 반환.
    """
    if draft:
        return await _save_draft(page)

    await _close_help_panel(page)
    await _delay(1000, 1500)
    await _screenshot(page, "before_publish")

    target = await _get_editor_frame(page)

    # 1단계: 상단 발행 버튼 클릭 (설정 패널 열기)
    clicked = False
    for search_target, label in [(page, "메인페이지"), (target, "에디터프레임")]:
        try:
            js_result = await search_target.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    const pub = btns.find(b => {
                        const txt = b.textContent.trim();
                        if (txt !== '발행') return false;
                        const rect = b.getBoundingClientRect();
                        return rect.y < 100;
                    });
                    if (pub) {
                        pub.click();
                        return (pub.className || 'btn') + '|' + pub.textContent.trim();
                    }
                    return null;
                }
            """)
            if js_result:
                logger.info(f"발행 버튼 JS 클릭 ({label}): {js_result}")
                await _delay(2000, 3000)
                clicked = True
                break
        except Exception as e:
            logger.warning(f"JS 발행 탐색 실패 ({label}): {e.__class__.__name__}")

        if not clicked:
            for sel in [".publish_btn", ".se-publish-btn"]:
                try:
                    btn = search_target.locator(sel).first
                    if await btn.count():
                        await btn.click(timeout=8000)
                        await _delay(2000, 3000)
                        clicked = True
                        break
                except Exception:
                    pass
        if clicked:
            break

    if not clicked:
        logger.error("발행 버튼 없음")
        await _screenshot(page, "publish_btn_not_found")
        return None

    await _screenshot(page, "after_publish_click")
    logger.info("발행 설정 패널 대기 중...")
    await _delay(2000, 3000)

    # 2단계(추가): 카테고리 선택
    if category:
        await _select_category(page, category)
        await _delay(400, 700)

    # 2단계: 설정 패널 태그 입력
    if tags:
        tag_input_found = False
        for t in [page, target]:
            try:
                tag_loc = t.locator('input[placeholder*="태그"]').first
                if not await tag_loc.count():
                    continue
                tag_input_found = True
                for tag in tags[:10]:
                    await tag_loc.click()
                    await _delay(150, 250)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(tag, delay=30)
                    await _delay(200, 350)
                    await page.keyboard.press("Enter")
                    await _delay(350, 500)
                logger.info(f"태그 {min(len(tags), 10)}개 입력 완료")
                await _delay(500, 800)
                break
            except Exception as e:
                logger.warning(f"태그 입력 실패: {e.__class__.__name__}")
                continue
        if not tag_input_found:
            logger.warning("발행 설정 패널 태그 입력창 없음 — 태그 생략")

    # 3단계: 설정 패널 하단 '✓ 발행' 클릭
    confirmed = False
    for t in [page, target]:
        try:
            res = await t.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    const confirmBtn = btns.find(b => {
                        const txt = b.textContent.trim();
                        if (!txt.includes('발행')) return false;
                        const rect = b.getBoundingClientRect();
                        return rect.y > 200 && rect.width > 30;
                    });
                    if (confirmBtn) {
                        confirmBtn.click();
                        const r = confirmBtn.getBoundingClientRect();
                        return confirmBtn.className + '|y:' + Math.round(r.y);
                    }
                    return null;
                }
            """)
            if res:
                logger.info(f"발행 설정 확인 클릭: {res}")
                await _delay(8000, 12000)
                confirmed = True
                break
        except Exception as e:
            logger.warning(f"발행 확인 JS 실패: {e.__class__.__name__}")

    final_url = page.url
    logger.info(f"발행 후 URL (1차): {final_url}")

    if "Redirect=Write" in final_url or "PostWriteForm" in final_url:
        if confirmed:
            logger.info("URL 아직 에디터 — 추가 10초 대기")
            await _delay(8000, 12000)
            final_url = page.url
            logger.info(f"발행 후 URL (2차): {final_url}")

    await _screenshot(page, "after_publish")

    is_post_url = (
        re.search(r"/\d{9,}", final_url) is not None
        and "Redirect=Write" not in final_url
        and "PostWriteForm" not in final_url
    )

    if is_post_url:
        logger.info(f"발행 성공 — 포스트 URL: {final_url}")
        return final_url

    logger.error(f"발행 최종 실패 — URL: {final_url}")
    await _screenshot(page, "publish_failed_final")
    return None


async def _post(
    naver_id: str,
    naver_pw: str,
    blog_id: str,
    title: str,
    body: str,
    tags: list[str],
    naver_cookies: str = "",
    images: list[dict] | None = None,
    draft: bool = False,
    allow_pw_login: bool = False,
    table_str: str = "",
    table_strs: list[str] | None = None,
    subheadings: list[str] | None = None,
    faq_questions: list[str] | None = None,
    category: str = "",
    faq_pairs: list[tuple[str, str]] | None = None,
    summary_text: str = "",
) -> dict | None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=_UA,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await ctx.new_page()

        cookies_ok = await _load_cookies(ctx, naver_cookies)

        if not cookies_ok or not await _is_logged_in(page):
            # ⚠️ 보호조치 재발 방지: CI(데이터센터 IP)에서의 ID/PW 자동 로그인은
            # 네이버가 '타인 로그인'으로 판단해 계정을 잠그는 가장 큰 트리거다.
            # 따라서 기본적으로 쿠키만 사용하고, 쿠키가 죽으면 즉시 중단 + 알림.
            if not allow_pw_login:
                logger.error(
                    "쿠키 무효/만료 — ID/PW 자동 로그인은 보호조치 위험으로 생략. "
                    "새 쿠키 발급 후 NAVER_COOKIES 시크릿을 갱신하세요. (ALLOW_PW_LOGIN=true 면 강제 로그인)"
                )
                await _screenshot(page, "cookie_invalid_abort", full_page=True)
                await browser.close()
                return None
            logger.warning("쿠키 실패 — ALLOW_PW_LOGIN=true 라 ID/PW 로그인 시도 (보호조치 위험 감수)")
            if not naver_id or not naver_pw:
                logger.error("ID/PW 없음 — 종료")
                await browser.close()
                return None
            if not await _login(page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)

        write_page = await _navigate_to_write_page(ctx, page, naver_id, blog_id)

        if write_page is None and allow_pw_login:
            logger.warning("에디터 진입 실패 — ALLOW_PW_LOGIN=true 라 ID/PW 재로그인 후 재시도")
            if not naver_id or not naver_pw:
                logger.error("ID/PW 없음 — 종료")
                await browser.close()
                return None
            login_page = await ctx.new_page()
            if not await _login(login_page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)
            write_page = await _navigate_to_write_page(ctx, login_page, naver_id, blog_id)

        if write_page is None:
            logger.error(
                "에디터 진입 실패 — 종료. (쿠키 무효 가능성 — 새 쿠키 발급 권장. "
                "ID/PW 자동 로그인은 보호조치 방지를 위해 비활성)"
            )
            await browser.close()
            return None

        logger.info(f"에디터 진입 성공: {write_page.url}")
        await _delay(2000, 3000)
        await _screenshot(write_page, "editor_ready")

        await _dismiss_draft_popup(write_page)
        await _delay(500, 800)

        await _close_help_panel(write_page)
        await _delay(1000, 1500)

        await _screenshot(write_page, "editor_ready2")

        # 제목 입력
        logger.info(f"제목 입력 시작: {title[:40]}")
        await _fill_title(write_page, title)
        await _delay(500, 800)
        await _screenshot(write_page, "after_title")

        # ── 본문 입력 (소실 방지 최우선): 마커 제거한 전체 본문을 한 번에 안정 입력 ──
        # [사진N] 마커가 문장 중간에 있으면 앵커가 잘려서 이미지가 문단 중간에 삽입되므로
        # 마커를 항상 독립된 줄로 강제 정규화한다.
        body = re.sub(r"([^\n])\[사진(\d+)\]", r"\1\n[사진\2]", body)
        body = re.sub(r"\[사진(\d+)\]([^\n])", r"[사진\1]\n\2", body)
        _PHOTO_MARKER = re.compile(r"\[사진(\d+)\]")
        marker_positions = _PHOTO_MARKER.findall(body)
        # 다중 표: 각 [표삽입] 위치별로 (표 데이터, 앵커 텍스트) 매핑
        src_tables = list(table_strs) if table_strs else ([table_str] if table_str else [])
        table_jobs: list[tuple[str, str]] = []
        for i, m in enumerate(re.finditer(r"\[표삽입\]", body)):
            data = src_tables[i] if i < len(src_tables) else None
            if not data:
                continue
            table_jobs.append((data, _preceding_text_at(body, m.start())))
        table_anchor_set = {a.strip() for _, a in table_jobs if a}
        faq_anchor_text = _get_preceding_text(body, "[FAQ삽입]") if faq_pairs else None
        # 요약 블록 앵커: [요약삽입] 직전 텍스트 (도입부 마지막 줄)
        summary_m = re.search(r"\[요약삽입\]", body)
        summary_anchor_text = _preceding_text_at(body, summary_m.start()) if summary_m and summary_text else None
        body_text = _PHOTO_MARKER.sub("", body)
        body_text = re.sub(r"\[표삽입\]", "", body_text)  # 표 자리표시자 제거
        body_text = re.sub(r"\[FAQ삽입\]", "", body_text)  # FAQ 자리표시자 제거
        body_text = re.sub(r"\[요약삽입\]", "", body_text)  # 요약 자리표시자 제거
        # ※ [구분선]은 _type_in_editor가 처리하므로 body_text에 남겨둬야 함
        # 혹시 본문에 남은 표/FAQ 마커 잔재 제거(대괄호 유무 무관) — 본문 노출 방지
        body_text = re.sub(r"\[?\s*(?:표시작|표끝|FAQ시작|FAQ끝|요약시작|요약끝)\s*\]?", "", body_text)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

        logger.info(f"본문 전체 입력 시작 ({len(body_text)}자, [사진] 마커 {len(marker_positions)}개, 표 {len(table_jobs)}개, FAQ앵커텍스트: {faq_anchor_text[:20] if faq_anchor_text else None})")
        await _type_in_editor(write_page, body_text)
        await _delay(1000, 1500)

        # 본문 입력 검증
        editor_len = await _editor_text_length(write_page)
        min_required = min(800, int(len(body_text) * 0.5))
        logger.info(
            f"에디터 본문 검증: 입력됨 {editor_len}자 / 생성 {len(body_text)}자 (최소 {min_required}자)"
        )
        if editor_len < min_required:
            logger.error(
                f"본문 입력 검증 실패 — 에디터 {editor_len}자 < 최소 {min_required}자. 본문 소실 의심으로 발행 중단."
            )
            await _screenshot(write_page, "body_verify_failed", full_page=True)
            if not draft:
                await browser.close()
                return None
            logger.warning("드래프트 모드 — 검증 실패해도 스크린샷 확인 위해 계속 진행")

        # ── 본문 글꼴 + 소제목 제목 스타일 ──
        try:
            await _apply_font_all(write_page, font_dn="nanummaruburi")
        except Exception as e:
            logger.warning(f"글꼴 적용 예외(계속): {e}")
        try:
            await _style_paragraphs(write_page, subheadings or [], size_label="19", bold=True, label="소제목", style_type="quotation_vertical")
        except Exception as e:
            logger.warning(f"소제목 스타일 예외(계속): {e}")

        # ── 진짜 네이버 표 삽입 (다중 표 지원) ──
        for ti, (tdata, tanchor) in enumerate(table_jobs):
            try:
                ok_tbl = await _insert_table(write_page, tdata, tanchor)
                logger.info(f"표 {ti+1}/{len(table_jobs)} 삽입 {'성공' if ok_tbl else '실패(본문 유지)'} (앵커: {tanchor[:20]})")
            except Exception as e:
                logger.warning(f"표 {ti+1} 삽입 예외(계속): {e}")

        # ── FAQ 인용구 세트 삽입 (Q와 A를 하나의 인용구 상자에 개행으로 묶어 삽입) ──
        if faq_pairs and faq_anchor_text is not None:
            try:
                ok_faq = await _insert_faq_pairs(write_page, faq_pairs, faq_anchor_text)
                logger.info(f"FAQ 인용구 세트 삽입 {'성공' if ok_faq else '실패(본문 유지)'}")
            except Exception as e:
                logger.warning(f"FAQ 인용구 세트 삽입 예외(계속): {e}")

        # ── 핵심 요약 버티컬라인 블록 삽입 (도입부 바로 뒤) ──
        if summary_text and summary_anchor_text is not None:
            try:
                ok_summary = await _insert_summary_block(write_page, summary_text, summary_anchor_text)
                logger.info(f"요약 블록 삽입 {'성공' if ok_summary else '실패(본문 유지)'}")
            except Exception as e:
                logger.warning(f"요약 블록 삽입 예외(계속): {e}")

        # ── 이미지 삽입 (best-effort): 단락 앵커 위치에 삽입, 실패해도 본문 유지 ──
        images_inserted = 0
        MAX_IMG = 7
        if images and marker_positions:
            anchors = _compute_image_text_anchors(body)
            logger.info(f"이미지 앵커 {len(anchors)}개 계산 — 단락 위치별 삽입 시도")
            for anchor_text, img_idx in anchors:
                if images_inserted >= MAX_IMG:
                    break
                if not (0 <= img_idx < len(images)):
                    continue
                # ── 앵커 충돌 방지 ─────────────────────────────────────
                # 표/FAQ 앵커와 같은 단락이면 이미지가 표(셀) 안에 끼어 들어가므로 건너뛴다.
                # URL 줄(관련링크)에는 이미지를 붙이지 않는다(링크 카드 자리 침범 방지).
                _a = (anchor_text or "").strip()
                if _a and _a in table_anchor_set:
                    logger.warning(f"이미지 {img_idx+1}번 앵커가 표 앵커와 동일 — 표 안 삽입 방지로 건너뜀")
                    continue
                if faq_anchor_text and _a == faq_anchor_text.strip():
                    logger.warning(f"이미지 {img_idx+1}번 앵커가 FAQ 앵커와 동일 — 건너뜀")
                    continue
                if _a.startswith("http://") or _a.startswith("https://"):
                    logger.warning(f"이미지 {img_idx+1}번 앵커가 URL(관련링크) 줄 — 건너뜀")
                    continue
                # 미리 만든 로컬 이미지(예: AI 대표 요리사진)가 있으면 그대로 사용
                local_path = images[img_idx].get("local_path") or _download_image_to_temp(
                    images[img_idx].get("url", ""), label=images[img_idx].get("label")
                )
                if not local_path:
                    logger.warning(f"이미지 {img_idx+1}번 다운로드 실패 — 건너뜀")
                    continue
                # anchor에서 [가운데] 접두사 제거 (에디터 실제 텍스트와 매칭)
                clean_anchor = re.sub(r"^\[가운데\]\s*", "", anchor_text)
                # 헤더카드/최상단 이미지(첫 이미지+로컬 생성 + 빈 앵커)는 빈앵커→문서끝(Control+End)이 아니라
                # 문서 맨 위(Control+Home)에 삽입해야 한다(gov/health 브랜드 헤더카드가 글 맨 아래로 가던 버그).
                is_header_top = img_idx == 0 and bool(images[img_idx].get("local_path")) and not clean_anchor.strip()
                if is_header_top:
                    await write_page.keyboard.press("Control+Home")
                    await _delay(150, 300)
                else:
                    await _move_cursor_after_text(write_page, clean_anchor)
                # 커서가 표 안에 들어갔으면 이미지가 셀에 끼므로 건너뛴다(이중 안전장치).
                if await _caret_in_table(write_page):
                    logger.warning(f"이미지 {img_idx+1}번 커서가 표 안 — 셀 삽입 방지로 건너뜀")
                    continue
                # 단락 바로 아래에 단독 삽입되도록 Enter를 입력하여 새로운 단락 라인을 만든 뒤 이미지 삽입
                await write_page.keyboard.press("Enter")
                await _delay(200, 400)
                img_caption = images[img_idx].get("label") or images[img_idx].get("alt_text", "")
                ok = await _insert_image_file(
                    write_page,
                    local_path=local_path,
                    alt_text=img_caption,
                )
                # 첫 이미지 등 간헐 실패 대비: 1회 재시도 (사진 팝업/에디터 워밍업 지연으로
                # 첫 삽입만 카운트 검증 전에 실패하던 케이스를 잡는다. 후속 이미지는 동일 경로로 성공)
                if not ok:
                    logger.warning(f"이미지 {img_idx+1}번 1차 삽입 실패 — 재시도")
                    await _delay(1500, 2000)
                    if img_idx == 0:
                        await write_page.keyboard.press("Control+Home")
                        await _delay(150, 300)
                    else:
                        clean_anchor = re.sub(r"^\[가운데\]\s*", "", anchor_text)
                        await _move_cursor_after_text(write_page, clean_anchor)
                    await write_page.keyboard.press("Enter")
                    await _delay(200, 400)
                    ok = await _insert_image_file(
                        write_page,
                        local_path=local_path,
                        alt_text=img_caption,
                    )
                if ok:
                    images_inserted += 1
                    logger.info(f"이미지 {img_idx+1}번 삽입 성공 (앵커: {anchor_text[:20]})")
                else:
                    logger.warning(f"이미지 {img_idx+1}번 삽입 실패(재시도 포함) — 본문 유지하고 계속")
                await _delay(500, 900)
        elif images:
            logger.info(f"마커 없음 — 본문 끝에 이미지 best-effort 삽입 ({min(3, len(images))}장)")
            for img in images[:3]:
                local_path = img.get("local_path") or _download_image_to_temp(img.get("url", ""), label=img.get("label"))
                if not local_path:
                    continue
                await _move_cursor_after_text(write_page, "")
                if await _insert_image_file(write_page, local_path=local_path, alt_text=img.get("label") or img.get("alt_text", "")):
                    images_inserted += 1
                await _delay(500, 900)

        await _delay(1000, 1500)
        await _screenshot(write_page, "after_body", full_page=True)
        logger.info(f"이미지 {images_inserted}장 실제 삽입 완료 (검증: 에디터 이미지 수 기준)")

        # 발행 전 휴먼 제스처 시뮬레이션
        await _simulate_human_review(write_page)

        # 발행 (draft=True 면 임시저장만)
        post_url = await _publish(write_page, tags=tags, draft=draft, category=category)
        await _save_cookies(ctx)
        await browser.close()

        if post_url:
            return {
                "post_url": post_url,
                "images_inserted": images_inserted,
                "editor_text_len": editor_len,
                "draft": draft,
            }
        logger.error("발행 실패")
        return None


def post_to_naver_blog(
    naver_id: str,
    naver_pw: str,
    blog_id: str,
    title: str,
    body: str,
    tags: list[str],
    naver_cookies: str = "",
    images: list[dict] | None = None,
    draft: bool = False,
    allow_pw_login: bool = False,
    table_str: str = "",
    table_strs: list[str] | None = None,
    subheadings: list[str] | None = None,
    faq_questions: list[str] | None = None,
    category: str = "",
    faq_pairs: list[tuple[str, str]] | None = None,
    summary_text: str = "",
) -> dict | None:
    return asyncio.run(
        _post(
            naver_id=naver_id,
            naver_pw=naver_pw,
            blog_id=blog_id,
            title=title,
            body=body,
            tags=tags,
            naver_cookies=naver_cookies,
            images=images,
            draft=draft,
            allow_pw_login=allow_pw_login,
            table_str=table_str,
            table_strs=table_strs,
            subheadings=subheadings,
            faq_questions=faq_questions,
            category=category,
            faq_pairs=faq_pairs,
            summary_text=summary_text,
        )
    )
