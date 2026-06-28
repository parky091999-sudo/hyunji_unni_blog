"""
Pexels API로 키워드 관련 이미지 URL 수집
image_keywords (content.py에서 생성된 7개 키워드) 사용 시 각 위치별 적합한 이미지 수집
"""
import logging
import re
import tempfile

import requests

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"


def generate_dish_image(dish: str, api_key: str) -> str | None:
    """레시피 대표 이미지를 AI로 생성(실제 한국 가정식 사진 톤). 성공 시 로컬 PNG 경로, 실패 시 None.
    Pexels는 한식 사진이 빈약해 대표컷이 어색하므로, 같은 GOOGLE_API_KEY로 이미지를 생성한다.
    Imagen → Gemini 이미지생성 순으로 시도하고, 둘 다 실패하면 None(상위에서 Pexels/카드 폴백)."""
    if not dish or not api_key:
        return None
    prompt = (
        f"A realistic, appetizing top-down food photograph of Korean home-style dish '{dish}', "
        f"served on a plate on a clean wooden table, natural soft daylight, cozy home kitchen mood, "
        f"high detail, no text, no people, no watermark."
    )

    def _save_png(data) -> str:
        import base64
        raw = base64.b64decode(data) if isinstance(data, str) else data
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(raw)
        tmp.close()
        return tmp.name

    # 현지씨(coupang) 파이프라인에서 검증된 방식: gemini-3.1-flash-image, response_modalities=['IMAGE'].
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        for model in ("gemini-3.1-flash-image", "gemini-2.5-flash-image"):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=gtypes.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.parts:
                    if getattr(part, "thought", False):
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        path = _save_png(inline.data)
                        logger.info(f"대표 이미지 AI 생성 성공({model}): {dish} -> {path}")
                        return path
            except Exception as e:
                logger.info(f"Gemini 이미지({model}) 생성 실패: {e.__class__.__name__}: {str(e)[:90]}")
    except Exception as e:
        logger.warning(f"AI 이미지 생성 모듈 오류(폴백 진행): {e}")

    logger.warning(f"대표 이미지 AI 생성 실패 — Pexels/카드로 폴백: {dish}")
    return None

# 카테고리/키워드 → 영문 검색어 매핑
_KO_TO_EN: list[tuple[re.Pattern, str]] = [
    # ── 건강·의학 ──────────────────────────────────────────────────
    (re.compile(r"탈모|두피|모발"), "hair care healthy scalp shampoo herbal no people"),
    (re.compile(r"철분|빈혈|헤모글로빈|페리틴"), "iron rich food spinach lentils dark greens no people"),
    (re.compile(r"호르몬|에스트로겐|갑상선|안드로겐"), "herbal wellness tea hormone health food no people"),
    (re.compile(r"단백질|아미노산|케라틴"), "eggs nuts beans protein food ingredients no people"),
    (re.compile(r"비타민|영양소|미네랄|영양제"), "colorful fresh vegetables vitamins supplements no people"),
    (re.compile(r"다이어트|체중|비만|살빼"), "healthy meal prep salad vegetables weight loss no people"),
    (re.compile(r"혈당|혈압|혈류|혈관"), "fresh berries vegetables heart health food no people"),
    (re.compile(r"장|유산균|프로바이오틱|장내"), "yogurt fermented kimchi gut health food no people"),
    (re.compile(r"피부|콜라겐|항산화|기미"), "fresh berries antioxidant fruits beautiful skin no people"),
    (re.compile(r"면역|항체|염증"), "lemon ginger honey immune boost drink no people"),
    (re.compile(r"뇌|인지|기억력|치매"), "omega fish walnuts brain health food no people"),
    (re.compile(r"뼈|칼슘|골다공증|관절"), "dairy milk calcium rich food bones no people"),
    (re.compile(r"심장|심혈관|동맥경화"), "heart healthy food salmon berries omega no people"),
    (re.compile(r"눈|시력|루테인|안구"), "colorful carrots blueberries eye health food no people"),
    (re.compile(r"스트레스|피로|수면|불면"), "calm relaxing herbal tea sleep wellness no people"),
    (re.compile(r"식단|영양|건강식"), "healthy balanced meal colorful vegetables no people"),
    (re.compile(r"운동|근육|근력|헬스"), "fitness exercise healthy lifestyle workout no people"),
    # ── 살림/생활 ──────────────────────────────────────────────────
    (re.compile(r"욕실|화장실|샤워"), "clean bathroom interior aesthetic no people"),
    (re.compile(r"주방|부엌|싱크대"), "cozy kitchen counter still life aesthetic no people"),
    (re.compile(r"세탁기|빨래"), "laundry room aesthetic details no people"),
    (re.compile(r"청소|정리|루틴"), "home interior organization aesthetic minimalist no people"),
    (re.compile(r"곰팡이|습기"), "bathroom tiles clean detail still life"),
    (re.compile(r"요리|레시피|밥|식단|냉파"), "korean food table setting cozy aesthetic no people"),
    (re.compile(r"도시락|아침\s*메뉴"), "bento box lunch box still life cozy"),
    (re.compile(r"식비\s*절약"), "cozy study desk notebook coffee still life"),
    (re.compile(r"인테리어|꾸미|홈\s*데코"), "cozy home interior aesthetic minimalist no people"),
    (re.compile(r"수납|정리함|선반"), "organized storage shelves aesthetic details no people"),
    (re.compile(r"옷장|드레스룸"), "organized closet wardrobe aesthetic minimalist no people"),
    (re.compile(r"냉장고"), "organized refrigerator shelves inside close up no people"),
    (re.compile(r"베란다|발코니"), "balcony terrace cozy plants aesthetic no people"),
    (re.compile(r"무드등|조명"), "cozy bedroom mood lighting aesthetic no people"),
    (re.compile(r"절약|생활비|가계부"), "cozy study desk piggy bank still life"),
    (re.compile(r"전기세|난방비|냉방비"), "cozy home warm lighting detail"),
    (re.compile(r"에어컨"), "air conditioner clean minimalist white no people"),
    (re.compile(r"다이소"), "cozy home organizer aesthetic design no people"),
    (re.compile(r"이케아"), "ikea home organization shelves aesthetic no people"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner minimalist home no people"),
    (re.compile(r"공기청정기"), "home air purifier close up minimalist no people"),
    (re.compile(r"필터|교체"), "clean home appliance minimalist details"),
    (re.compile(r"신혼|살림"), "cozy new home living room aesthetic no people"),
    (re.compile(r"자취|1인\s*가구"), "cozy small apartment interior aesthetic no people"),
    (re.compile(r"혼수|결혼\s*준비"), "cozy bridal room decoration aesthetic details"),
]
_DEFAULT_QUERY = "cozy Korean home interior aesthetic no people"

# 살림/생활 블로그에 '뜬금없는' 스톡사진 제외용 (alt 텍스트 기준)
# 달러사진, 인물, 자동차, 방독면, 스마트폰, 보석 등 뜬금없는 사물 차단
_OFFTOPIC_RE = re.compile(
    r"\b(money|dollar|cash|currency|coin|finance|financial|banking|invest|investment|"
    r"stock\s*market|business|office|meeting|conference|corporate|suit|handshake|"
    r"graph|chart|mountain|beach|forest|ocean|sunset|sky|desert|wildlife|animal|"
    r"abstract|texture|pattern|gradient|wedding\s*dress|model\s*pose|"
    r"person|people|man|woman|model|face|hand|finger|arm|leg|body|portrait|couple|family|"
    r"human|girl|boy|guy|lady|male|female|"
    # 유저 피드백 반영: 차량용 필터, 방독면, 스마트폰, 반지/액세서리 등 원천 배제
    r"car|auto|vehicle|automotive|engine|gas\s*mask|respirator|mask|phone|smartphone|mobile|ring|jewelry|necklace|bracelet|earring)\b",
    re.I,
)


def _keyword_to_en(keyword: str) -> str:
    """한국어 키워드를 Pexels 검색용 영어 쿼리로 변환"""
    # 영어가 이미 포함된 경우 그대로 사용
    query = keyword
    if not re.search(r"[a-zA-Z]{3,}", keyword):
        found = False
        for pattern, eng in _KO_TO_EN:
            if pattern.search(keyword):
                query = eng
                found = True
                break
        if not found:
            query = _DEFAULT_QUERY

    # 모든 쿼리에 대해 people-free 필터링 및 감성 톤 강화
    if "no people" not in query.lower() and "people" not in query.lower():
        query = f"{query} no people"
    if "aesthetic" not in query.lower():
        query = f"{query} aesthetic"

    # 레시피/요리 관련 영어 키워드에 대해 korean 묵시적 접두사 부여 (양식/스톡 사진 방지)
    food_kws = ["food", "dish", "cooking", "meal", "recipe", "stew", "soup", "vegetable", "kitchen"]
    if any(fw in query.lower() for fw in food_kws) and "korean" not in query.lower():
        query = f"korean {query}"

    return query


def _fetch_one_image(query: str, api_key: str, exclude_ids: set | None = None) -> dict | None:
    """단일 쿼리로 이미지 1장 수집 (중복 제외 + 관련성 필터로 뜬금없는 사진 제외)"""
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 12,  # 후보 넉넉히 받아 필터링
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        for p in photos:
            if exclude_ids and p["id"] in exclude_ids:
                continue
            cand = {
                "url": p["src"]["large"],
                "alt_text": query,
                "photographer": p.get("photographer", ""),
                "pexels_id": p["id"],
            }
            alt = p.get("alt") or ""
            if _OFFTOPIC_RE.search(alt):
                logger.info(f"관련성 필터: 뜬금없는 사진 제외 (alt={alt[:45]!r}, query={query!r})")
                continue
            return cand
        # 후보가 전부 off-topic(사람 노출 등)이면 억지로 첫 후보를 쓰지 않고 None 반환
        return None
    except Exception as e:
        logger.warning(f"Pexels 단일 수집 실패 (query={query!r}): {e}")
    return None


def get_post_images(
    keyword: str,
    api_key: str,
    count: int = 7,
    category: str = "",
    image_keywords: list[str] | None = None,
) -> list[dict]:
    """
    Pexels 이미지 수집.
    image_keywords (content.py에서 생성된 7개)가 있으면 각 키워드별로 1장씩 수집.
    없으면 기존 방식(키워드 → 영어 변환)으로 count장 수집.
    """
    if not api_key:
        logger.warning("PEXELS_API_KEY 없음 — 이미지 없이 진행")
        return []

    # image_keywords가 있으면 각 위치별 맞춤 이미지 수집
    if image_keywords and len(image_keywords) >= 1:
        results = []
        used_ids: set = set()
        for i, img_kw in enumerate(image_keywords[:count]):
            query = _keyword_to_en(img_kw)
            img = _fetch_one_image(query, api_key, exclude_ids=used_ids)
            if img:
                used_ids.add(img["pexels_id"])
                img["alt_text"] = img_kw  # 원본 키워드를 alt_text로 보존
                results.append(img)
            else:
                # fallback: 기본 키워드로 시도
                fallback_query = _keyword_to_en(keyword)
                img = _fetch_one_image(fallback_query, api_key, exclude_ids=used_ids)
                if img:
                    used_ids.add(img["pexels_id"])
                    img["alt_text"] = keyword
                    results.append(img)
        logger.info(f"Pexels 이미지 {len(results)}개 수집 (image_keywords 방식, {len(image_keywords)}개 키워드)")
        return results

    # 기존 방식: 단일 쿼리로 count장 수집
    search_keyword = keyword
    if category:
        cat_hints = {
            "신혼살림기초": "newlywed home",
            "청소정리": "cleaning organization",
            "요리식비": "cooking food",
            "절약재테크": "budget saving",
            "인테리어": "interior decor",
            "쇼핑정보": "home goods",
        }
        if category in cat_hints:
            search_keyword = f"{keyword} {cat_hints[category]}"

    query = _keyword_to_en(search_keyword)
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": count + 3,
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        results = []
        used_ids: set = set()
        for p in photos:
            if len(results) >= count:
                break
            if p["id"] not in used_ids:
                used_ids.add(p["id"])
                results.append({
                    "url": p["src"]["large"],
                    "alt_text": f"{keyword} 관련 이미지",
                    "photographer": p.get("photographer", ""),
                    "pexels_id": p["id"],
                })
        logger.info(f"Pexels 이미지 {len(results)}개 수집 (query={query!r})")
        return results
    except Exception as e:
        logger.warning(f"Pexels 수집 실패: {e}")
        return []


def fetch_image_urls(keyword: str, count: int = 4, api_key: str = "") -> list[str]:
    """기존 인터페이스 호환용 래퍼"""
    images = get_post_images(keyword=keyword, api_key=api_key, count=count)
    return [img["url"] for img in images]


def generate_health_infographic(title: str, subheadings: list[str], api_key: str) -> str | None:
    """건강 포스팅 요약 인포그래픽 AI 생성 (Gemini 이미지 생성 API).
    subheadings: 섹션 제목 목록 (최대 5개). 성공 시 로컬 PNG 경로, 실패 시 None."""
    if not api_key or not title:
        return None

    n = min(len(subheadings), 5)
    if n == 0:
        return None

    points = " / ".join([f"{i+1}. {sh}" for i, sh in enumerate(subheadings[:n])])
    prompt = (
        f"Create a vibrant Korean health infographic. "
        f"Main title in Korean: '{title}'. "
        f"Show exactly {n} health benefit sections with icons and Korean labels: {points}. "
        f"Design: light pastel background, {n} colorful numbered circular badges, "
        f"Korean text labels inside each badge, clean magazine-style layout, "
        f"no watermarks, no English brand logos. "
        f"Style: similar to Korean health blog summary card with numbered sections 1 to {n}."
    )

    def _save_png(data) -> str:
        import base64
        raw = base64.b64decode(data) if isinstance(data, str) else data
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(raw)
        tmp.close()
        return tmp.name

    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        for model in ("gemini-2.0-flash-preview-image-generation", "gemini-3.1-flash-image", "gemini-2.5-flash-image"):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=gtypes.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.parts:
                    if getattr(part, "thought", False):
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        path = _save_png(inline.data)
                        logger.info(f"인포그래픽 AI 생성 성공({model}): {title[:30]} → {path}")
                        return path
            except Exception as e:
                logger.info(f"인포그래픽 생성 실패({model}): {e.__class__.__name__}: {str(e)[:90]}")
    except Exception as e:
        logger.warning(f"인포그래픽 생성 모듈 오류: {e}")

    logger.warning(f"인포그래픽 AI 생성 실패 — PIL 폴백 없음: {title[:30]}")
    return None
