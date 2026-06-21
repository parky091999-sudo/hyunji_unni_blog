"""
Playwright로 네이버 블로그 자동 포스팅
SE3/SE4 에디터 기반 — 쿠키 세션 재사용으로 로그인 최소화
"""
import asyncio
import json
import logging
import os
import random

from playwright.async_api import async_playwright, Page, BrowserContext, Frame

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
        logger.error("로드할 쿠키 없음")
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
    logger.info(f"쿠키 {len(clean)}개 로드 완료")
    return True


async def _is_logged_in(page: Page) -> bool:
    """NID_AUT 쿠키 존재 여부로 1차 로그인 체크"""
    cookies = await page.context.cookies()
    names = {c["name"] for c in cookies}
    logged = "NID_AUT" in names
    logger.info(f"로그인 체크(쿠키): {'OK' if logged else 'FAIL'} (쿠키: {sorted(names)[:8]})")
    return logged


async def _verify_session(page: Page) -> bool:
    """네이버 메인 접속으로 실제 세션 유효성 확인"""
    try:
        await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=20000)
        await _delay(2000, 3000)
        await _screenshot(page, "session_verify")
        # 로그아웃 상태면 로그인 버튼이 보임
        login_link_count = await page.locator(
            "a.link_login, a[href*='nidlogin'], .gnb_login_area a"
        ).count()
        # 로그인 상태면 사용자 아이디/메뉴가 보임
        logged_in_indicator = await page.locator(
            ".gnb_my_area, .MyView-module, [class*='MyMenu'], .link_logout"
        ).count()
        logger.info(
            f"세션 검증 — 로그인버튼: {login_link_count}, 로그인표시: {logged_in_indicator}, URL: {page.url}"
        )
        # BlogHome 리다이렉트 = 로그인 상태
        if "BlogHome" in page.url or logged_in_indicator > 0:
            return True
        if login_link_count > 0 and logged_in_indicator == 0:
            logger.warning("네이버 메인에서 로그아웃 상태 감지 — 세션 만료")
            return False
        return True  # 확실하지 않으면 로그인 상태로 간주
    except Exception as e:
        logger.warning(f"세션 검증 실패: {e}")
        return True  # 오류 시 로그인 상태로 간주 (과도한 재시도 방지)


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


def _looks_like_write_page(url: str) -> bool:
    """URL이 글쓰기 에디터 페이지인지 판별"""
    if not url or "about:blank" in url:
        return False
    bad = ["BlogHome.naver", "nid.naver.com", "section.blog.naver.com"]
    if any(b in url for b in bad):
        return False
    good = [
        "postwrite", "PostWrite", "editor", "/write", "editForm",
        "Redirect=Write", "GoBlogWrite",  # 네이버 현재 글쓰기 리다이렉트 패턴
    ]
    return any(g in url for g in good)


async def _navigate_to_write_page(page: Page, naver_id: str, blog_id: str) -> bool:
    """글쓰기 에디터 페이지 진입 — 세 가지 방법 순차 시도"""

    # 방법 1: 알려진 글쓰기 URL 직접 이동
    ids_to_try = list(dict.fromkeys(filter(None, [blog_id, naver_id])))
    write_url_candidates = (
        ["https://blog.naver.com/GoBlogWrite.naver"]  # 현행 글쓰기 진입점
        + [f"https://blog.naver.com/{bid}/postwrite" for bid in ids_to_try]
    )
    for url in write_url_candidates:
        logger.info(f"[방법1] 이동: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await _delay(2000, 3000)
            cur = page.url
            await _screenshot(page, "try1_write")
            logger.info(f"결과 URL: {cur}")
            if _looks_like_write_page(cur):
                logger.info(f"방법1 성공: {cur}")
                return True
            # URL로 판단 어렵다면 에디터 요소 존재 여부 확인
            editor_count = await page.locator(
                "div[contenteditable='true'], .se-title-text, .se-main-container"
            ).count()
            if editor_count > 0:
                logger.info(f"방법1 성공 (에디터 요소 {editor_count}개 감지): {cur}")
                return True
        except Exception as e:
            logger.warning(f"방법1 실패 ({url}): {e}")

    # 방법 2: 블로그 홈 → 글쓰기 버튼 클릭
    home_id = blog_id or naver_id
    logger.info(f"[방법2] 블로그 홈 진입: {home_id}")
    try:
        await page.goto(f"https://blog.naver.com/{home_id}", wait_until="domcontentloaded", timeout=25000)
        await _delay(2000, 3000)
        await _screenshot(page, "try2_blog_home")
        logger.info(f"블로그 홈 URL: {page.url}")

        write_btn_sels = [
            ".btn_write",
            "a.write_btn",
            "a:has-text('글쓰기')",
            "button:has-text('글쓰기')",
            "[href*='postwrite']",
            "[href*='PostWriteForm']",
        ]
        for sel in write_btn_sels:
            try:
                el = page.locator(sel).first
                if not await el.count():
                    continue

                href = await el.get_attribute("href") or ""
                logger.info(f"글쓰기 버튼 발견: {sel} | href={href!r}")

                # href가 직접 이동 가능한 URL이면 goto 사용 (networkidle로 리다이렉트 체인 따라감)
                if href and href not in ("#", "") and "javascript:" not in href.lower():
                    goto_url = href if href.startswith("http") else f"https://blog.naver.com{href}"
                    logger.info(f"글쓰기 href 직접 이동: {goto_url}")
                    await page.goto(goto_url, wait_until="networkidle", timeout=35000)
                    await _delay(2000, 3000)
                    await _screenshot(page, "try2_href_nav")
                    cur = page.url
                    logger.info(f"href 이동 후 URL: {cur}")
                    if _looks_like_write_page(cur):
                        return True
                    # 에디터 요소로도 확인
                    ed_count = await page.locator(
                        "div[contenteditable='true'], .se-title-text, .se-main-container"
                    ).count()
                    if ed_count > 0:
                        logger.info(f"href 이동 성공 (에디터 요소 {ed_count}개): {cur}")
                        return True

                # 클릭 — 새 탭 열릴 경우 expect_page로 캡처
                try:
                    async with page.context.expect_page(timeout=6000) as new_page_info:
                        await el.click()
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                    target_url = new_page.url
                    logger.info(f"새 탭 열림: {target_url}")
                    await _screenshot(new_page, "try2_new_tab")
                    await new_page.close()
                    if _looks_like_write_page(target_url):
                        await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                        await _delay(2000, 3000)
                        await _screenshot(page, "try2_write_page")
                        return True
                except Exception:
                    # 새 탭 없음 — 현재 페이지 URL 확인
                    await _delay(3000, 4000)
                    cur = page.url
                    logger.info(f"글쓰기 클릭 후 URL: {cur}")
                    await _screenshot(page, "try2_after_click")
                    if _looks_like_write_page(cur):
                        return True
                break
            except Exception as e:
                logger.debug(f"셀렉터 {sel}: {e}")
    except Exception as e:
        logger.warning(f"방법2 실패: {e}")

    # 방법 3: 구형 PostWriteForm (최후 수단) - 여러 파라미터 조합
    for bid in ids_to_try:
        for params in [f"blogId={bid}", f"blogId={bid}&postNo=0", f"blogId={bid}&from=blog"]:
            url = f"https://blog.naver.com/PostWriteForm.naver?{params}"
            logger.info(f"[방법3] 레거시: {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await _delay(3000, 5000)
                cur = page.url
                await _screenshot(page, f"try3_{bid}")
                logger.info(f"레거시 결과: {cur}")
                if _looks_like_write_page(cur):
                    logger.info("방법3 성공")
                    return True
            except Exception as e:
                logger.warning(f"방법3 실패: {e}")

    logger.error("모든 방법으로 글쓰기 페이지 진입 실패")
    return False


async def _get_editor_frame(page: Page):
    """에디터 frame 반환 — iframe 내부 또는 메인 페이지"""
    await _delay(500, 1000)
    # 에디터 관련 frame URL 패턴 우선
    for frame in page.frames:
        url = frame.url or ""
        if any(kw in url for kw in ["editor", "se.naver", "postwrite", "editForm"]):
            logger.info(f"에디터 frame 발견 (URL): {url}")
            return frame
    # contenteditable 있는 frame 탐색
    for frame in page.frames:
        try:
            count = await frame.locator("div[contenteditable='true']").count()
            if count > 0:
                logger.info(f"에디터 frame 발견 (contenteditable): {frame.url}")
                return frame
        except Exception:
            continue
    return page


async def _fill_title(page: Page, title: str):
    """제목 입력 — SE4 에디터 기준 확인된 셀렉터 우선"""
    target = await _get_editor_frame(page)
    title_sels = [
        # SE4 신형 에디터 (확인된 셀렉터)
        "div[contenteditable='true'][data-placeholder='제목']",
        # 구형 SE3 셀렉터
        ".se-title-text",
        "[data-se-type='title'] [contenteditable]",
        # 기타 폴백
        ".title_input",
        "input[name='title']",
        "[placeholder='제목']",
    ]
    for sel in title_sels:
        try:
            t = target.locator(sel).first
            if await t.count():
                await t.click()
                await _delay(300, 500)
                # contenteditable은 Ctrl+A → 타이핑으로 입력
                await target.keyboard.press("Control+a")
                await target.keyboard.type(title, delay=20)
                logger.info(f"제목 입력 완료 ({sel}): {title[:40]}")
                return
        except Exception:
            continue
    logger.warning("제목 입력 영역을 찾지 못함")


async def _type_in_editor(page: Page, text: str):
    """본문 영역에 내용 입력 — SE4 확인된 셀렉터 우선"""
    target = await _get_editor_frame(page)

    body_sels = [
        # SE4 신형: 제목이 아닌 contenteditable (확인된 패턴)
        "div[contenteditable='true']:not([data-placeholder='제목'])",
        # SE3 구형
        ".se-text-paragraph",
        "[data-se-type='text'] [contenteditable]",
        ".se-component-content",
        ".se-main-container",
        # 최후 폴백
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
        await target.keyboard.press("Tab")

    await _delay(500, 800)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        lines = para.split("\n")
        for j, line in enumerate(lines):
            if line.strip():
                await target.keyboard.type(line.strip(), delay=15)
            if j < len(lines) - 1:
                await target.keyboard.press("Enter")
        if i < len(paragraphs) - 1:
            await target.keyboard.press("Enter")
            await target.keyboard.press("Enter")
        await _delay(100, 200)


async def _add_tags(page: Page, tags: list[str]):
    target = await _get_editor_frame(page)
    tag_selectors = [
        ".tag_input input",
        ".se-tag input",
        "[placeholder*='태그']",
        "input[class*='tag']",
        ".HashTagArea input",
    ]
    for sel in tag_selectors:
        try:
            tag_box = target.locator(sel).first
            if await tag_box.count():
                for tag in tags[:10]:
                    await tag_box.click()
                    await _delay(200, 400)
                    await tag_box.fill(tag)
                    await target.keyboard.press("Enter")
                    await _delay(300, 500)
                logger.info(f"태그 {len(tags)}개 입력 완료")
                return
        except Exception:
            continue
    logger.warning("태그 입력 영역 없음 — 태그 생략")


async def _publish(page: Page) -> str | None:
    await _screenshot(page, "before_publish")
    target = await _get_editor_frame(page)

    publish_selectors = [
        "button:has-text('발행')",
        ".publish_btn",
        "button:has-text('게시')",
        "[data-gdl-area='bottom'] button:last-child",
        "button.confirm",
        ".btn_submit",
    ]
    clicked = False
    for sel in publish_selectors:
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

    if "about:blank" in final_url or not final_url:
        return None
    return final_url


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

        # 로그인 상태 확인 (쿠키 → 실제 세션 검증 → ID/PW 로그인 순)
        needs_login = False
        if not cookies_ok or not await _is_logged_in(page):
            needs_login = True
        else:
            # 쿠키가 있어도 실제 세션이 만료됐을 수 있으므로 검증
            if not await _verify_session(page):
                logger.info("세션 만료 확인 — ID/PW 재로그인")
                needs_login = True

        if needs_login:
            logger.info("ID/PW 로그인 시도")
            if not naver_id or not naver_pw:
                logger.error("ID/PW 없음 - 로그인 불가")
                await browser.close()
                return None
            if not await _login(page, naver_id, naver_pw):
                await browser.close()
                return None
            await _save_cookies(ctx)

        # 글쓰기 페이지 진입
        if not await _navigate_to_write_page(page, naver_id, blog_id):
            logger.error("글쓰기 페이지 진입 실패 — 종료")
            await browser.close()
            return None

        logger.info(f"글쓰기 에디터 진입 성공: {page.url}")
        await _delay(2000, 3000)
        await _screenshot(page, "editor_ready")

        # 제목 입력
        await _fill_title(page, title)
        await _delay(500, 800)

        # 본문 입력
        await _type_in_editor(page, body)
        await _delay(1000, 1500)

        # 태그 입력
        await _add_tags(page, tags)
        await _delay(500, 800)

        # 발행
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
    blog_id: str,
    title: str,
    body: str,
    tags: list[str],
    naver_cookies: str = "",
) -> dict | None:
    return asyncio.run(_post(naver_id, naver_pw, blog_id, title, body, tags, naver_cookies))
