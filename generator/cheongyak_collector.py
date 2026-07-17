"""청약홈(한국부동산원) 분양공고 수집 — 건별 청약 분석글 파이프라인 (2026-07-17 사용자 지시).

데이터: 공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스' (odcloud v1)
  · getAPTLttotPblancDetail — APT 분양공고 상세(일정·지역·규제·URL)
  · getAPTLttotPblancMdl    — 주택형별 공급세대·최고분양가
  · getRemndrLttotPblancDetail — 무순위/잔여세대(줍줍)
키: config.PUBLIC_DATA_KEY (미설정 시 수집 스킵 — 파이프라인은 조용히 종료)

공고문 PDF: 공고 상세페이지(PBLANC_URL)에서 모집공고문 링크를 찾아 텍스트 발췌
  → 계약금 비율·중도금 대출 조건 등 API에 없는 디테일을 팩트로 주입(best-effort,
  실패해도 API 팩트만으로 발행 가능).

대상 지역: 수도권+광역시(2026-07-17 사용자 승인 범위). 임대 공고는 제외.
"""
import io
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import PUBLIC_DATA_KEY

logger = logging.getLogger("cheongyak_collector")

KST = timezone(timedelta(hours=9))
_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
_TIMEOUT = 30

# 수도권 + 광역시 + 세종 (청약홈 SUBSCRPT_AREA_CODE_NM 표기)
REGIONS = {"서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종"}


def _call(endpoint: str, cond: dict | None = None, per_page: int = 100) -> list[dict]:
    """odcloud 공통 호출. 실패/키 없음 → 빈 리스트."""
    if not PUBLIC_DATA_KEY:
        logger.warning("PUBLIC_DATA_KEY 미설정 — 청약홈 수집 스킵 "
                       "(data.go.kr에서 '청약홈 분양정보' 활용신청 후 키 등록 필요)")
        return []
    params = {"page": 1, "perPage": per_page, "serviceKey": PUBLIC_DATA_KEY}
    for k, v in (cond or {}).items():
        params[f"cond[{k}]"] = v
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"청약홈 API 호출 실패 ({endpoint}): {e}")
        return []


def _is_target(d: dict) -> bool:
    region = (d.get("SUBSCRPT_AREA_CODE_NM") or "").strip()
    if region not in REGIONS:
        return False
    # 임대 공고 제외(분양만) — RENT_SECD: 0=분양, 1=임대(명칭 필드가 더 안정적)
    rent_nm = str(d.get("RENT_SECD_NM") or d.get("RENT_SECD") or "")
    if "임대" in rent_nm or rent_nm == "1":
        return False
    return True


def fetch_new_apt_notices(days: int = 7) -> list[dict]:
    """최근 N일 모집공고(APT 분양) — 대상 지역·분양만."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _call("getAPTLttotPblancDetail", {"RCRIT_PBLANC_DE::GTE": cutoff})
    out = [d for d in rows if _is_target(d)]
    logger.info(f"청약홈 APT 공고: 최근 {days}일 {len(rows)}건 → 대상지역 {len(out)}건")
    return out


def fetch_new_remainder_notices(days: int = 7) -> list[dict]:
    """최근 N일 무순위/잔여세대(줍줍) 공고."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _call("getRemndrLttotPblancDetail", {"RCRIT_PBLANC_DE::GTE": cutoff})
    out = [d for d in rows if _is_target(d)]
    for d in out:
        d["_remainder"] = True
    logger.info(f"청약홈 무순위 공고: 최근 {days}일 {len(rows)}건 → 대상지역 {len(out)}건")
    return out


def fetch_house_types(house_manage_no: str, remainder: bool = False) -> list[dict]:
    """주택형별 공급세대수·최고분양가."""
    ep = "getRemndrLttotPblancMdl" if remainder else "getAPTLttotPblancMdl"
    return _call(ep, {"HOUSE_MANAGE_NO::EQ": house_manage_no})


def notice_key(d: dict) -> str:
    return f"{d.get('HOUSE_MANAGE_NO', '')}-{d.get('PBLANC_NO', '')}"


# ── 공고문 PDF: 다운로드 → 텍스트 발췌 + 핵심 페이지 이미지 캡처 ─────────────

_PDF_KEYWORDS = ("계약금", "중도금", "잔금", "공급금액", "납부", "대출", "발코니", "옵션")
# 이미지 캡처 대상 페이지 분류 (2026-07-17 사용자 지시: 금액표·평면도 캡처를 본문에)
_PRICE_PAGE_KWS = ("공급금액", "납부일정", "납부조건")
# 평면도 = '평면도' 키워드 + 도면형 페이지(텍스트 희박). '단위세대'는 유의사항 문단에도
# 흔해 오탐(월계 공고 p42/54 실측) — 제외. 도면 없는 공고(월계 등)에선 캡처 안 됨이 정답.
_PLAN_KW = "평면도"
_PLAN_MAX_TEXT = 900


def fetch_notice_pdf(detail: dict) -> bytes | None:
    """공고 상세페이지(PBLANC_URL)에서 모집공고문 PDF 바이트 확보. 실패 시 None."""
    page_url = (detail.get("PBLANC_URL") or "").strip()
    if not page_url:
        return None
    try:
        import html as _html
        html = requests.get(page_url, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"}).text
        # 1순위: '모집공고문 보기' 앵커 href — 실측 패턴(2026-07-17 월계 중흥S-클래스):
        #   https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=…&atchmnflSn=…
        pdf_url = ""
        m = re.search(r"""<a[^>]+href=["']([^"']+)["'][^>]*>[^<]*모집공고문[^<]*</a>""", html)
        if m:
            pdf_url = _html.unescape(m.group(1))
        if not pdf_url:
            # 2순위: 첨부파일/PDF 계열 링크 패턴
            cands = re.findall(
                r"""["']([^"']+(?:getAtchmnfl\.do[^"']*|\.pdf[^"']*|[Ff]ile[Dd]own[^"']*))["']""", html)
            if cands:
                pdf_url = _html.unescape(cands[0])
        if not pdf_url:
            logger.info("공고문 PDF 링크 미발견 — API 팩트만 사용")
            return None
        if not pdf_url.startswith("http"):
            pdf_url = f"https://www.applyhome.co.kr{pdf_url}"
        pdf_bytes = requests.get(pdf_url, timeout=60,
                                 headers={"User-Agent": "Mozilla/5.0",
                                          "Referer": page_url}).content
        if pdf_bytes[:4] != b"%PDF":
            logger.info("공고문 응답이 PDF 아님 — 사용 안 함")
            return None
        logger.info(f"공고문 PDF 확보: {len(pdf_bytes) // 1024}KB")
        return pdf_bytes
    except Exception as e:
        logger.info(f"공고문 PDF 확보 실패(무시): {e}")
        return None


def _page_texts(pdf_bytes: bytes, max_pages: int = 40) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out = []
    for p in reader.pages[:max_pages]:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            out.append("")
    return out


def pdf_excerpt(pdf_bytes: bytes, max_chars: int = 12000) -> str:
    """납부조건·대출 등 핵심 키워드 페이지 위주 텍스트 발췌 (팩트 주입용)."""
    try:
        pages = _page_texts(pdf_bytes)
        keyed = [t for t in pages if any(k in t for k in _PDF_KEYWORDS)]
        text = "\n".join(keyed or pages[:6])
        text = re.sub(r"[ \t]+", " ", text)
        logger.info(f"공고문 PDF 발췌 {len(text)}자 (키워드 페이지 {len(keyed)}개)")
        return text[:max_chars]
    except Exception as e:
        logger.info(f"공고문 텍스트 발췌 실패(무시): {e}")
        return ""


def pdf_capture_key_pages(pdf_bytes: bytes, max_price: int = 2, max_plan: int = 2) -> list[dict]:
    """공급금액표·평면도 페이지를 PNG로 렌더 → [{path, label}] (본문 삽입용, PyMuPDF).
    평면도가 공고문에 없는 단지는 금액표만 캡처된다. 실패 시 빈 리스트."""
    import tempfile
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.info("PyMuPDF 미설치 — 공고문 페이지 캡처 생략")
        return []
    out: list[dict] = []
    try:
        texts = _page_texts(pdf_bytes, max_pages=60)
        price_idx = [i for i, t in enumerate(texts) if any(k in t for k in _PRICE_PAGE_KWS)]
        plan_idx = [i for i, t in enumerate(texts)
                    if _PLAN_KW in t and len(t) < _PLAN_MAX_TEXT and i not in price_idx]
        targets = ([(i, "공급금액·납부조건") for i in price_idx[:max_price]]
                   + [(i, "타입별 평면도") for i in plan_idx[:max_plan]])
        if not targets:
            logger.info("공고문에서 금액표/평면도 페이지 미검출 — 캡처 생략")
            return []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, label in targets:
            if i >= doc.page_count:
                continue
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))  # 2배율 — 표 글자 가독
            # Windows: 핸들 열린 채 save하면 PermissionError — 먼저 닫고 경로에 저장
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.close()
            pix.save(tmp.name)
            out.append({"path": tmp.name, "label": label, "page": i + 1})
        doc.close()
        logger.info(f"공고문 페이지 캡처 {len(out)}장: {[o['label'] for o in out]}")
        return out
    except Exception as e:
        logger.info(f"공고문 페이지 캡처 실패(무시): {e}")
        return []


# ── 팩트 빌드 ────────────────────────────────────────────────────────────────

def _money(val) -> str:
    """LTTOT_TOP_AMOUNT(만원 단위) → '5억 2,000만 원' 표기."""
    try:
        n = int(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    eok, man = divmod(n, 10000)
    if eok and man:
        return f"{eok}억 {man:,}만 원"
    if eok:
        return f"{eok}억 원"
    return f"{man:,}만 원"


def build_facts(detail: dict, types: list[dict], pdf_excerpt: str = "") -> dict:
    """generate_deep_post의 facts(dict) — 공고 확정 팩트만 담는다."""
    g = detail.get
    schedule = {
        "모집공고일": g("RCRIT_PBLANC_DE", ""),
        "특별공급 접수": f"{g('SPSPLY_RCEPT_BGNDE', '')} ~ {g('SPSPLY_RCEPT_ENDDE', '')}",
        "1순위 접수": f"{g('GNRL_RNK1_CRSPAREA_RCPTDE', '')} (해당지역) / "
                    f"{g('GNRL_RNK1_ETC_AREA_RCPTDE', '')} (기타지역)",
        "2순위 접수": f"{g('GNRL_RNK2_CRSPAREA_RCPTDE', '')} (해당지역)",
        "당첨자 발표": g("PRZWNER_PRESNATN_DE", ""),
        "계약": f"{g('CNTRCT_CNCLS_BGNDE', '')} ~ {g('CNTRCT_CNCLS_ENDDE', '')}",
        "입주 예정": g("MVN_PREARNGE_YM", ""),
    }
    if detail.get("_remainder"):
        schedule = {
            "모집공고일": g("RCRIT_PBLANC_DE", ""),
            "접수": f"{g('SUBSCRPT_RCEPT_BGNDE', '') or g('RCEPT_BGNDE', '')} ~ "
                  f"{g('SUBSCRPT_RCEPT_ENDDE', '') or g('RCEPT_ENDDE', '')}",
            "당첨자 발표": g("PRZWNER_PRESNATN_DE", ""),
            "계약": f"{g('CNTRCT_CNCLS_BGNDE', '')} ~ {g('CNTRCT_CNCLS_ENDDE', '')}",
        }

    type_rows = []
    top_prices = []
    for t in types:
        price = _money(t.get("LTTOT_TOP_AMOUNT"))
        row = {
            "주택형": t.get("HOUSE_TY", ""),
            "공급면적": f"{t.get('SUPLY_AR', '')}㎡",
            "일반공급": t.get("SUPLY_HSHLDCO", ""),
            "특별공급": t.get("SPSPLY_HSHLDCO", ""),
            "최고분양가": price or "공고문 확인",
        }
        type_rows.append(row)
        try:
            top_prices.append(int(str(t.get("LTTOT_TOP_AMOUNT")).replace(",", "")))
        except (TypeError, ValueError):
            pass

    facts = {
        "단지명": g("HOUSE_NM", ""),
        "공급위치": g("HSSPLY_ADRES", ""),
        "공급지역": g("SUBSCRPT_AREA_CODE_NM", ""),
        "공고유형": "무순위/잔여세대(줍줍)" if detail.get("_remainder") else "APT 일반분양",
        "총공급세대수": g("TOT_SUPLY_HSHLDCO", ""),
        "시공사": g("CNSTRCT_ENTRPS_NM", ""),
        "문의처": g("MDHS_TELNO", ""),
        "일정": schedule,
        "주택형별 공급": type_rows,
        "규제": {
            "투기과열지구": g("SPECLT_RDN_EARTH_AT", ""),
            "조정대상지역": g("MDAT_TRGET_AREA_SECD", ""),
            "분양가상한제": g("PARCPRC_ULS_AT", ""),
            "정비사업": g("IMPRMN_BSNS_AT", ""),
            "공공주택지구": g("PUBLIC_HOUSE_EARTH_AT", ""),
            "생애최초 공급": g("LFE_FRST_SUPLY_AT", ""),
        },
        "청약홈 공고 URL": g("PBLANC_URL", ""),
    }
    if top_prices:
        top = max(top_prices)
        facts["필요현금 참고(최고분양가 기준)"] = {
            "최고분양가": _money(top),
            "계약금 10% 가정": _money(round(top * 0.1)),
            "계약금 20% 가정": _money(round(top * 0.2)),
            "주의": "실제 계약금 비율·중도금 대출 여부는 입주자모집공고문 기준(아래 발췌 참고)",
        }
    if pdf_excerpt:
        facts["모집공고문 발췌(납부조건·대출 관련 원문)"] = pdf_excerpt
    return facts


def build_key_stats(detail: dict, types: list[dict]) -> list:
    stats = []
    if detail.get("TOT_SUPLY_HSHLDCO"):
        stats.append({"label": "총 공급세대", "value": f"{detail['TOT_SUPLY_HSHLDCO']}세대"})
    rc = detail.get("GNRL_RNK1_CRSPAREA_RCPTDE") or detail.get("RCEPT_BGNDE", "")
    if rc:
        stats.append({"label": "청약 접수", "value": rc})
    prices = [t.get("LTTOT_TOP_AMOUNT") for t in types if t.get("LTTOT_TOP_AMOUNT")]
    if prices:
        try:
            stats.append({"label": "최고 분양가", "value": _money(max(int(str(p).replace(',', '')) for p in prices))})
        except ValueError:
            pass
    if detail.get("PRZWNER_PRESNATN_DE"):
        stats.append({"label": "당첨자 발표", "value": detail["PRZWNER_PRESNATN_DE"]})
    return stats[:4]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    notices = fetch_new_apt_notices() + fetch_new_remainder_notices()
    for n in notices[:10]:
        print(notice_key(n), "|", n.get("HOUSE_NM"), "|", n.get("SUBSCRPT_AREA_CODE_NM"),
              "|", n.get("RCRIT_PBLANC_DE"))
    if not notices:
        print("신규 공고 없음(또는 PUBLIC_DATA_KEY 미설정)")
