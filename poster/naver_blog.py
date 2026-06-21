"""
Playwright로 네이버 블로그 자동 포스팅
SE3 에디터 기반 — 쿠키 세션 재사용으로 로그인 최소화
"""
import asyncio
import json
import logging
import os
import random

from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

ROOT     = os.path.dirname(os.path.dirname(__file__))
COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")
WRITE_URL   = "https://blog.naver.com/PostWriteForm.naver"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def _delay(ms_min: int = 300, ms_max: int = 800):
    await asyncio.sleep(random.uniform(ms_min / 1000, ms_max / 1000))


async def _save_cookies(ctx: BrowserContext):
    os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
    cookies = await ctx.cookies()
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info(f"쿠키 저장 완료 ({len(cookies)}개)")


async def _load_cookies(ctx: BrowserContext, cookies_json: str = "") -> bool:
    """저장된 쿠키 또는 환경변수 쿠키 로드"""
    raw = None
    if cookies_json:
        try:
            raw = json.loads(cookies_json)
        except Exception:
            pass

    if raw is None and os.path.exists(COOKIE_PATH):
        with open(COOKIE_PATH, encoding="utf-8") as f:
            raw = json.load(f)

    if not raw:
        return False

    await ctx.add_cookies(raw)
    return True


async def _is_logged_in(page: Page) -> bool:
    await page.goto("https://www.naver.com", wait_until="domcontentloaded")
    await _delay(1000, 2000)
    # 로그인 상태면 내정보 버튼 존재
    return await page.locator("#account").count() > 0


async def _login(page: Page, naver_id: str, naver_pw: str) -> bool:
    logger.info("네이버 로그인 시도")
    await page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded")
    await _delay(1000, 2000)

    await page.locator("#id").fill(naver_id)
    await _delay(300, 600)
    await page.locator("#pw").fill(naver_pw)
    await _delay(400, 700)
    await page.locator(".btn_login").click()
    await _delay(3000, 5000)

    # 로그인 후 현재 URL 확인
    if "nid.naver.com" in page.url:
        logger.error(f"로그인 실패 또는 추가 인증 필요 (현재 URL: {page.url})")
        return False

    logger.info("로그인 성공")
    return True


async def _type_in_editor(page: Page, text: str):
    """SE3 에디터 본문 영역에 내용 입력"""
    # SE3 본문 영역 클릭 (여러 선택자 시도)
    selectors = [
        ".se-text-paragraph",
        "[data-se-type='text'] [contenteditable]",
        ".se-component-content",
    ]
    clicked = False
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click()
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        # 제목 다음 Tab키로 본문 이동
        await page.keyboard.press("Tab")

    await _delay(500, 800)

    # 단락별로 입력
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        lines = para.split("\n")
        for j, line in enumerate(lines):
            if line.strip():
                await page.keyboard.type(line.strip(), delay=15)
            if j < len(lines) - 1:
                await page.keyboard.press("Enter")
        if i < len(paragraphs) - 1:
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
        await _delay(200, 400)


async def _add_tags(page: Page, tags: list[str]):
    """태그 입력"""
    tag_selectors = [
        ".tag_input input",
        ".se-tag input",
        "[placeholder*='태그']",
    ]
    for sel in tag_selectors:
        try:
            tag_box = page.locator(sel).first
            if await tag_box.count() > 0:
                for tag in tags[:10]:
                    await tag_box.click()
                    await _delay(200, 400)
                    await tag_box.fill(tag)
                    await page.keyboard.press("Enter")
                    await _delay(300, 500)
                return
        except Exception:
            continue
    logger.warning("태그 입력 영역을 찾지 못함 — 태그 없이 진행")


async def _publish(page: Page) -> str | None:
    """발행 버튼 클릭 → 완료 URL 반환"""
    publish_selectors = [
        "button:has-text('발행')",
        ".publish_btn",
        "[data-gdl-area='bottom'] button:last-child",
    ]
    for sel in publish_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                await _delay(2000, 3000)
                break
        except Exception:
            continue

    # 발행 확인 팝업 처리
    confirm_selectors = [
        "button:has-text('확인')",
        "button:has-text('발행하기')",
        ".btn_confirm",
    ]
    for sel in confirm_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                await _delay(3000, 5000)
                break
        except Exception:
            continue

    final_url = page.url
    logger.info(f"발행 후 URL: {final_url}")
    return final_url if "PostView" in final_url or "blog.naver.com" in final_url else None


async def _post(
    naver_id: str,
    naver_pw: str,
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
        await _load_cookies(ctx, naver_cookies)

        # 로그인 상태 확인
        if not await _is_logged_in(page):
            if not naver_id or not naver_pw:
                logger.error("쿠키 만료, ID/PW도 없음 — 로그인 불가")
                await browser.close()
                return None
            if not await _login(page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)

        # 글쓰기 페이지 이동
        await page.goto(WRITE_URL, wait_until="networkidle")
        await _delay(3000, 5000)

        # 제목 입력
        title_sel = [
            ".se-title-text",
            "[placeholder='제목']",
            "[data-se-type='title'] [contenteditable]",
        ]
        for sel in title_sel:
            try:
                t = page.locator(sel).first
                if await t.count() > 0:
                    await t.click()
                    await _delay(300, 500)
                    await t.fill(title)
                    logger.info(f"제목 입력: {title}")
                    break
            except Exception:
                continue

        await _delay(500, 800)

        # 본문 입력
        await _type_in_editor(page, body)
        await _delay(1000, 1500)

        # 태그 입력
        await _add_tags(page, tags)
        await _delay(500, 800)

        # 발행
        post_url = await _publish(page)

        # 쿠키 갱신 저장
        await _save_cookies(ctx)
        await browser.close()

        if post_url:
            return {"post_url": post_url}
        logger.error("발행 URL 확인 실패")
        return None


def post_to_naver_blog(
    naver_id: str,
    naver_pw: str,
    title: str,
    body: str,
    tags: list[str],
    naver_cookies: str = "",
) -> dict | None:
    return asyncio.run(_post(naver_id, naver_pw, title, body, tags, naver_cookies))
