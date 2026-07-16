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

# ★신뢰 언론사/IT매체 도메인 화이트리스트 — og:image는 '이 목록 기사'에서만 사용한다.
# 목록 외(연예·라이프스타일 매체, 개인블로그, SNS, 인플루언서 등)는 남의 개인사진·아동 사진·
# 저작권 회색지대 이미지를 대표로 긁어오는 사고가 있어(2026-07-16 실측: 연예뉴스가 인플루언서
# 인스타 사진을 og로 제공) og를 쓰지 않고 Pexels 스톡으로 폴백한다.
_TRUSTED_NEWS_DOMAINS = (
    # 통신·종합일간
    "yna.co.kr", "yonhapnews", "newsis.com", "news1.kr",
    "chosun.com", "donga.com", "joongang.co.kr", "joins.com", "hani.co.kr",
    "khan.co.kr", "seoul.co.kr", "kmib.co.kr", "munhwa.com", "segye.com",
    "hankookilbo.com", "kyunghyang.com",
    # 경제
    "mk.co.kr", "hankyung.com", "mt.co.kr", "sedaily.com", "edaily.co.kr",
    "fnnews.com", "asiae.co.kr", "etoday.co.kr", "heraldcorp.com", "newspim.com",
    "ajunews.com", "biz.chosun.com", "wowtv.co.kr",
    # 방송
    "ytn.co.kr", "kbs.co.kr", "imbc.com", "sbs.co.kr", "jtbc.co.kr",
    # IT·테크·과학 전문
    "etnews.com", "zdnet.co.kr", "bloter.net", "ddaily.co.kr", "dt.co.kr",
    "inews24.com", "itchosun.com", "betanews.net", "aitimes.com", "aitimes.kr",
    "thelec.kr", "kbench.com", "itworld.co.kr", "ciokorea.com", "boannews.com",
    "dongascience.com", "hellot.net",
)
# og:image URL 자체가 이 호스트면 차단(SNS·개인블로그 이미지 CDN — 화이트리스트 통과 기사라도 방어)
_BLOCKED_IMG_HOSTS = (
    "cdninstagram", "fbcdn.net", "instagram.com", "postfiles.pstatic",
    "blogfiles.naver", "pinimg.com", "ytimg.com", "tiktokcdn", "twimg.com",
)


def _is_trusted_news(url: str) -> bool:
    dom = _domain(url)
    return any(t in dom for t in _TRUSTED_NEWS_DOMAINS)


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
    """기사 URL → og:image 다운로드. (local_path, 출처도메인) 반환.
    ★신뢰 언론사 화이트리스트 기사만 허용 + og 이미지 URL이 SNS/개인 CDN이면 차단(개인사진 방어)."""
    if not _is_trusted_news(article_url):
        logger.info(f"비신뢰 도메인({_domain(article_url)}) — og 스킵, Pexels 폴백")
        return None
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
    og_host = _domain(og)
    if any(b in og_host for b in _BLOCKED_IMG_HOSTS):
        logger.info(f"og 이미지 호스트 차단({og_host}) — SNS/개인 CDN 추정, 스킵")
        return None
    path = _download(og)
    if not path:
        return None
    return path, _domain(article_url)


def _pexels_query(seed: str) -> str:
    """테크 seed → 주제 관련 Pexels 영어 쿼리(사람 배제는 image._fetch_one_image가 처리).
    _keyword_to_en이 테크 용어를 엉뚱한 쿼리(실내/화분 등)로 매핑하던 문제 보정(2026-07-16)."""
    s = seed or ""
    # ★사물 중심(플랫레이/제품컷) 쿼리 — 인물/손이 들어간 컷은 image._OFFTOPIC_RE가 걸러 폴백되므로
    #   물체만 나오는 스톡이 잡히도록 flat lay/on desk/still life 등을 붙인다(2026-07-16).
    groups = [
        (("아이폰", "갤럭시", "픽셀", "스마트폰", "에어팟", "버즈", "이어폰", "워치", "AI 스마트폰"),
         "smartphone flat lay on desk still life"),
        (("노트북", "맥북", "RTX", "그래픽카드", "게이밍", "모니터", "PC", "부품"),
         "laptop computer on wooden desk still life"),
        (("로봇청소기", "에어프라이어", "TV", "청소기", "공기청정기", "제습기", "정수기", "가전", "냉장고", "세탁기"),
         "modern home appliance product still life"),
        (("아이오닉", "기아", "테슬라", "전기차", "EV", "자동차", "모빌리티", "충전"),
         "electric car charging station empty"),
        (("챗GPT", "AI", "인공지능", "챗봇"),
         "circuit board technology abstract closeup"),
    ]
    for keys, q in groups:
        if any(k in s for k in keys):
            return q
    return "technology gadget device"


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
            # 캡션에 콜론(:)을 넣지 않음 — 스크린샷 파일명(alt_text 사용)에 콜론이 섞여
            # 아티팩트 업로드가 실패하던 문제(2026-07-16) 회피. 캡션 자체도 콜론 없이 자연스럽다.
            return {"local_path": path, "label": f"출처 {dom}" if dom else "출처 뉴스", "source": "og"}

    # 2순위: Pexels 스톡 (안전 폴백) — seed를 테크 카테고리 영어 쿼리로 매핑해 주제 관련성 확보
    if pexels_key:
        try:
            from generator.image import _fetch_one_image
            q = _pexels_query(topic.get("seed", ""))
            img = _fetch_one_image(q, pexels_key)
            if img and img.get("url"):
                logger.info(f"본문 실사진: Pexels 스톡 폴백 ({q})")
                return {"url": img["url"], "label": "", "source": "pexels"}
        except Exception as e:
            logger.info(f"Pexels 폴백 실패: {str(e)[:60]}")

    logger.info("본문 실사진 없음 — 헤더 카드만 유지")
    return None
