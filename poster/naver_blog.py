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
            if line.strip():
                # 인간적인 타이핑: 짧은 문장은 빠르게, 긴 문장은 느리게, 중간에 쉬는 구간
                char_delay = random.randint(12, 35)
                await page.keyboard.type(line.strip(), delay=char_delay)
                # 문장 끝에 자연스러운 짧은 멈춤
                if j < len(lines) - 1:
                    await _delay(80, 250)
            if j < len(lines) - 1:
                await page.keyboard.press("Enter")
        if i < len(paragraphs) - 1:
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
            # 단락 사이 더 긴 자연스러운 멈춤
            await _delay(200, 600)


def _compute_image_anchors(body: str) -> list[tuple[int, int]]:
    """
    [사진N] 마커가 본문에서 '몇 번째 줄-단락(0-based) 뒤'에 위치하는지 계산.
    반환: [(para_index, image_index_0based), ...] — 위→아래 순서.

    _type_in_editor 는 본문을 \\n 줄마다 Enter로 끊어 SE 에디터의
    .se-text-paragraph 를 줄 단위로 만든다. 따라서 마커 앞의 '비어있지 않은 줄 수'가
    곧 그 위치의 .se-text-paragraph 인덱스(+1)에 대응한다.
    이미지는 .se-section-image 로 삽입되어 .se-text-paragraph 인덱스를 바꾸지 않으므로
    위에서부터 순서대로 처리해도 인덱스가 안정적이다 (정밀하진 않아도 ±1 수준).
    """
    marker = re.compile(r"\[사진(\d+)\]")
    anchors: list[tuple[int, int]] = []
    for m in marker.finditer(body):
        before_clean = marker.sub("", body[: m.start()])
        lines = [ln for ln in before_clean.split("\n") if ln.strip()]
        para_index = max(0, len(lines) - 1)
        anchors.append((para_index, int(m.group(1)) - 1))
    return anchors


async def _move_cursor_to_paragraph_end(page: Page, para_idx: int):
    """본문 para_idx번째 단락(0-based) 끝으로 커서 이동. para_idx<0 이면 문서 끝."""
    target = await _get_editor_frame(page)
    try:
        if para_idx < 0:
            await page.keyboard.press("Control+End")
            await _delay(150, 300)
            return
        paras = target.locator(".se-section-text .se-text-paragraph")
        cnt = await paras.count()
        if cnt == 0:
            await page.keyboard.press("Control+End")
            await _delay(150, 300)
            return
        idx = min(para_idx, cnt - 1)
        await paras.nth(idx).click()
        await page.keyboard.press("End")
        await _delay(150, 300)
    except Exception:
        try:
            await page.keyboard.press("Control+End")
        except Exception:
            pass


def _download_image_to_temp(url: str) -> str | None:
    """이미지 URL → 임시 파일로 다운로드. 경로 반환, 실패 시 None."""
    try:
        suffix = ".jpg" if "jpg" in url.lower() else ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tmp.write(resp.read())
        tmp.close()
        logger.info(f"이미지 다운로드 완료: {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.warning(f"이미지 다운로드 실패: {e}")
        return None


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

        # ── 방법 1: 파일 선택창 통합 인터셉터 ──────────────────────
        try:
            async with page.expect_file_chooser(timeout=8000) as fc_info:
                # 1a. 에디터에 포커스 확보
                try:
                    ed = target.locator("[contenteditable='true']").first
                    if await ed.count():
                        await ed.click()
                        await _delay(200, 400)
                except Exception:
                    pass

                # 1b. 사진 버튼 클릭
                if not await _click_photo_button(page):
                    raise RuntimeError("사진 버튼 없음")

                # 1c. 다이얼로그 대기 후 '내 PC에서' 탐색
                await asyncio.sleep(2.5)
                await _screenshot(page, "after_photo_btn", full_page=True)

                # 모든 프레임에서 버튼 탐색 (로그 포함)
                pc_sels = [
                    "text=내 PC에서", "text=내PC에서", "text=컴퓨터에서",
                    "text=파일에서", "text=PC에서", "text=파일 선택",
                    "button:has-text('파일')", "label:has-text('파일')",
                    "[class*='tabPC']", "[class*='upload_pc']",
                    "[class*='local']", "[class*='pc_btn']",
                ]
                for frame in _all_frames():
                    # 프레임 내 버튼 목록 디버그 로그
                    try:
                        btns = await frame.evaluate("""
                            () => [...document.querySelectorAll('button,label,a')]
                                .filter(e => {
                                    const t = (e.textContent || '').toLowerCase();
                                    const c = (e.className || '').toLowerCase();
                                    return ['파일','pc','업로드','upload','local'].some(k=>t.includes(k)||c.includes(k));
                                })
                                .map(e => ({tag:e.tagName, txt:e.textContent.trim().slice(0,25), cls:e.className.slice(0,40)}))
                                .slice(0,5)
                        """)
                        if btns:
                            logger.info(f"[frame {frame.url[:50]}] 버튼: {btns}")
                    except Exception:
                        pass

                    for sel in pc_sels:
                        try:
                            btn = frame.locator(sel).first
                            if await btn.count() > 0:
                                # 보이는 버튼만 클릭 (timeout 없이 빠르게 확인)
                                try:
                                    vis = await btn.is_visible(timeout=500)
                                except Exception:
                                    vis = False
                                if not vis:
                                    continue
                                logger.info(f"'내 PC에서' 발견 클릭: {sel}")
                                await btn.click(timeout=2000)
                                break
                        except Exception:
                            continue
                    else:
                        continue
                    break
                else:
                    logger.info("'내 PC에서' 버튼 없음 — 파일창 직접 트리거 여부 대기")

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


async def _publish(page: Page, tags: list[str] | None = None, draft: bool = False) -> str | None:
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
            logger.info("쿠키 없음 — ID/PW 로그인 시도")
            if not naver_id or not naver_pw:
                logger.error("ID/PW 없음 — 종료")
                await browser.close()
                return None
            if not await _login(page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)

        write_page = await _navigate_to_write_page(ctx, page, naver_id, blog_id)

        if write_page is None:
            logger.info("에디터 진입 실패 — ID/PW 재로그인 후 재시도")
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
            logger.error("재시도 후에도 에디터 진입 실패 — 종료")
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
        # 예전엔 텍스트→이미지→텍스트 인터리브였는데, 이미지 삽입 실패가 포커스를 깨
        # 인트로 이후 본문이 통째로 소실됐다. 이제 텍스트를 먼저 전부 넣고, 이미지는
        # 그 뒤에 best-effort로 얹는다 (이미지 실패해도 본문은 절대 잃지 않음).
        _PHOTO_MARKER = re.compile(r"\[사진(\d+)\]")
        marker_positions = _PHOTO_MARKER.findall(body)
        body_text = _PHOTO_MARKER.sub("", body)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

        logger.info(f"본문 전체 입력 시작 ({len(body_text)}자, [사진] 마커 {len(marker_positions)}개)")
        await _type_in_editor(write_page, body_text)
        await _delay(1000, 1500)

        # 본문 입력 검증 — 에디터 실제 텍스트가 비면 발행 금지 (인트로만 발행되는 사고 차단)
        editor_len = await _editor_text_length(write_page)
        min_required = max(800, int(len(body_text) * 0.5))
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

        # ── 이미지 삽입 (best-effort): 단락 앵커 위치에 삽입, 실패해도 본문 유지 ──
        images_inserted = 0
        MAX_IMG = 7
        if images and marker_positions:
            anchors = _compute_image_anchors(body)
            logger.info(f"이미지 앵커 {len(anchors)}개 계산 — 단락 위치별 삽입 시도")
            for para_idx, img_idx in anchors:
                if images_inserted >= MAX_IMG:
                    break
                if not (0 <= img_idx < len(images)):
                    continue
                local_path = _download_image_to_temp(images[img_idx]["url"])
                if not local_path:
                    logger.warning(f"이미지 {img_idx+1}번 다운로드 실패 — 건너뜀")
                    continue
                await _move_cursor_to_paragraph_end(write_page, para_idx)
                ok = await _insert_image_file(
                    write_page,
                    local_path=local_path,
                    alt_text=images[img_idx].get("alt_text", ""),
                )
                if ok:
                    images_inserted += 1
                    logger.info(f"이미지 {img_idx+1}번 삽입 성공 (단락 {para_idx} 뒤)")
                else:
                    logger.warning(f"이미지 {img_idx+1}번 삽입 실패 — 본문 유지하고 계속")
                await _delay(500, 900)
        elif images:
            logger.info(f"마커 없음 — 본문 끝에 이미지 best-effort 삽입 ({min(3, len(images))}장)")
            for img in images[:3]:
                local_path = _download_image_to_temp(img["url"])
                if not local_path:
                    continue
                await _move_cursor_to_paragraph_end(write_page, -1)
                if await _insert_image_file(write_page, local_path=local_path, alt_text=img.get("alt_text", "")):
                    images_inserted += 1
                await _delay(500, 900)

        await _delay(1000, 1500)
        await _screenshot(write_page, "after_body", full_page=True)
        logger.info(f"이미지 {images_inserted}장 실제 삽입 완료 (검증: 에디터 이미지 수 기준)")

        # 발행 (draft=True 면 임시저장만)
        post_url = await _publish(write_page, tags=tags, draft=draft)
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
) -> dict | None:
    return asyncio.run(
        _post(naver_id, naver_pw, blog_id, title, body, tags, naver_cookies, images, draft)
    )
