"""
주식 팩트 데이터 수집기 (주식분석·공모주·ETF).
LLM 할루시네이션 방지: 공신력 있는 API·크롤링으로 당일 수치만 확보.
"""
import logging
import re
from datetime import datetime

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger("stock_collector")

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ETF 성격 프로필(고정 팩트 — 운용사 공시 기반 상식). 구체 수치가 아닌 '전략 성격'만.
_ETF_PROFILE: dict[str, dict] = {
    "SCHD": {
        "이름": "Schwab 미국 배당주 ETF",
        "성격": "배당성장 코어",
        "전략": "다우존스 미국배당100 지수 추종(패시브), 10년 이상 배당 우량주",
        "지급주기": "분기 배당",
        "포지션": "포트폴리오 중심을 잡는 안정형",
    },
    "JEPQ": {
        "이름": "JPMorgan 나스닥 프리미엄인컴 ETF",
        "성격": "고배당 월인컴",
        "전략": "나스닥100 보유 + 커버드콜(옵션 프리미엄)으로 월분배 추구(액티브)",
        "지급주기": "월 배당",
        "포지션": "현금흐름형. 강세장 상단수익 제한·분배금 변동 큼",
    },
    "QLD": {
        "이름": "ProShares 나스닥100 2배 ETF",
        "성격": "2배 레버리지",
        "전략": "나스닥100 일간 수익률의 2배 추종",
        "지급주기": "배당 거의 없음",
        "포지션": "공격형. 횡보장 복리감소(변동성 끌림) 주의",
    },
    "TQQQ": {
        "이름": "ProShares 나스닥100 3배 ETF",
        "성격": "3배 레버리지",
        "전략": "나스닥100 일간 수익률의 3배 추종",
        "지급주기": "배당 없음",
        "포지션": "초공격형. 장기보유 시 복리감소 심함, 단기·소액 한정",
    },
}


class StockDataCollector:
    @staticmethod
    def get_core_etf_data() -> dict:
        """미국 핵심 ETF(TQQQ, QLD, JEPQ, SCHD) 주가·등락률 + 배당률·총보수·52주위치·전략 프로필."""
        target_tickers = ["TQQQ", "QLD", "JEPQ", "SCHD"]
        etf_data: dict = {}
        logger.info("미국 코어 ETF 데이터 수집 시작")

        for ticker in target_tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="5d")
                if hist.empty or len(hist) < 2:
                    logger.warning(f"{ticker}: 데이터 부족")
                    continue
                current_price = float(hist["Close"].iloc[-1])
                prev_price = float(hist["Close"].iloc[-2])
                change_pct = ((current_price - prev_price) / prev_price) * 100
                row = {
                    "현재가(USD)": round(current_price, 2),
                    "전일대비 등락률(%)": round(change_pct, 2),
                    "거래량": int(hist["Volume"].iloc[-1]),
                }

                # 배당률·총보수·52주 위치 (best-effort — 실패 필드는 생략)
                info = {}
                try:
                    info = stock.info or {}
                except Exception as e:
                    logger.warning(f"{ticker} info 조회 실패(무시): {e}")

                dy = info.get("yield") or info.get("trailingAnnualDividendYield")
                if isinstance(dy, (int, float)) and dy > 0:
                    row["배당수익률(%)"] = round(dy * 100, 2)
                exp = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
                if isinstance(exp, (int, float)) and exp > 0:
                    # yfinance는 0.06% 를 0.0006 또는 0.06으로 주는 경우가 있어 정규화
                    row["총보수(%)"] = round(exp * 100, 2) if exp < 1 else round(exp, 2)
                hi = info.get("fiftyTwoWeekHigh")
                lo = info.get("fiftyTwoWeekLow")
                if isinstance(hi, (int, float)) and isinstance(lo, (int, float)) and hi > lo:
                    pos = (current_price - lo) / (hi - lo) * 100
                    row["52주위치(%)"] = round(max(0, min(100, pos)), 1)

                prof = _ETF_PROFILE.get(ticker)
                if prof:
                    row.update(prof)

                etf_data[ticker] = row
            except Exception as e:
                logger.warning(f"{ticker} 데이터 수집 실패: {e}")

        return etf_data

    @staticmethod
    def _parse_upper_limit_table(table) -> list[dict]:
        rows: list[dict] = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) <= 4:
                continue
            stock_name = cols[3].get_text(strip=True)
            price = cols[4].get_text(strip=True)
            if not stock_name or not price or stock_name in ("종목명", "종목"):
                continue
            change = cols[6].get_text(strip=True) if len(cols) > 6 else (
                cols[2].get_text(strip=True) if len(cols) > 2 else ""
            )
            rows.append({"종목명": stock_name, "현재가": price, "등락률": change})
        return rows

    @staticmethod
    def get_today_upper_limit() -> list[dict]:
        """국내 증시 당일 상한가 종목 (네이버 금융)."""
        url = "https://finance.naver.com/sise/sise_upper.naver"
        upper_limits: list[dict] = []
        logger.info("국내 상한가 특징주 크롤링 시작")

        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            tables = soup.find_all("table", {"class": "type_5"})
            if not tables:
                legacy = soup.find("table", {"class": "type_2"})
                tables = [legacy] if legacy else []

            for table in tables:
                upper_limits.extend(StockDataCollector._parse_upper_limit_table(table))

            if not upper_limits:
                logger.warning("상한가 테이블 미발견 또는 데이터 없음")
        except Exception as e:
            logger.error(f"상한가 크롤링 에러: {e}")

        return upper_limits

    @staticmethod
    def _ipo_field(td, selector: str) -> str:
        el = td.select_one(selector)
        return el.get_text(strip=True) if el else ""

    @staticmethod
    def _ipo_labeled_field(td, area_class: str) -> str:
        """area_* 블록에서 em.tit 라벨을 제외한 값만 추출."""
        area = td.select_one(f".{area_class}")
        if not area:
            return ""
        num = area.select_one(".num")
        if num:
            return num.get_text(strip=True)
        text = area.get_text(strip=True)
        for tit in area.select("em.tit"):
            text = text.replace(tit.get_text(strip=True), "", 1)
        return text.strip()

    @staticmethod
    def get_ipo_calendar() -> list[dict]:
        """공모주 청약 일정 (네이버 금융 IPO)."""
        url = "https://finance.naver.com/sise/ipo.nhn"
        ipo_list: list[dict] = []
        logger.info("공모주 캘린더 크롤링 시작")

        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for tr in soup.select("table.type_7 > tbody > tr"):
                tds = tr.select("td")
                if not tds:
                    continue
                td = tds[0]
                name = (
                    StockDataCollector._ipo_field(td, ".item_name a")
                    or StockDataCollector._ipo_field(td, ".item_name")
                )
                if not name:
                    continue
                market = StockDataCollector._ipo_field(td, ".item_name .type")
                gongmoga = StockDataCollector._ipo_labeled_field(td, "area_price")
                entry = {
                    "종목명": name,
                    "시장": market,
                    "공모가": gongmoga,
                    "업종": StockDataCollector._ipo_labeled_field(td, "area_type"),
                    "주간사": StockDataCollector._ipo_labeled_field(td, "area_sup"),
                    "경쟁률": StockDataCollector._ipo_labeled_field(td, "area_competition"),
                    "청약일": StockDataCollector._ipo_labeled_field(td, "area_private"),
                    "상장일": StockDataCollector._ipo_labeled_field(td, "area_list"),
                }
                # 확정 공모가(단일 숫자)면 10주 청약 증거금(공모가×50%×10주) 계산해 첨부
                nums = re.findall(r"[\d,]+", gongmoga or "")
                if len(nums) == 1:
                    try:
                        price = int(nums[0].replace(",", ""))
                        if price > 0:
                            entry["10주청약증거금(원)"] = f"{int(price * 0.5 * 10):,}"
                    except ValueError:
                        pass
                ipo_list.append(entry)
        except Exception as e:
            logger.error(f"공모주 크롤링 에러: {e}")

        if not ipo_list:
            logger.warning("공모주 일정 데이터 없음")
        return ipo_list[:15]

    @staticmethod
    def collect(topic_id: str) -> dict | list | None:
        """topic_id별 팩트 데이터 수집."""
        collectors = {
            "etf포트폴리오": StockDataCollector.get_core_etf_data,
            "상한가특징주": StockDataCollector.get_today_upper_limit,
            "공모주캘린더": StockDataCollector.get_ipo_calendar,
        }
        fn = collectors.get(topic_id)
        if not fn:
            return None
        data = fn()
        if isinstance(data, dict) and not data:
            return None
        if isinstance(data, list) and not data:
            return None
        return data
