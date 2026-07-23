"""발행 직후 품질 게이트 (2026-07-23 사용자 지시 '발행시 점검').

각 채널 발행 스크립트가 발행 성공 직후 호출 → 5대 점검 기준(이미지/표·기호누출·글머리·
소제목·상투어)을 자동 검사하고 data/qc_log.jsonl 에 기록. WP는 리터럴 마크다운·h4가
라이브에 남아있으면 self-heal(normalize 재PUT)까지 한다. 절대 발행을 막지 않는다
(발행은 이미 성공한 상태 — QC는 사후 점검·자가교정·로깅).

판정: FAIL=즉시 교정 대상(마커/h4), WARN=품질 저하(상투어·과분할), OK.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from generator.wp_html import normalize_residual_md, rendered_to_raw

logger = logging.getLogger("publish_qc")
KST = timezone(timedelta(hours=9))
_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_QC_LOG = os.path.join(_DATA, "qc_log.jsonl")

# 교과서체 종결 상투어(명백한 것만 — '해야 합니다' 등 흔한 표현은 오탐이라 제외).
_CLICHE = re.compile(
    r"것이 (?:중요|좋)|게 좋습니다|하시면 됩니다|도움이 되(?:길|었)|기억하세요|"
    r"이처럼|이로써|혁신적|극대화|탁월")
_MD_BULLET = re.compile(r"(?:^|\n|>)\*[ \t]+\S")


def check_wp_html(html: str) -> tuple[list[tuple[str, str]], dict]:
    """WP 본문(content.rendered/raw) 점검. (issues, metrics)."""
    issues: list[tuple[str, str]] = []
    if "**" in html:
        issues.append(("FAIL", f"리터럴 마크다운 ** x{html.count('**')}"))
    if _MD_BULLET.search(html):
        issues.append(("FAIL", "미변환 마크다운 불릿 '* '"))
    if "[[" in html:
        issues.append(("FAIL", "위키링크 [[ 누출"))
    if re.search(r"\{\{.*?\}\}", html):
        issues.append(("WARN", "미변환 {{ }} 마커"))
    h4 = len(re.findall(r"<h[4-6]\b", html))
    if h4:
        issues.append(("FAIL", f"화이트리스트 이탈 h4+ x{h4}"))
    heads = len(re.findall(r"<h[23]\b", html))
    if heads > 18:
        issues.append(("WARN", f"소제목 과다 x{heads}"))
    cl = len(_CLICHE.findall(html))
    if cl > 3:
        issues.append(("WARN", f"교과서체 상투어 x{cl}"))
    metrics = {"h2h3": heads, "h4plus": h4, "img": html.count("<img"),
               "table": html.count("<table"), "cliche": cl}
    return issues, metrics


def check_naver_text(text: str) -> tuple[list[tuple[str, str]], dict]:
    """네이버 본문(에디터에 넣은 plain text) 점검."""
    issues: list[tuple[str, str]] = []
    if "**" in text:
        issues.append(("FAIL", f"리터럴 마크다운 ** x{text.count('**')}"))
    if "[[" in text:
        issues.append(("FAIL", "위키링크 [[ 누출"))
    if re.search(r"(?:^|\n)\*[ \t]+\S", text):
        issues.append(("WARN", "마크다운 불릿 '* '"))
    if "##" in text or re.search(r"(?:^|\n)#{1,6}\s", text):
        issues.append(("WARN", "마크다운 헤더 '#'"))
    cl = len(_CLICHE.findall(text))
    if cl > 4:
        issues.append(("WARN", f"교과서체 상투어 x{cl}"))
    return issues, {"chars": len(text), "cliche": cl}


def check_caption(text: str) -> tuple[list[tuple[str, str]], dict]:
    """스레드/단문 캡션 점검(마커 위주)."""
    issues: list[tuple[str, str]] = []
    for mk in ("**", "[[", "]]", "##"):
        if mk in text:
            issues.append(("FAIL", f"기호 누출 '{mk}'"))
    return issues, {"chars": len(text)}


def verdict(issues: list[tuple[str, str]]) -> str:
    if any(s == "FAIL" for s, _ in issues):
        return "FAIL"
    if any(s == "WARN" for s, _ in issues):
        return "WARN"
    return "OK"


def record(channel: str, ident: str, issues: list[tuple[str, str]], metrics: dict,
           healed: bool = False) -> str:
    """qc_log.jsonl append + 로그 출력. 판정 문자열 반환."""
    v = verdict(issues)
    rec = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "channel": channel,
           "id": ident, "verdict": v, "healed": healed,
           "issues": [f"{s}:{m}" for s, m in issues], "metrics": metrics}
    try:
        with open(_QC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"QC 로그 기록 실패: {e}")
    tag = {"OK": "✅", "WARN": "⚠️", "FAIL": "🔴"}.get(v, "?")
    detail = "; ".join(f"{s}:{m}" for s, m in issues) or "clean"
    logger.info(f"[QC {tag} {v}] {channel} {ident}{' (self-healed)' if healed else ''} — {detail}")
    return v


def qc_wp_live(wp_url: str, post_id: int, auth, channel: str, ident: str,
               heal: bool = True) -> str:
    """발행된 WP 글을 라이브로 재fetch(context=edit)→점검→FAIL(마커/h4)이면 self-heal 재PUT."""
    import requests
    base = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    try:
        r = requests.get(base, params={"context": "edit", "_fields": "content"},
                         auth=auth, timeout=45)
        content = r.json().get("content", {})
        raw = content.get("raw") or rendered_to_raw(content.get("rendered", ""))
    except Exception as e:
        logger.warning(f"[QC] 라이브 재fetch 실패 {channel} {ident}: {e}")
        return "ERROR"
    issues, metrics = check_wp_html(raw)
    healed = False
    if heal and any(s == "FAIL" for s, _ in issues) and (
            "**" in raw or _MD_BULLET.search(raw) or re.search(r"<h[4-6]\b", raw)):
        fixed = normalize_residual_md(raw)
        if fixed != raw:
            try:
                u = requests.post(base, json={"content": fixed}, auth=auth, timeout=45)
                if u.status_code in (200, 201):
                    healed = True
                    issues, metrics = check_wp_html(fixed)
                    logger.info(f"[QC] self-heal 완료 {channel} {ident}")
                else:
                    logger.warning(f"[QC] self-heal PUT 실패 {u.status_code}")
            except Exception as e:
                logger.warning(f"[QC] self-heal 오류: {e}")
    return record(channel, ident, issues, metrics, healed=healed)
