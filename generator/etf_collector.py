"""
ETF 팩트 데이터 수집기 (국내 ETF·국내상장 해외ETF·미국 ETF·절세계좌 테마).
LLM 할루시네이션 방지: 네이버금융 실데이터·yfinance 실데이터만 사용.
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger("etf_collector")

KST = timezone(timedelta(hours=9))
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_KR_ETF_LIST_URL = "https://finance.naver.com/api/sise/etfItemList.nhn"

_KR_TAB_LABEL = {
    1: "국내 시장지수", 2: "국내 업종·테마", 3: "국내 파생(레버리지·인버스)",
    4: "해외지수(국내상장)", 5: "원자재", 6: "채권", 7: "기타(MMF 등)",
}

# 레버리지·인버스는 변동성이 커서 '정보성' 개별분석/절세계좌 소재로 부적절 — 기본 제외
_RISK_EXCLUDE_KEYWORDS = ["레버리지", "인버스", "곱버스"]

# 국내 섹터·테마 비교군 (실제 KRX 코드, 2026-07 시가총액 상위 검증됨)
KR_SECTOR_GROUPS: dict[str, list[str]] = {
    "반도체": ["396500", "091160", "395270"],
    "2차전지": ["305720", "305540", "364980"],
    "바이오·헬스케어": ["244580", "143860", "266420"],
    "국내 배당": ["161510", "472150", "441800"],
    "리츠(부동산)": ["329200", "476800"],
    "시장 대표(코스피200)": ["069500", "102110", "278530"],
}

# 국내상장 해외ETF 브랜드 비교군 (같은 기초지수, 다른 운용사 — 보수·괴리율 비교 소재)
KR_OVERSEAS_BRAND_GROUPS: dict[str, list[str]] = {
    "미국 S&P500": ["360750", "379800", "360200", "379780"],
    "미국 나스닥100": ["133690", "379810", "367380", "368590"],
    "미국 배당다우존스": ["458730", "446720", "402970", "489250"],
}

# ETF 성격 프로필(고정 팩트 — 운용사 공시 기반 상식). 구체 수치가 아닌 '전략 성격'만.
US_ETF_PROFILE: dict[str, dict] = {
    "SCHD": {
        "이름": "Schwab 미국 배당주 ETF", "성격": "배당성장 코어",
        "전략": "다우존스 미국배당100 지수 추종(패시브), 10년 이상 배당 우량주",
        "지급주기": "분기 배당", "포지션": "포트폴리오 중심을 잡는 안정형",
    },
    "JEPQ": {
        "이름": "JPMorgan 나스닥 프리미엄인컴 ETF", "성격": "고배당 월인컴",
        "전략": "나스닥100 보유 + 커버드콜(옵션 프리미엄)으로 월분배 추구(액티브)",
        "지급주기": "월 배당", "포지션": "현금흐름형. 강세장 상단수익 제한·분배금 변동 큼",
    },
    "JEPI": {
        "이름": "JPMorgan 에퀴티 프리미엄인컴 ETF", "성격": "고배당 월인컴(S&P500)",
        "전략": "S&P500 저변동성 주식 + 커버드콜(ELN)로 월분배 추구(액티브)",
        "지급주기": "월 배당", "포지션": "JEPQ보다 변동성 낮음(나스닥이 아닌 S&P500 기반)",
    },
    "DIVO": {
        "이름": "Amplify CWP 인핸스드 배당인컴 ETF", "성격": "배당블루칩+옵션 인컴",
        "전략": "우량 배당주 액티브 선별 + 일부 콜옵션 매도로 월분배",
        "지급주기": "월 배당", "포지션": "SCHD보다 인컴 비중 높고 변동성 완충 목적",
    },
    "QLD": {
        "이름": "ProShares 나스닥100 2배 ETF", "성격": "2배 레버리지",
        "전략": "나스닥100 일간 수익률의 2배 추종", "지급주기": "배당 거의 없음",
        "포지션": "공격형. 횡보장 복리감소(변동성 끌림) 주의",
    },
    "TQQQ": {
        "이름": "ProShares 나스닥100 3배 ETF", "성격": "3배 레버리지",
        "전략": "나스닥100 일간 수익률의 3배 추종", "지급주기": "배당 없음",
        "포지션": "초공격형. 장기보유 시 복리감소 심함, 단기·소액 한정",
    },
    "QQQ": {
        "이름": "Invesco QQQ Trust", "성격": "나스닥100 성장 코어",
        "전략": "나스닥100 지수 추종(패시브), 대형 기술주 비중 높음",
        "지급주기": "분기 배당(소액)", "포지션": "성장주 중심 공격형 코어",
    },
    "VOO": {
        "이름": "Vanguard S&P500 ETF", "성격": "미국 대표지수 코어",
        "전략": "S&P500 지수 추종(패시브), 초저보수", "지급주기": "분기 배당",
        "포지션": "미국 증시 전체를 담는 기본 코어 자산",
    },
    "VTI": {
        "이름": "Vanguard Total Stock Market ETF", "성격": "미국 전체시장 코어",
        "전략": "CRSP US Total Market 지수 추종(대형~소형주 총망라, 패시브)",
        "지급주기": "분기 배당", "포지션": "VOO보다 더 넓게 담는 시장 전체형 코어",
    },
    "VUG": {
        "이름": "Vanguard Growth ETF", "성격": "미국 대형 성장주",
        "전략": "CRSP US Large Cap Growth 지수 추종(패시브)",
        "지급주기": "분기 배당(소액)", "포지션": "가치주보다 성장주 비중 높은 공격형",
    },
    "SOXL": {
        "이름": "Direxion 데일리 반도체 불 3X", "성격": "반도체 3배 레버리지",
        "전략": "필라델피아 반도체지수 일간 수익률의 3배 추종", "지급주기": "배당 없음",
        "포지션": "초공격형. 반도체 업황에 베팅, 복리감소 위험 큼",
    },
    "UPRO": {
        "이름": "ProShares 울트라프로 S&P500", "성격": "S&P500 3배 레버리지",
        "전략": "S&P500 일간 수익률의 3배 추종", "지급주기": "배당 거의 없음",
        "포지션": "초공격형. 장기보유 부적합",
    },
    "AGG": {
        "이름": "iShares 코어 미국종합채권 ETF", "성격": "미국 종합채권 코어",
        "전략": "블룸버그 미국종합채권지수 추종(국채·회사채·MBS 등, 패시브)",
        "지급주기": "월 배당(이자분배)", "포지션": "안전자산 코어, 금리 변동에 가격 민감",
    },
    "TLT": {
        "이름": "iShares 20년+ 미국국채 ETF", "성격": "미국 장기국채",
        "전략": "만기 20년 이상 미국국채 추종(패시브)", "지급주기": "월 배당",
        "포지션": "금리 하락기에 강세, 금리 인상기엔 변동성 큼(듀레이션 김)",
    },
    "BND": {
        "이름": "Vanguard 토탈본드마켓 ETF", "성격": "미국 전체채권 코어",
        "전략": "블룸버그 미국종합채권(유동조정) 지수 추종(패시브)",
        "지급주기": "월 배당", "포지션": "AGG와 유사한 안전자산 코어, 초저보수",
    },
    "SHY": {
        "이름": "iShares 1-3년 미국국채 ETF", "성격": "미국 단기국채",
        "전략": "만기 1~3년 국채 추종(패시브)", "지급주기": "월 배당",
        "포지션": "변동성 매우 낮은 대기자금·현금성 자산",
    },
}

US_THEME_GROUPS: dict[str, list[str]] = {
    "배당·인컴형": ["SCHD", "JEPI", "JEPQ", "DIVO"],
    "시장지수·성장형": ["QQQ", "VOO", "VTI", "VUG"],
    "레버리지형": ["TQQQ", "QLD", "SOXL", "UPRO"],
    "채권형": ["AGG", "TLT", "BND", "SHY"],
}

_US_WATCHLIST_ALL = list(US_ETF_PROFILE.keys())

_TAX_ANGLES = ["ISA", "연금저축펀드", "퇴직연금DC"]

_CONTENT_TYPES = [
    "kr_individual", "us_individual", "kr_overseas_individual",
    "sector_compare_kr", "sector_compare_us", "tax_account",
]


class EtfDataCollector:
    # ── 국내 ETF 전종목 리스트 ──────────────────────────
    @staticmethod
    def get_kr_etf_list() -> list[dict]:
        """네이버금융 ETF 전종목 API. 시총·거래량·3개월수익률·분류(tab) 포함."""
        try:
            resp = requests.get(_KR_ETF_LIST_URL, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = "euc-kr"
            data = json.loads(resp.text)
            items = data.get("result", {}).get("etfItemList", [])
            logger.info(f"국내 ETF 전종목 수집: {len(items)}건")
            return items
        except Exception as e:
            logger.error(f"국내 ETF 리스트 수집 에러: {e}")
            return []

    @staticmethod
    def get_kr_etf_top(
        tab_codes: list[int], sort_key: str = "marketSum",
        exclude_risk: bool = True, extra_exclude_keywords: list[str] | None = None,
        exclude_codes: set[str] | None = None, top_n: int = 15,
    ) -> list[dict]:
        items = EtfDataCollector.get_kr_etf_list()
        filtered = [i for i in items if i.get("etfTabCode") in tab_codes]
        exclude_kw = list(_RISK_EXCLUDE_KEYWORDS) if exclude_risk else []
        exclude_kw += extra_exclude_keywords or []
        if exclude_kw:
            filtered = [i for i in filtered if not any(k in i.get("itemname", "") for k in exclude_kw)]
        if exclude_codes:
            filtered = [i for i in filtered if i.get("itemcode") not in exclude_codes]
        filtered.sort(key=lambda x: -(x.get(sort_key) or 0))
        return filtered[:top_n]

    @staticmethod
    def get_kr_etf_detail(code: str) -> dict:
        """개별 ETF 상세: 기초지수/유형/상장일·펀드보수/운용사·기간수익률·NAV/괴리율·구성종목상위."""
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        detail: dict = {}
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            t_idx = soup.find("table", {"summary": lambda s: s and "기초지수" in s})
            if t_idx:
                for tr in t_idx.find_all("tr"):
                    th, td = tr.find("th"), tr.find("td")
                    if not th or not td:
                        continue
                    label = th.get_text(strip=True)
                    value = td.get_text(strip=True)
                    if label in ("기초지수", "유형"):
                        detail[label] = value
                    elif label == "상장일":
                        detail["상장일"] = value
                        m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", value)
                        if m:
                            try:
                                detail["_상장일_dt"] = datetime(
                                    int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST
                                )
                            except ValueError:
                                pass

            t_fee = soup.find("table", {"summary": lambda s: s and "펀드보수" in s})
            if t_fee:
                em = t_fee.find("em")
                if em:
                    detail["펀드보수(연,%)"] = em.get_text(strip=True).replace("%", "")
                for tr in t_fee.find_all("tr"):
                    th, td = tr.find("th"), tr.find("td")
                    if th and td and "운용사" in th.get_text():
                        detail["운용사"] = td.get_text(strip=True)

            t_ret = soup.find("table", {"summary": lambda s: s and "수익률" in s})
            if t_ret:
                for tr in t_ret.find_all("tr"):
                    th, td = tr.find("th"), tr.find("td")
                    if not th or not td:
                        continue
                    label = th.get_text(strip=True).replace(" ", "")
                    em = td.find("em")
                    val = (em.get_text(strip=True) if em else td.get_text(strip=True))
                    if val and val.upper() not in ("N/A", "-"):
                        detail[f"{label}(%)"] = val

            nav_table = None
            for t in soup.find_all("table", {"class": "tb_type1"}):
                classes = t.get("class") or []
                if not t.get("summary") and "tb_type1_a" not in classes:
                    nav_table = t
                    break
            if nav_table:
                rows = [tr for tr in nav_table.find_all("tr") if tr.find("td", class_="date")]
                if rows:
                    tds = rows[0].find_all("td")
                    if len(tds) >= 4:
                        detail["최근NAV"] = tds[2].get_text(strip=True)
                        em = tds[3].find("em")
                        detail["괴리율(%)"] = (em.get_text(strip=True) if em else tds[3].get_text(strip=True))

            holdings_table = soup.select_one("table.tb_type1.tb_type1_a")
            if holdings_table:
                holdings = []
                for tr in holdings_table.find_all("tr"):
                    a = tr.find("a", href=True)
                    if not a:
                        continue
                    name = a.get_text(strip=True)
                    per_td = tr.find("td", class_="per")
                    weight = per_td.get_text(strip=True) if per_td else ""
                    if name and weight:
                        holdings.append(f"{name} {weight}")
                    if len(holdings) >= 7:
                        break
                if holdings:
                    detail["구성종목상위"] = holdings
        except Exception as e:
            logger.error(f"{code} ETF 상세 크롤링 에러: {e}")
        return detail

    @staticmethod
    def _find_recent_listings(tab_codes: list[int], top_n: int = 15, max_check: int = 12) -> list[dict]:
        """최근 상장 ETF 후보(휴리스틱: 코드가 클수록 최근 배정 가능성 높음 → 상세페이지 상장일로 실검증)."""
        items = EtfDataCollector.get_kr_etf_list()
        pool = [
            i for i in items
            if i.get("etfTabCode") in tab_codes
            and not any(k in i.get("itemname", "") for k in _RISK_EXCLUDE_KEYWORDS)
        ]
        pool.sort(key=lambda x: x.get("itemcode", ""), reverse=True)
        now = datetime.now(KST)
        found = []
        for item in pool[:max_check]:
            detail = EtfDataCollector.get_kr_etf_detail(item["itemcode"])
            listed = detail.get("_상장일_dt") if detail else None
            # 실측(2026-07): 코드값 상위 12개조차 상장일이 1~2년 전인 경우가 흔함(신규 발행 속도가
            # 코드 소진 속도보다 느림) — 임계값을 넉넉히 잡아 "이 풀에서 상대적으로 최근"을 잡아낸다.
            if listed and (now - listed).days <= 800:
                merged = dict(item)
                merged["_detail_cache"] = detail
                found.append(merged)
            if len(found) >= top_n:
                break
        return found

    # ── 미국 ETF (yfinance) ──────────────────────────
    @staticmethod
    def get_us_etf_data(tickers: list[str]) -> dict:
        """미국 ETF 주가·등락률·배당률·총보수·기간수익률(실데이터) + 성격 프로필."""
        etf_data: dict = {}
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="6mo")
                if hist.empty or len(hist) < 2:
                    logger.warning(f"{ticker}: 데이터 부족")
                    continue
                closes = hist["Close"]
                current_price = float(closes.iloc[-1])
                prev_price = float(closes.iloc[-2])
                change_pct = ((current_price - prev_price) / prev_price) * 100
                row = {
                    "현재가(USD)": round(current_price, 2),
                    "전일대비 등락률(%)": round(change_pct, 2),
                    "거래량": int(hist["Volume"].iloc[-1]),
                    # 주말·휴장일 발행 시 '오늘/전일 마감' 오표기 방지 — 실제 마지막 거래일 명시
                    # (2026-07-05(일) 글이 7/2(목) 종가를 '전일 대비 상승 마감'으로 쓴 실사고)
                    "마지막거래일": hist.index[-1].strftime("%Y-%m-%d"),
                }

                def _trailing_return(days_back: int, _closes=closes, _cur=current_price) -> float | None:
                    if len(_closes) <= days_back:
                        return None
                    old = float(_closes.iloc[-(days_back + 1)])
                    if old <= 0:
                        return None
                    return round((_cur - old) / old * 100, 2)

                r1m = _trailing_return(21)
                if r1m is not None:
                    row["1개월수익률(%)"] = r1m
                r3m = _trailing_return(63)
                if r3m is not None:
                    row["3개월수익률(%)"] = r3m
                if len(closes) >= 20:
                    roll_max = closes.cummax()
                    drawdown = (closes - roll_max) / roll_max * 100
                    row["6개월최대낙폭(%)"] = round(float(drawdown.min()), 2)

                info = {}
                try:
                    info = stock.info or {}
                except Exception as e:
                    logger.warning(f"{ticker} info 조회 실패(무시): {e}")

                dy = info.get("yield") or info.get("trailingAnnualDividendYield")
                if isinstance(dy, (int, float)) and dy > 0:
                    row["배당수익률(%)"] = round(dy * 100, 2)
                exp = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
                # yfinance가 이 필드를 '퍼센트 숫자 그대로'(0.06=0.06%) 반환 — ×100 정규화 금지
                # (과거 stock_collector.py에서 100배 부풀림 실사고 있었음, 동일 주의사항 적용)
                if isinstance(exp, (int, float)) and 0 < exp <= 5:
                    row["총보수(%)"] = round(exp, 2)

                prof = US_ETF_PROFILE.get(ticker)
                if prof:
                    row.update(prof)

                etf_data[ticker] = row
            except Exception as e:
                logger.warning(f"{ticker} 데이터 수집 실패: {e}")
        return etf_data

    # ── 콘텐츠 타입 순환 선정 ──────────────────────────
    @staticmethod
    def pick_etf_topic(history: list[dict] | None = None, force_content_type: str | None = None) -> dict | None:
        """ETF 소분류 콘텐츠 타입(6종)을 순환하며 오늘의 소재를 선정.

        force_content_type: 수동 지정(검증·workflow_dispatch용). _CONTENT_TYPES 중 하나가 아니면 무시.
        """
        history = history or []
        history_len = len(history)
        if force_content_type in _CONTENT_TYPES:
            start_idx = _CONTENT_TYPES.index(force_content_type)
        else:
            start_idx = history_len % len(_CONTENT_TYPES)
        recent_subjects = {h.get("etf_subject") for h in history[:15] if h.get("etf_subject")}

        # 특정 콘텐츠 타입이 일시적 데이터 실패(예: 외부 API 장애)로 None을 반환하면
        # 같은 소재가 다음 실행에서도 반복 스킵되는 걸 막기 위해 다음 타입으로 1바퀴 폴백 탐색.
        for offset in range(len(_CONTENT_TYPES)):
            content_type = _CONTENT_TYPES[(start_idx + offset) % len(_CONTENT_TYPES)]
            try:
                result = EtfDataCollector._pick_by_content_type(content_type, recent_subjects, history_len)
            except Exception as e:
                logger.error(f"ETF 소재 선정 실패({content_type}): {e}")
                result = None
            if result:
                return result
            logger.warning(f"ETF 콘텐츠 타입 {content_type} 소재 없음 — 다음 타입으로 폴백")
        return None

    @staticmethod
    def _pick_by_content_type(content_type: str, recent_subjects: set, history_len: int) -> dict | None:
        if content_type == "kr_individual":
            return EtfDataCollector._pick_individual(recent_subjects, history_len, overseas=False)
        if content_type == "us_individual":
            return EtfDataCollector._pick_us_individual(recent_subjects)
        if content_type == "kr_overseas_individual":
            return EtfDataCollector._pick_individual(recent_subjects, history_len, overseas=True)
        if content_type == "sector_compare_kr":
            return EtfDataCollector._pick_sector_compare(recent_subjects, history_len, us=False)
        if content_type == "sector_compare_us":
            return EtfDataCollector._pick_sector_compare(recent_subjects, history_len, us=True)
        if content_type == "tax_account":
            return EtfDataCollector._pick_tax_account(recent_subjects)
        return None

    @staticmethod
    def _pick_individual(recent_subjects: set, history_len: int, overseas: bool) -> dict | None:
        tab_codes = [4] if overseas else [1, 2]
        sub_mode = (history_len // len(_CONTENT_TYPES)) % 3
        reason_map = {0: "국내 상장 ETF 시가총액 상위권", 1: "오늘 거래량 상위권", 2: "비교적 최근 상장(상장일은 표 참고)"}

        cands: list[dict] = []
        if sub_mode == 0:
            cands = EtfDataCollector.get_kr_etf_top(tab_codes, sort_key="marketSum", top_n=20)
        elif sub_mode == 1:
            cands = EtfDataCollector.get_kr_etf_top(tab_codes, sort_key="quant", top_n=20)
        else:
            cands = EtfDataCollector._find_recent_listings(tab_codes, top_n=20)
        if not cands:
            cands = EtfDataCollector.get_kr_etf_top(tab_codes, sort_key="marketSum", top_n=20)
            sub_mode = 0
        if not cands:
            return None

        picked = next((c for c in cands if c.get("itemcode") not in recent_subjects), cands[0])
        detail = picked.pop("_detail_cache", None) or EtfDataCollector.get_kr_etf_detail(picked["itemcode"])
        code, name = picked["itemcode"], picked["itemname"]

        row = {
            "ETF명": name,
            "현재가": picked.get("nowVal"),
            "전일대비등락률(%)": picked.get("changeRate"),
            "시가총액(억원)": picked.get("marketSum"),
            "거래량": picked.get("quant"),
            "분류": _KR_TAB_LABEL.get(picked.get("etfTabCode"), ""),
            "선정사유": reason_map[sub_mode],
            **detail,
        }
        content_type = "kr_overseas_individual" if overseas else "kr_individual"
        return {
            "_etf_content_type": content_type,
            "_etf_subject": code,
            "_chart_mode": "single",
            "_chart_tickers": [f"{code}.KS"],
            "_chart_labels": {f"{code}.KS": name},
            "_chart_title": f"{name} 최근 6개월 가격 추이",
            "_header_keyword": f"{name} 분석",
            **row,
        }

    @staticmethod
    def _pick_us_individual(recent_subjects: set) -> dict | None:
        pool = _US_WATCHLIST_ALL
        ticker = next((t for t in pool if t not in recent_subjects), pool[0])
        data = EtfDataCollector.get_us_etf_data([ticker])
        row = data.get(ticker)
        if not row:
            return None
        return {
            "_etf_content_type": "us_individual",
            "_etf_subject": ticker,
            "_chart_mode": "single",
            "_chart_tickers": [ticker],
            "_chart_labels": {ticker: row.get("이름", ticker)},
            "_chart_title": f"{ticker} 최근 6개월 가격 추이",
            "_header_keyword": f"{ticker} 분석",
            "티커": ticker,
            "선정사유": "미국 주요 ETF 워치리스트 순환 소개",
            **row,
        }

    @staticmethod
    def _pick_sector_compare(recent_subjects: set, history_len: int, us: bool) -> dict | None:
        groups = US_THEME_GROUPS if us else KR_SECTOR_GROUPS
        names = list(groups.keys())
        idx = (history_len // len(_CONTENT_TYPES)) % len(names)
        order = names[idx:] + names[:idx]
        group_name = next((n for n in order if n not in recent_subjects), order[0])
        members = groups[group_name]
        market = "미국" if us else "국내"

        if us:
            data = EtfDataCollector.get_us_etf_data(members)
            chart_tickers = [t for t in members if t in data]
            chart_labels = {t: data[t].get("이름", t) for t in chart_tickers}
        else:
            data = {}
            chart_tickers, chart_labels = [], {}
            for code in members:
                items = EtfDataCollector.get_kr_etf_list()
                meta = next((i for i in items if i.get("itemcode") == code), None)
                d = EtfDataCollector.get_kr_etf_detail(code)
                name = meta.get("itemname", code) if meta else code
                if meta:
                    d = {
                        "현재가": meta.get("nowVal"), "전일대비등락률(%)": meta.get("changeRate"),
                        "시가총액(억원)": meta.get("marketSum"), **d,
                    }
                if d:
                    data[name] = d
                    chart_tickers.append(f"{code}.KS")
                    chart_labels[f"{code}.KS"] = name
        if not data:
            return None

        return {
            "_etf_content_type": "sector_compare_us" if us else "sector_compare_kr",
            "_etf_subject": group_name,
            "_chart_mode": "compare",
            "_chart_tickers": chart_tickers,
            "_chart_labels": chart_labels,
            "_chart_title": f"{market} {group_name} ETF 비교 (최근 3개월, 시작일=100 기준)",
            "_header_keyword": f"{group_name} ETF 비교",
            "그룹명": group_name,
            "시장": market,
            "비교대상": data,
        }

    @staticmethod
    def _pick_tax_account(recent_subjects: set) -> dict | None:
        angle = next((a for a in _TAX_ANGLES if a not in recent_subjects), _TAX_ANGLES[0])

        kr_examples = EtfDataCollector.get_kr_etf_top([1], sort_key="marketSum", top_n=3)
        overseas_examples = EtfDataCollector.get_kr_etf_top(
            [4], sort_key="marketSum", top_n=3,
            extra_exclude_keywords=["커버드콜", "합성", "레버리지"],
        )
        bond_examples = EtfDataCollector.get_kr_etf_top([6], sort_key="marketSum", top_n=2)

        examples = []
        for c in kr_examples + overseas_examples + bond_examples:
            examples.append({
                "ETF명": c["itemname"],
                "분류": _KR_TAB_LABEL.get(c.get("etfTabCode"), ""),
                "시가총액(억원)": c.get("marketSum"),
            })
        if not examples:
            return None

        return {
            "_etf_content_type": "tax_account",
            "_etf_subject": angle,
            "_chart_mode": None,
            "_chart_tickers": [],
            "_chart_labels": {},
            "_chart_title": "",
            "_header_keyword": f"{angle} ETF 활용법",
            "중심계좌": angle,
            "예시상품군": examples,
            "선정사유": f"{angle} 절세계좌 ETF 투자 안내",
        }
