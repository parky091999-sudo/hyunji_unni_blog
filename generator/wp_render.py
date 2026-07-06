"""
네이버 마커 본문 → 워드프레스용 시맨틱 HTML + SEO 메타/스키마 렌더러.

설계 원칙(2026-07-06, 워드프레스 확장):
- 생성 로직(content.py/info_content.py)·품질게이트·표·FAQ·요약은 전부 재활용.
- 발행 렌더러만 교체: SE ONE Playwright 컴포넌트 대신 순수 HTML 문자열 변환(브라우저 불필요).
- 네이버(SE ONE) → 구글 SEO 최적화 변형:
  · [소제목] 회색바 → <h2>/<h3> (검색 구조 신호)
  · [FAQ] 인용구 → <h2> + FAQPage JSON-LD (리치결과)
  · 신청방법 ①②③ → <ol> + (선택)HowTo 스키마
  · 두괄식 답변 → 그대로(피처드 스니펫에 유리)
  · meta description·slug·Article 스키마 신규
- ⚠️ 네이버판과 100% 동일 본문은 구글 중복 페널티 → 호출측에서 변형/‌canonical 관리.

입력: _parse_response 산출 post dict
  {title, body(마커), summary_text, table_strs, faq_pairs, subheadings, tags, ...}
출력: {html, meta_description, slug, schema_jsonld, seo_title, excerpt}
"""
import json
import re
from datetime import datetime, timezone, timedelta
from html import escape

KST = timezone(timedelta(hours=9))
AUTHOR = "현지언니"
_PHOTO_RE = re.compile(r"^\s*\[사진(\d+)\]\s*$")


# ── 인라인 텍스트 정리(마커 잔재·강조마커 제거) ──
def _clean_inline(text: str) -> str:
    t = re.sub(r"\[\[(.+?)\]\]", r"\1", text)          # [[강조]] → 텍스트
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\[(?:요약삽입|표삽입|FAQ삽입|구분선|쿠팡추천\d+)\]", "", t)
    return t.strip()


def _bullet_kind(line: str):
    """리스트 항목 종류 판별 → ('ol'|'ul', 내용) 또는 None."""
    s = line.strip()
    if re.match(r"^[①-⑳]\s", s):                       # 원형숫자 = 순서 있는 단계
        return ("ol", re.sub(r"^[①-⑳]\s*", "", s))
    if re.match(r"^\d{1,2}[.)]\s", s):                  # 1. 2. = 순서
        return ("ol", re.sub(r"^\d{1,2}[.)]\s*", "", s))
    if re.match(r"^[·•\-*]\s", s):                       # 글머리 = 순서 없음
        return ("ul", re.sub(r"^[·•\-*]\s*", "", s))
    return None


# ── 표: 파이프 구분 문자열 → <table> ──
def _table_to_html(tstr: str) -> str:
    rows = []
    for ln in tstr.splitlines():
        ln = ln.strip()
        if not ln or set(ln) <= {"-", "|", " ", "+"}:   # 구분선 행 스킵
            continue
        parts = [c.strip() for c in ln.split("|")]
        if parts and not parts[0]:
            parts = parts[1:]
        if parts and not parts[-1]:
            parts = parts[:-1]
        if parts:
            rows.append(parts)
    if not rows:
        return ""
    head, *body = rows
    th = "".join(f"<th>{escape(c)}</th>" for c in head)
    trs = ""
    for r in body:
        tds = "".join(f"<td>{escape(c)}</td>" for c in r)
        trs += f"<tr>{tds}</tr>"
    return (
        '<figure class="wp-block-table hj-table"><table>'
        f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody>"
        "</table></figure>"
    )


# ── 요약 블록 → 강조 박스 ──
def _summary_to_html(summary_text: str) -> str:
    items = []
    for ln in summary_text.splitlines():
        s = _clean_inline(re.sub(r"^[\s✓✔☑√❤·•▪●◦・\-*①-⑳]+", "", ln)).strip()
        if s:
            items.append(s)
    if not items:
        return ""
    lis = "".join(f"<li>{escape(s)}</li>" for s in items)
    return f'<div class="hj-summary"><p class="hj-summary-title">한눈에 보는 핵심</p><ul>{lis}</ul></div>'


# ── FAQ → <h2> + 아코디언 마크업(스키마는 별도) ──
def _faq_to_html(faq_pairs) -> str:
    if not faq_pairs:
        return ""
    blocks = ""
    for q, a in faq_pairs:
        blocks += (
            '<div class="hj-faq-item">'
            f"<h3 class=\"hj-faq-q\">{escape(_clean_inline(q))}</h3>"
            f"<p class=\"hj-faq-a\">{escape(_clean_inline(a))}</p>"
            "</div>"
        )
    return f'<h2>자주 묻는 질문</h2><div class="hj-faq">{blocks}</div>'


def _faq_schema(faq_pairs) -> dict | None:
    if not faq_pairs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": _clean_inline(q),
                "acceptedAnswer": {"@type": "Answer", "text": _clean_inline(a)},
            }
            for q, a in faq_pairs
        ],
    }


def _article_schema(title: str, desc: str, url: str = "") -> dict:
    now = datetime.now(KST).isoformat()
    d = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title[:110],
        "description": desc,
        "author": {"@type": "Person", "name": AUTHOR},
        "publisher": {"@type": "Organization", "name": AUTHOR},
        "datePublished": now,
        "dateModified": now,
    }
    if url:
        d["mainEntityOfPage"] = {"@type": "WebPage", "@id": url}
    return d


# ── slug: 키워드 기반(한글 허용, 공백→하이픈) ──
def _slug(keyword: str, title: str) -> str:
    base = (keyword or title).strip()
    base = re.sub(r"\([^)]*\)", "", base)
    base = re.sub(r"[^\w가-힣\s-]", "", base)
    base = re.sub(r"\s+", "-", base.strip())
    return base[:60].strip("-").lower()


# ── meta description: 도입부에서 155자 이내 ──
def _meta_description(body: str, summary_text: str) -> str:
    # 도입부 첫 문단(마커 앞)
    intro = ""
    for ln in body.splitlines():
        if _PHOTO_RE.match(ln) or ln.strip().startswith("["):
            if intro:
                break
            continue
        s = _clean_inline(ln)
        if s:
            intro = s
            break
    src = intro or " ".join(
        _clean_inline(re.sub(r"^[\s✓✔☑√❤·•▪●◦・\-*①-⑳]+", "", l)) for l in summary_text.splitlines()
    )
    src = re.sub(r"\s+", " ", src).strip()
    if len(src) > 155:
        src = src[:152].rsplit(" ", 1)[0] + "…"
    return src


def render_wordpress_post(post: dict, category: str = "", base_url: str = "") -> dict:
    """post dict(_parse_response 산출) → 워드프레스 발행용 HTML+SEO 번들."""
    title = _clean_inline(post.get("title", "")).strip()
    body = post.get("body", "") or ""
    table_strs = post.get("table_strs", []) or ([post["table_str"]] if post.get("table_str") else [])
    faq_pairs = post.get("faq_pairs", []) or []

    out: list[str] = []
    list_buf: list[str] = []
    list_type = None
    table_i = 0

    def flush_list():
        nonlocal list_buf, list_type
        if list_buf:
            tag = list_type or "ul"
            lis = "".join(f"<li>{escape(x)}</li>" for x in list_buf)
            out.append(f"<{tag}>{lis}</{tag}>")
            list_buf = []
            list_type = None

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        i += 1
        if not s:
            flush_list()
            continue

        pm = _PHOTO_RE.match(raw)
        if pm:
            flush_list()
            out.append(f'<figure class="hj-photo" data-photo-idx="{pm.group(1)}"></figure>')
            continue
        if s == "[요약삽입]":
            flush_list()
            out.append(_summary_to_html(post.get("summary_text", "")))
            continue
        if s == "[표삽입]":
            flush_list()
            if table_i < len(table_strs):
                out.append(_table_to_html(table_strs[table_i]))
                table_i += 1
            continue
        if s == "[FAQ삽입]":
            flush_list()
            out.append(_faq_to_html(faq_pairs))
            continue
        if s == "[구분선]":
            flush_list()
            # 다음 비어있지 않은 줄 = 소제목
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                out.append(f"<h2>{escape(_clean_inline(lines[i]))}</h2>")
                i += 1
            continue

        bk = _bullet_kind(s)
        if bk:
            kind, content = bk
            if list_type and list_type != kind:
                flush_list()
            list_type = kind
            list_buf.append(_clean_inline(content))
            continue

        flush_list()
        out.append(f"<p>{escape(_clean_inline(s))}</p>")

    flush_list()
    html = "\n".join(x for x in out if x)

    desc = _meta_description(body, post.get("summary_text", ""))
    schemas = [_article_schema(title, desc, base_url)]
    fs = _faq_schema(faq_pairs)
    if fs:
        schemas.append(fs)
    schema_jsonld = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>'
        for s in schemas
    )

    return {
        "seo_title": title[:60],
        "html": html,
        "meta_description": desc,
        "excerpt": desc,
        "slug": _slug(post.get("keyword", ""), title),
        "schema_jsonld": schema_jsonld,
        "tags": post.get("tags", []),
    }
