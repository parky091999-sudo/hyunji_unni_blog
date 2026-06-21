"""
Playwright로 네이버 블로그 자동 포스팅
SE3/SE4 에디터 기반 — 쿠키 세션 재사용으로 로그인 최소화

[핵심 발견사항]
- www.naver.com, GoBlogWrite.naver 는 Akamai CDN이 클라우드 IP 차단
- section.blog.naver.com/BlogHome.naver 는 접근 가능
- 글쓰기 버튼을 BlogHome에서 직접 클릭해야 에디터 진입 가능 (Referer 필요)
- 새 탭이 열리면 그 탭을 에디터 페이지로 사용
"""
import asyncio
import json
import logging
import os
import random

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


async def _screenshot(page: Page, name: str):
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        path = os.path.join(SHOT_DIR, f"{name}.png")
        await page.screenshot(path=path, full_page=False)
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
    # 확실한 에디터 URL 패턴
    good = ["postwrite", "PostWrite", "Redirect=Write", "editForm"]
    return any(g in url for g in good)


async def _navigate_to_write_page(ctx: BrowserContext, page: Page, naver_id: str, blog_id: str) -> Page | None:
    """
    글쓰기 에디터 페이지 진입.
    새 탭이 열리면 그 탭을 반환하고, 현재 페이지면 page 반환.
    실패 시 None 반환.

    핵심: BlogHome에서 직접 CLICK만 사용 (CDN 차단 때문에 goto 불가)
    """

    # BlogHome 접속 — section.blog.naver.com은 클라우드 IP 허용됨
    blog_home_url = "https://section.blog.naver.com/BlogHome.naver"
    logger.info(f"BlogHome 접속: {blog_home_url}")
    await page.goto(blog_home_url, wait_until="domcontentloaded", timeout=30000)
    await _delay(2000, 3000)
    await _screenshot(page, "blog_home")
    logger.info(f"BlogHome URL: {page.url}")

    # 로그인 필요 여부 체크 (BlogHome이 로그인 페이지로 리다이렉트됐는지)
    if "nidlogin" in page.url or "login" in page.url.lower():
        logger.warning("BlogHome이 로그인 페이지로 리다이렉트 — 세션 만료")
        return None

    # 글쓰기 버튼 셀렉터 순서
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

            # 클릭 전 현재 페이지 수 확인
            pages_before = len(ctx.pages)

            # 클릭: 새 탭 열릴 수 있음
            try:
                async with ctx.expect_page(timeout=8000) as new_page_info:
                    await el.click()
                new_pg = await new_page_info.value
                await new_pg.wait_for_load_state("domcontentloaded", timeout=20000)
                await _delay(2000, 3000)
                await _screenshot(new_pg, "write_new_tab")
                logger.info(f"새 탭 열림: {new_pg.url}")
                # 에디터 요소 대기
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

            # 새 탭 없는 경우: 현재 페이지에서 에디터 대기
            await _delay(3000, 5000)
            cur = page.url
            logger.info(f"클릭 후 현재 URL: {cur}")
            await _screenshot(page, "after_click_write")

            # Redirect=Write 패턴: 추가 대기 후 에디터 확인
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
                    # networkidle 대기 후 다시 확인
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

    # 방법 2: 구형 PostWriteForm 시도 (blogId 파라미터 포함)
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


async def _close_help_panel(page: Page):
    """도움말 패널 닫기 (SE ONE 에디터 초기 실행 시 자동으로 열림)"""
    close_sels = [
        "button[aria-label*='닫기']",
        ".se-help-panel .se-close-btn",
        ".help_panel .close",
        "button.se-close-btn",
        "[class*='help'][class*='close']",
        "[class*='helpPanel'] button",
    ]
    for sel in close_sels:
        try:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click()
                await _delay(500, 800)
                logger.info(f"도움말 패널 닫음: {sel}")
                return
        except Exception:
            continue
    # 키보드 Escape로도 시도
    try:
        await page.keyboard.press("Escape")
        await _delay(300, 500)
    except Exception:
        pass


async def _fill_title(page: Page, title: str):
    """제목 입력 — 메인 페이지와 iframe 모두 탐색"""
    target = await _get_editor_frame(page)

    # SE ONE 에디터: 제목은 iframe 내부에서 첫 번째 contenteditable 또는 .se-title-text
    title_sels = [
        # SE ONE 제목 (contenteditable div, placeholder는 CSS pseudo-element)
        ".se-title-text",
        "[data-se-type='title']",
        ".se-section-oglink .se-title",
        # 일반 contenteditable (이 중 첫 번째가 제목일 가능성)
        "div[contenteditable='true']",
        # input 형태
        "input[name='title']",
        "[placeholder='제목']",
        "[data-placeholder='제목']",
    ]

    # 먼저 메인 페이지(write_page)에서 탐색
    for search_target in [page, target]:
        for sel in title_sels:
            try:
                t = search_target.locator(sel).first
                if await t.count():
                    await t.click()
                    await _delay(300, 500)
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(title, delay=20)
                    logger.info(f"제목 입력 완료 ({sel}): {title[:40]}")
                    return
            except Exception:
                continue

    logger.warning("제목 입력 영역을 찾지 못함")


async def _type_in_editor(page: Page, text: str):
    target = await _get_editor_frame(page)
    body_sels = [
        ".se-text-paragraph",  # SE ONE 본문 (확인됨)
        "div[contenteditable='true']:not([data-placeholder='제목'])",
        "[data-se-type='text'] [contenteditable]",
        ".se-component-content",
        ".se-main-container",
        "[contenteditable='true']",
    ]
    clicked = False
    for sel in body_sels:
        try:
            loc = target.locator(sel).first
            if await loc.count():
                await loc.click()
                clicked = True
                logger.info(f"에디터 본문 클릭: {sel}")
                break
        except Exception:
            continue

    if not clicked:
        await page.keyboard.press("Tab")  # Frame에는 keyboard 없음 — page 사용

    await _delay(500, 800)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        lines = para.split("\n")
        for j, line in enumerate(lines):
            if line.strip():
                await page.keyboard.type(line.strip(), delay=15)  # page.keyboard 사용
            if j < len(lines) - 1:
                await page.keyboard.press("Enter")
        if i < len(paragraphs) - 1:
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
        await _delay(100, 200)


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
                    await page.keyboard.press("Enter")  # page.keyboard 사용
                    await _delay(300, 500)
                logger.info(f"태그 {len(tags)}개 입력 완료")
                return
        except Exception:
            continue
    logger.warning("태그 입력 영역 없음 — 태그 생략")


async def _publish(page: Page) -> str | None:
    await _screenshot(page, "before_publish")
    target = await _get_editor_frame(page)

    pub_sels = [
        "button:has-text('발행')",
        "button:has-text('게시')",
        ".publish_btn",
        "[data-gdl-area='bottom'] button:last-child",
        "button.confirm",
        ".btn_submit",
    ]
    clicked = False
    for sel in pub_sels:
        try:
            btn = target.locator(sel).first
            if await btn.count():
                logger.info(f"발행 버튼 클릭: {sel}")
                await btn.click()
                await _delay(2000, 3000)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        logger.error("발행 버튼 없음")
        await _screenshot(page, "publish_btn_not_found")
        return None

    # 발행 확인 팝업
    for sel in ["button:has-text('확인')", "button:has-text('발행하기')", ".btn_confirm"]:
        try:
            btn = target.locator(sel).first
            if await btn.count():
                await btn.click()
                await _delay(3000, 5000)
                break
        except Exception:
            continue

    final_url = page.url
    logger.info(f"발행 후 URL: {final_url}")
    await _screenshot(page, "after_publish")
    return final_url if final_url and "about:blank" not in final_url else None


async def _post(
    naver_id: str,
    naver_pw: str,
    blog_id: str,
    title: str,
    body: str,
    tags: list[str],
    naver_cookies: str = "",
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

        # 쿠키 로드
        cookies_ok = await _load_cookies(ctx, naver_cookies)

        # 쿠키 없거나 NID_AUT 없으면 ID/PW 로그인
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

        # 글쓰기 페이지 진입 (BlogHome → 클릭)
        write_page = await _navigate_to_write_page(ctx, page, naver_id, blog_id)

        if write_page is None:
            # 세션 만료 가능성 — 강제 재로그인 후 재시도
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

        # 도움말 패널 닫기 (SE ONE 에디터 첫 실행 시 자동 열림)
        await _close_help_panel(write_page)
        await _delay(500, 1000)

        # 제목 / 본문 / 태그 입력
        await _fill_title(write_page, title)
        await _delay(500, 800)
        await _type_in_editor(write_page, body)
        await _delay(1000, 1500)
        await _add_tags(write_page, tags)
        await _delay(500, 800)

        # 발행
        post_url = await _publish(write_page)
        await _save_cookies(ctx)
        await browser.close()

        if post_url:
            return {"post_url": post_url}
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
) -> dict | None:
    return asyncio.run(_post(naver_id, naver_pw, blog_id, title, body, tags, naver_cookies))
