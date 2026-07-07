"""
워드프레스 REST API 발행 어댑터 (WP_PIPELINE.md §5 B단계).

render_wordpress_post() 산출 번들 → WP 글 발행(초안/공개).
- 인증: Application Password(Basic Auth). config: WP_URL / WP_USER / WP_APP_PW.
- 카테고리·태그는 이름 → term id 해석(없으면 생성).
- 네이버(Playwright)와 달리 브라우저 불필요 — 순수 REST.

전제: WP 관리자 계정의 Application Password. HTTPS 필수(평문 Basic 금지).
"""
import base64
import logging

import requests

from config import WP_URL, WP_USER, WP_APP_PW

logger = logging.getLogger("wp_publish")
_TIMEOUT = 30


def _base() -> str:
    return WP_URL.rstrip("/")


def _api(path: str) -> str:
    return f"{_base()}/wp-json/wp/v2/{path.lstrip('/')}"


def _headers() -> dict:
    # Application Password는 공백 포함 표기돼도 그대로 사용 가능(서버가 정규화).
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _configured() -> bool:
    if not (WP_URL and WP_USER and WP_APP_PW):
        logger.error("WP 설정 누락 — WP_URL/WP_USER/WP_APP_PW(.env 또는 GH Secret) 확인")
        return False
    return True


def _resolve_term(kind: str, name: str) -> int | None:
    """kind='categories'|'tags', 이름 → term id(없으면 생성)."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        r = requests.get(_api(kind), params={"search": name, "per_page": 100},
                         headers=_headers(), timeout=_TIMEOUT)
        if r.ok:
            for t in r.json():
                if str(t.get("name", "")).strip().lower() == name.lower():
                    return t["id"]
        r = requests.post(_api(kind), json={"name": name}, headers=_headers(), timeout=_TIMEOUT)
        if r.status_code in (200, 201):
            return r.json()["id"]
        # 이미 존재하면 에러 payload에 기존 id가 담겨온다
        data = r.json()
        if data.get("code") == "term_exists":
            return int(data["data"]["term_id"])
        logger.warning(f"{kind} '{name}' 해석 실패 {r.status_code}: {r.text[:150]}")
    except Exception as e:
        logger.warning(f"{kind} '{name}' 해석 예외: {e}")
    return None


def publish_wordpress(rendered: dict, title: str, *, status: str = "draft",
                      category: str = "", include_schema: bool = True) -> dict | None:
    """렌더 번들 → WP 발행.

    rendered: render_wordpress_post() 반환(content_html/excerpt/slug/tags/schema_jsonld).
    title   : 글 제목(전체 — render의 seo_title은 60자 절삭이라 별도로 받는다).
    status  : 'draft'(기본, 스팟체크) | 'publish' | 'future' 등.
    반환    : {id, link, status} 또는 None.
    """
    if not _configured():
        return None

    content = rendered.get("content_html") or rendered.get("html") or ""
    if include_schema and rendered.get("schema_jsonld"):
        content = content + "\n" + rendered["schema_jsonld"]

    payload: dict = {
        "title": (title or rendered.get("seo_title") or "").strip(),
        "content": content,
        "status": status,
        "excerpt": rendered.get("excerpt", ""),
    }
    if rendered.get("slug"):
        payload["slug"] = rendered["slug"]

    if category:
        cid = _resolve_term("categories", category)
        if cid:
            payload["categories"] = [cid]

    tag_ids = [tid for tid in (_resolve_term("tags", n) for n in (rendered.get("tags") or [])) if tid]
    if tag_ids:
        payload["tags"] = tag_ids

    try:
        r = requests.post(_api("posts"), json=payload, headers=_headers(), timeout=_TIMEOUT)
    except Exception as e:
        logger.error(f"발행 요청 실패: {e}")
        return None

    if r.status_code in (200, 201):
        d = r.json()
        logger.info(f"발행 완료 [{d.get('status')}] id={d.get('id')} {d.get('link')}")
        return {"id": d.get("id"), "link": d.get("link"), "status": d.get("status")}

    logger.error(f"발행 실패 {r.status_code}: {r.text[:300]}")
    return None


def check_connection() -> bool:
    """인증·연결 점검(현재 사용자 조회). 실발행 전 스모크 테스트."""
    if not _configured():
        return False
    try:
        r = requests.get(f"{_base()}/wp-json/wp/v2/users/me", headers=_headers(), timeout=_TIMEOUT)
        if r.ok:
            logger.info(f"WP 연결 OK — 사용자 '{r.json().get('name')}' (id={r.json().get('id')})")
            return True
        logger.error(f"WP 연결 실패 {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"WP 연결 예외: {e}")
    return False
