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

ROOT        = os.path.dirname(os.path.dirname(__file__))
COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")
SHOT_DIR    = os.path.join(ROOT, "data", "screenshots")
WRITE_URL   = "https://blog.naver.com/PostWriteForm.naver"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def _delay(ms_min: int = 300, ms_max: int = 800):
    await asyncio.sleep(random.uniform(ms_min / 1000, ms_max / 1000))


async def _screenshot(page: Page, name: str):
    """디버그 스크린샷 저장"""
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
    """저장된 쿠키 또는 환경변수 쿠키 로드"""
    raw = None

    if cookies_json.strip():
        try:
            raw = json.loads(cookies_json.strip())
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
        logger.error("로드할 쿠키 없음")
        return False

    # Playwright add_cookies에 필요한 필드만 추출
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
    logger.info(f"쿠키 {len(clean)}개 로드 완료")
    return True


async def _is_logged_in(page: Page) -> bool:
    """NID_AUT 쿠키 존재 여부로 로그인 체크 (URL 이동 없음)"""
    cookies = await page.context.cookies()
    names = {c["name"] for c in cookies}
    logged = "NID_AUT" in names
    logger.info(f"로그인 체크: {'OK' if logged else 'FAIL'} (쿠키: {sorted(names)[:5]}...)")
    return logged


async def _login(page: Page, naver_id: str, naver_pw: str) -> bool:
    logger.info("네이버 로그인 시도")
    await page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded")
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


async def _type_in_editor(page: Page, text: str):
    """SE3 에디터 본문 영역에 내용 입력"""
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
                logger.info(f"에디터 클릭: {sel}")
                break
        except Exception:
            continue

    if not clicked:
        await page.keyboard.press("Tab")

    await _delay(500, 800)

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
        await _delay(100, 200)


async def _add_tags(page: Page, tags: list[str]):
    tag_selectors = [
        ".tag_input input",
        ".se-tag input",
        "[placeholder*='태그']",
        "input[class*='tag']",
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
                logger.info(f"태그 {len(tags)}개 입력 완료")
                return
        except Exception:
            continue
    logger.warning("태그 입력 영역을 찾지 못함 - 태그 없이 진행")


async def _publish(page: Page) -> str | None:
    await _screenshot(page, "before_publish")

    publish_selectors = [
        "button:has-text('발행')",
        ".publish_btn",
        "[data-gdl-area='bottom'] button:last-child",
        "button.confirm",
    ]
    clicked = False
    for sel in publish_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                logger.info(f"발행 버튼 클릭: {sel}")
                await btn.click()
                await _delay(2000, 3000)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        logger.error("발행 버튼을 찾지 못함")
        await _screenshot(page, "publish_btn_not_found")
        return None

    # 발행 확인 팝업
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
    await _screenshot(page, "after_publish")

    if "about:blank" in final_url or final_url == "":
        return None
    return final_url


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
        cookies_ok = await _load_cookies(ctx, naver_cookies)

        # 로그인 상태 확인
        if not cookies_ok or not await _is_logged_in(page):
            logger.info("쿠키 없음 또는 미인증 - ID/PW 로그인 시도")
            if not naver_id or not naver_pw:
                logger.error("ID/PW 없음 - 로그인 불가")
                await browser.close()
                return None
            if not await _login(page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)

        # 쓰기 페이지
        logger.info(f"쓰기 페이지 이동: {WRITE_URL}")
        await page.goto(WRITE_URL, wait_until="networkidle", timeout=30000)
        await _delay(3000, 5000)
        await _screenshot(page, "write_page")
        logger.info(f"현재 URL: {page.url}")

        # 제목 입력
        title_sels = [
            ".se-title-text",
            "[placeholder='제목']",
            "[data-se-type='title'] [contenteditable]",
        ]
        for sel in title_sels:
            try:
                t = page.locator(sel).first
                if await t.count() > 0:
                    await t.click()
                    await _delay(300, 500)
                    await t.fill(title)
                    logger.info(f"제목 입력 완료: {title[:30]}")
                    break
            except Exception:
                continue

        await _delay(500, 800)
        await _type_in_editor(page, body)
        await _delay(1000, 1500)
        await _add_tags(page, tags)
        await _delay(500, 800)

        post_url = await _publish(page)
        await _save_cookies(ctx)
        await browser.close()

        if post_url:
            return {"post_url": post_url}
        logger.error("발행 실패")
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
