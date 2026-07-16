"""
형수의테크공장 본문 실사진 수집 — 상황별 스마트 캐스케이드.

1순위: 출처 뉴스 기사의 대표 이미지(og:image) — 그 뉴스의 실제 사진(가장 정확). '출처: 도메인' 캡션.
2순위: Pexels 스톡 — OG 없거나 부실하면 주제 키워드로 안전한 스톡.
실패 시: None (헤더 AI 카드만 유지).

※ 뉴스 이미지는 출처 표기해도 저작권 회색지대 — 캡션에 출처 명시로 최소화.
"""
import logging
import os
import re
import tempfile
import urllib.parse
import urllib.request
from html import unescape

logger = logging.getLogger("tech_image")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::secure_url)?["\'][^>]*'
    r'content=["\']([^"\']+)["\']', re.IGNORECASE)
_OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:image|twitter:image)["\']',
    re.IGNORECASE)


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _extract_og_url(page_html: str, base_url: str) -> str | None:
    for rgx in (_OG_RE, _OG_RE2):
        m = rgx.search(page_html)
        if m:
            u = unescape(m.group(1)).strip()
            if u.startswith("//"):
                u = "https:" + u
            elif u.startswith("/"):
                p = urllib.parse.urlparse(base_url)
                u = f"{p.scheme}://{p.netloc}{u}"
            if u.startswith("http"):
                return u
    return None


def _download(url: str, min_bytes: int = 12000) -> str | None:
    """이미지 다운로드 → PIL로 깨끗한 baseline RGB JPG로 재인코딩해 반환.

    ★뉴스 og:image가 CMYK·프로그레시브·ICC 프로파일 등을 지니면 네이버 SE 에디터가
    업로드해도 0장으로 무시하는 사례가 있어(2026-07-16 실측), 반드시 정규화한다.
    PIL이 못 여는 손상/HTML 응답은 여기서 걸러져 None → 다음 소스(캐스케이드)로.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "image" not in ctype:
                return None
            data = resp.read()
        if len(data) < min_bytes:
            logger.info(f"이미지 너무 작음({len(data)}B) — 로고 추정, 스킵")
            return None
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(data))
        im.load()
        # 아이콘·로고 배제(작은 정사각/저해상)
        if min(im.size) < 200:
            logger.info(f"이미지 해상도 낮음({im.size}) — 로고 추정, 스킵")
            return None
        if im.mode != "RGB":
            im = im.convert("RGB")
        # 과대 크기 축소(네이버 업로드 안정화)
        max_side = 1600
        if max(im.size) > max_side:
            r = max_side / max(im.size)
            im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        im.save(tmp.name, "JPEG", quality=88, optimize=True)  # baseline·RGB·메타제거
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.info(f"이미지 다운로드/정규화 실패(손상 추정 스킵): {str(e)[:70]}")
        return None


def _og_image_from_article(article_url: str) -> tuple[str, str] | None:
    """기사 URL → og:image 다운로드. (local_path, 출처도메인) 반환."""
    try:
        req = urllib.request.Request(article_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read(400_000).decode("utf-8", errors="ignore")
    except Exception as e:
        logger.info(f"기사 페이지 로드 실패: {str(e)[:60]}")
        return None
    og = _extract_og_url(html, article_url)
    if not og:
        return None
    path = _download(og)
    if not path:
        return None
    return path, _domain(article_url)


def get_tech_body_image(topic: dict, pexels_key: str = "") -> dict | None:
    """캐스케이드로 본문 실사진 1장 확보.
    반환: {"local_path"|"url", "label"(캡션), "source"} 또는 None.
    """
    # 1순위: 최신 뉴스 기사들의 og:image (위에서부터 성공하는 첫 장)
    for n in topic.get("news", [])[:5]:
        link = n.get("link") or ""
        if not link.startswith("http"):
            continue
        got = _og_image_from_article(link)
        if got:
            path, dom = got
            logger.info(f"본문 실사진: 뉴스 대표사진 확보 (출처 {dom})")
            return {"local_path": path, "label": f"출처: {dom}" if dom else "출처: 뉴스", "source": "og"}

    # 2순위: Pexels 스톡 (안전 폴백)
    if pexels_key:
        try:
            from generator.image import _fetch_one_image, _keyword_to_en
            q = _keyword_to_en(topic.get("seed", "technology")) or "technology gadget"
            img = _fetch_one_image(q, pexels_key)
            if img and img.get("url"):
                logger.info(f"본문 실사진: Pexels 스톡 폴백 ({q})")
                return {"url": img["url"], "label": "", "source": "pexels"}
        except Exception as e:
            logger.info(f"Pexels 폴백 실패: {str(e)[:60]}")

    logger.info("본문 실사진 없음 — 헤더 카드만 유지")
    return None
