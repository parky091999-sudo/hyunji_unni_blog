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
    # 확대분(2026-07-17 — 실사진 확보율 개선, 검증된 IT·종합 매체만)
    "digitaltoday.co.kr", "techm.kr", "byline.network", "nocutnews.co.kr", "mtn.co.kr",
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


def _person_dominant(path: str) -> bool:
    """Gemini Vision으로 '인물 중심 컷' 판별 — 신뢰 언론사 사진이어도 연예인·모델 홍보컷이면
    초상권 리스크(2026-07-16 실측: 언팩 홍보컷의 아이돌 얼굴이 헤더카드 대표사진으로 실림).
    YES면 사용 안 함. 판별 API 실패 시 기존 동작 유지(False)."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return False
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        img = open(path, "rb").read()
        resp = client.models.generate_content(
            model="gemini-2.5-flash",  # content.py 텍스트 체인과 동일 모델(무료 한도 공유)
            contents=[gtypes.Part.from_bytes(data=img, mime_type="image/jpeg"),
                      "이 사진에서 사람(얼굴이나 상반신)이 화면의 주요 피사체인가? "
                      "제품·기기만 있거나 사람이 배경의 작은 요소면 NO. 답은 YES 또는 NO 한 단어만."],
        )
        verdict = (resp.text or "").strip().upper().startswith("YES")
        if verdict:
            logger.info("인물 중심 컷 감지 — 초상 리스크로 사용 안 함")
        return verdict
    except Exception as e:
        logger.info(f"인물 판별 생략({e.__class__.__name__}: {str(e)[:50]})")
        return False


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


def _seed_relevant(path: str, seed: str) -> bool:
    """Gemini 비전으로 사진-주제 관련성 검증 (2026-07-19 폴드8 실사고: 삼성 글 본문에
    아이폰 og 이미지, 헤더 배경에 스피커 사진). 언론사 og도 기사 대표컷이 generic 그래픽·
    경쟁 브랜드인 경우가 있어 도메인 신뢰만으론 부족. API 실패 시 True(기존 동작 유지)."""
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")).strip()
    if not api_key or not seed:
        return True
    try:
        import mimetypes
        from google import genai
        from google.genai import types
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        client = genai.Client(api_key=api_key)
        img = types.Part.from_bytes(data=open(path, "rb").read(), mime_type=mime)
        r = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[img,
                      f"이 사진이 '{seed}' 주제의 테크 블로그 글에 어울리는가? "
                      "판정 기준: ①경쟁 브랜드 제품이 주인공이면 NO(예: 삼성 갤럭시 글에 아이폰이 "
                      "메인으로 보이는 사진) ②주제와 무관한 물건이 주인공이면 NO(예: 스마트폰 글에 "
                      "스피커·조명·주방용품) ③주제 제품 자체, 같은 카테고리의 일반 제품컷, 관련 현장·"
                      "행사 사진이면 YES. 대답은 YES 또는 NO 한 단어만."])
        ans = (getattr(r, "text", "") or "").strip().upper()
        if ans.startswith("NO"):
            logger.info(f"사진-주제 불일치로 제외 (seed={seed!r})")
            return False
        return True
    except Exception as e:
        logger.info(f"사진 관련성 검증 스킵({str(e)[:50]}) — 통과 처리")
        return True


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
            if _person_dominant(path):
                continue
            if not _seed_relevant(path, topic.get("seed", "")):
                continue
            logger.info(f"본문 실사진: 뉴스 대표사진 확보 (출처 {dom})")
            # 캡션에 콜론(:)을 넣지 않음 — 스크린샷 파일명(alt_text 사용)에 콜론이 섞여
            # 아티팩트 업로드가 실패하던 문제(2026-07-16) 회피. 캡션 자체도 콜론 없이 자연스럽다.
            return {"local_path": path, "label": f"출처 {dom}" if dom else "출처 뉴스", "source": "og"}

    # Pexels 폴백 제거(2026-07-16 사용자 피드백): 배터리 글에 주방 주전자 스톡이 붙는 등
    # '엉뚱한 이미지'가 글 신뢰를 깎음 — 무관 사진보다 무사진이 낫다. 신뢰 언론사 og만 사용.
    logger.info("본문 실사진 없음 — 헤더 카드만 유지")
    return None


def _naver_shopping_photos(query: str, want: int = 2) -> list[dict]:
    """네이버쇼핑 상품 실사진 — 판매 제품의 정확·적법한 실사(전략 문서의 원안, 2026-07-17 연결).
    뉴스 og가 부족할 때의 2순위. NAVER_CLIENT_ID/SECRET 필요(없으면 빈 리스트)."""
    import json as _json
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    sec = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and sec) or not query.strip():
        return []
    out: list[dict] = []
    try:
        url = ("https://openapi.naver.com/v1/search/shop.json?query="
               + urllib.parse.quote(query) + "&display=10&sort=sim")
        req = urllib.request.Request(url, headers={
            "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec, "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            items = _json.loads(resp.read().decode("utf-8")).get("items", [])
        for it in items:
            if len(out) >= want:
                break
            img = (it.get("image") or "").strip()
            if not img.startswith("http"):
                continue
            path = _download(img, min_bytes=8000)
            if not path:
                continue
            out.append({"local_path": path, "label": "출처 네이버쇼핑", "source": "shop"})
        logger.info(f"쇼핑 실사진 확보: {len(out)}장 (쿼리 {query!r})")
    except Exception as e:
        logger.info(f"쇼핑 실사진 실패(무시): {str(e)[:60]}")
    return out


def get_tech_photos(topic: dict, pexels_key: str = "", want: int = 3) -> list[dict]:
    """대표+섹션용 실사진을 여러 장 확보(테크티노처럼 섹션마다 사진).
    1순위 신뢰 언론사 og → 2순위 네이버쇼핑 상품 실사(판매 제품 시드일 때).
    Pexels·AI 일러스트는 사용 안 함(2026-07-16/17 사용자 피드백: 무관 스톡도, AI 티 나는
    이미지도 테크 톤을 깎음 — 실사진 없으면 무사진이 낫다).
    반환: [{"local_path", "label", "source"}, ...] (0~want장)."""
    photos: list[dict] = []
    used_domains: set[str] = set()
    for n in topic.get("news", [])[:8]:
        if len(photos) >= want:
            break
        link = n.get("link") or ""
        if not link.startswith("http"):
            continue
        dom = _domain(link)
        if dom in used_domains:  # 같은 매체 중복 컷 방지
            continue
        got = _og_image_from_article(link)  # 신뢰언론사 화이트리스트+블록호스트 검증은 내부에서
        if got:
            path, d = got
            if _person_dominant(path):  # 연예인·모델 홍보컷 초상 리스크 차단
                continue
            if not _seed_relevant(path, topic.get("seed", "")):  # 경쟁브랜드·무관물건 컷 차단
                continue
            used_domains.add(d)
            photos.append({"local_path": path, "label": f"출처 {d}" if d else "출처 뉴스", "source": "og"})

    # 2순위: 네이버쇼핑 실사 — 판매 제품 시드만(서비스성 시드는 무관 상품이 잡혀 오히려 해로움)
    if len(photos) < want:
        try:
            from generator.tech_content import SEED_CATEGORY
            seed = topic.get("seed", "")
            if seed and SEED_CATEGORY.get(seed, "") != "AI·IT":
                photos += _naver_shopping_photos(seed, want=want - len(photos))
        except Exception:
            pass
    logger.info(f"실사진 확보 합계: {len(photos)}장 (og+쇼핑, 인물컷 제외)")
    return photos
