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


def _strip_qa_prefix(text: str) -> str:
    """FAQ 문항의 'Q:'/'A:' 접두 제거 — 표시·스키마 모두 질문/답 본문만 남긴다."""
    return re.sub(r"^[QqAa]\s*[:.]\s*", "", text.strip())


def _bullet_kind(line: str):
    """리스트 항목 종류 판별 → ('ol'|'ul', 내용, 번호|None) 또는 None.
    번호를 보존해야 산문 문단이 사이에 끼어 리스트가 쪼개져도 1,1,1로 리셋되지 않는다."""
    s = line.strip()
    m = re.match(r"^([①-⑳])\s*(.+)", s)                 # 원형숫자 = 순서 있는 단계
    if m:
        return ("ol", m.group(2), ord(m.group(1)) - ord("①") + 1)
    m = re.match(r"^(\d{1,2})[.)]\s*(.+)", s)            # 1. 2. = 순서
    if m:
        return ("ol", m.group(2), int(m.group(1)))
    m = re.match(r"^[·•\-*]\s*(.+)", s)                   # 글머리 = 순서 없음
    if m:
        return ("ul", m.group(1), None)
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
            f"<h3 class=\"hj-faq-q\">{escape(_strip_qa_prefix(_clean_inline(q)))}</h3>"
            f"<p class=\"hj-faq-a\">{escape(_strip_qa_prefix(_clean_inline(a)))}</p>"
            "</div>"
        )
    # 제목(h2)은 본문의 '자주 묻는 질문' 소제목이 담당 — 여기서 중복 출력하지 않음.
    return f'<div class="hj-faq">{blocks}</div>'


def _faq_schema(faq_pairs) -> dict | None:
    if not faq_pairs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": _strip_qa_prefix(_clean_inline(q)),
                "acceptedAnswer": {"@type": "Answer", "text": _strip_qa_prefix(_clean_inline(a))},
            }
            for q, a in faq_pairs
        ],
    }


def _key_stats_html(key_stats) -> str:
    """핵심 수치 스트립 — [(값, 라벨), ...] → 카드 그리드(WP_PIPELINE §1 3번)."""
    if not key_stats:
        return ""
    cards = ""
    for item in key_stats[:4]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            v, l = item[0], item[1]
        elif isinstance(item, dict):
            v, l = item.get("value", ""), item.get("label", "")
        else:
            continue
        if not str(v).strip():
            continue
        cards += (
            f'<div class="hj-stat"><div class="hj-stat-v">{escape(str(v))}</div>'
            f'<div class="hj-stat-l">{escape(str(l))}</div></div>'
        )
    return f'<div class="hj-stats">{cards}</div>' if cards else ""


def _sources_html(sources) -> str:
    """참고·출처 — [(제목, url), ...] → 목록(E-E-A-T, WP_PIPELINE §1 8번)."""
    if not sources:
        return ""
    lis = ""
    for s in sources:
        if isinstance(s, (list, tuple)) and len(s) >= 2:
            t, u = s[0], s[1]
        elif isinstance(s, dict):
            t, u = s.get("title", ""), s.get("url", "")
        else:
            t, u = str(s), ""
        if not str(t).strip():
            continue
        if u:
            lis += f'<li><a href="{escape(str(u))}" rel="noopener nofollow" target="_blank">{escape(str(t))}</a></li>'
        else:
            lis += f"<li>{escape(str(t))}</li>"
    return f'<div class="hj-sources"><h2>참고·출처</h2><ul>{lis}</ul></div>' if lis else ""


def _toc_html(items) -> str:
    """목차 — [(anchor, text), ...] → 앵커 링크 목록(WP_PIPELINE §1 4번)."""
    if len(items) < 3:  # 섹션 2개 이하면 목차 실익 없음
        return ""
    lis = "".join(f'<li><a href="#{a}">{escape(t)}</a></li>' for a, t in items)
    return f'<nav class="hj-toc"><p class="hj-toc-t">목차</p><ol>{lis}</ol></nav>'


_DISCLAIMER = {
    "금융·재테크": "이 글은 일반적인 정보 제공을 목적으로 하며, 특정 금융상품의 가입 권유가 아닙니다. 세율·한도 등 제도 수치는 개정될 수 있으니 국세청·금융감독원 공식 자료로 최신 기준을 확인하세요. 투자·세무 판단의 책임은 본인에게 있습니다.",
    "세금·절세": "이 글은 일반적인 정보 제공을 목적으로 하며, 개별 사안의 세무 판단은 국세청 홈택스 또는 세무 전문가 상담으로 확인하세요. 세법·공제 기준은 개정될 수 있습니다.",
    "보험": "이 글은 일반적인 정보 제공을 목적으로 하며 특정 보험상품의 가입 권유가 아닙니다. 보장 내용·보험료는 상품과 개인 조건에 따라 다르니 가입 전 약관과 공식 비교 도구로 확인하세요.",
    "부동산·주거": "이 글은 일반적인 정보 제공을 목적으로 하며, 대출 한도·금리·세금은 개인 조건과 정책 변경에 따라 달라집니다. 실제 신청 전 금융기관·관할 기관 공식 안내로 확인하세요.",
}
_DISCLAIMER_DEFAULT = "이 글은 일반적인 정보 제공을 목적으로 하며, 제도·수치는 개정될 수 있으니 공식 자료로 최신 기준을 확인하세요."


def _related_posts_html(related: list[dict], base_url: str = "") -> str:
    """같은 카테고리 WP 글 내부 링크 — 체류·SEO."""
    if not related:
        return ""
    items = ""
    for r in related[:3]:
        title = escape(str(r.get("title", "")))
        slug = r.get("slug", "")
        link = r.get("link") or (f"{base_url.rstrip('/')}/{slug}/" if base_url and slug else "")
        if not link:
            continue
        items += f'<li><a href="{escape(link)}">{title}</a></li>'
    if not items:
        return ""
    return f'<nav class="hj-related"><h2>함께 보면 좋은 글</h2><ul>{items}</ul></nav>'


def _disclaimer_html(category: str) -> str:
    txt = _DISCLAIMER.get(category, _DISCLAIMER_DEFAULT)
    return f'<div class="hj-disclaimer">{escape(txt)}</div>'


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


def render_wordpress_post(post: dict, category: str = "", base_url: str = "",
                          slug_override: str = "", related_posts: list | None = None) -> dict:
    """post dict(_parse_response 산출) → 워드프레스 발행용 HTML+SEO 번들."""
    title = _clean_inline(post.get("title", "")).strip()
    body = post.get("body", "") or ""
    table_strs = post.get("table_strs", []) or ([post["table_str"]] if post.get("table_str") else [])
    faq_pairs = post.get("faq_pairs", []) or []

    out: list[str] = []
    list_buf: list[str] = []
    list_type = None
    list_start = None  # 쪼개진 ol이 이어지도록 시작 번호 보존
    ol_global_next = 1  # 섹션 간 ① 리셋 방지
    table_i = 0
    toc: list[tuple[str, str]] = []  # (anchor, 소제목 텍스트)

    def flush_list():
        nonlocal list_buf, list_type, list_start, ol_global_next
        if list_buf:
            tag = list_type or "ul"
            lis = "".join(f"<li>{escape(x)}</li>" for x in list_buf)
            if tag == "ol":
                start = list_start or 1
                attr = f' start="{start}"' if start > 1 else ""
                out.append(f"<ol{attr}>{lis}</ol>")
                ol_global_next = start + len(list_buf)
            else:
                out.append(f"<ul>{lis}</ul>")
            list_buf = []
            list_type = None
            list_start = None

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
                sub = _clean_inline(lines[i])
                anchor = f"sec-{len(toc) + 1}"
                toc.append((anchor, sub))
                out.append(f'<h2 id="{anchor}">{escape(sub)}</h2>')
                i += 1
            continue

        bk = _bullet_kind(s)
        if bk:
            kind, content, num = bk
            if list_type and list_type != kind:
                flush_list()
            if not list_buf:
                # 새 ol 시작: ①(1)이 섹션마다 반복되면 전역 번호로 이어 붙임
                list_start = num if (num and num > 1) else ol_global_next
            list_type = kind
            list_buf.append(_clean_inline(content))
            continue

        flush_list()
        out.append(f"<p>{escape(_clean_inline(s))}</p>")

    flush_list()
    body_html = "\n".join(x for x in out if x)

    # ── v2 페이지 요소 조립 (WP_PIPELINE §1·§2) ──
    key_stats_html = _key_stats_html(post.get("key_stats"))
    toc_html = _toc_html(toc)
    sources_html = _sources_html(post.get("sources"))
    related_html = _related_posts_html(related_posts or [], base_url)
    disclaimer_html = _disclaimer_html(category)
    # 발행용 완성 본문 — §1 승인 순서: 도입(두괄식)+요약 → 핵심수치 → 목차 → 본문 섹션 → 출처 → 면책.
    #   핵심수치·목차는 첫 소제목(h2) 직전에 삽입해 도입문이 글 맨 위에 오게 한다.
    pieces = [x for x in out if x]
    first_h2 = next((i for i, p in enumerate(pieces) if p.startswith("<h2 ")), None)
    if first_h2 is not None:
        pieces = pieces[:first_h2] + [key_stats_html, toc_html] + pieces[first_h2:]
    else:
        pieces = [key_stats_html, toc_html] + pieces
    content_html = "\n".join(
        x for x in (*pieces, related_html, sources_html, disclaimer_html) if x
    )

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
        "html": body_html,          # 본문만(하위호환)
        "content_html": content_html,  # 핵심수치+목차+본문+출처+면책 (WP 발행용)
        "toc_html": toc_html,
        "key_stats_html": key_stats_html,
        "sources_html": sources_html,
        "meta_description": desc,
        "excerpt": desc,
        "slug": (slug_override or _slug(post.get("keyword", ""), title)).strip("-"),
        "schema_jsonld": schema_jsonld,
        "tags": post.get("tags", []),
    }
