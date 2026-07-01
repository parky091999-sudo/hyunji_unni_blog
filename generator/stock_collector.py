"""
주식 팩트 데이터 수집기 (주식분석·공모주·ETF).
LLM 할루시네이션 방지: 공신력 있는 API·크롤링으로 당일 수치만 확보.
"""
import logging
from datetime import datetime

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger("stock_collector")

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class StockDataCollector:
    @staticmethod
    def get_core_etf_data() -> dict:
        """미국 핵심 ETF(TQQQ, QLD, JEPQ, SCHD) 주가·등락률."""
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
                etf_data[ticker] = {
                    "현재가(USD)": round(current_price, 2),
                    "전일대비 등락률(%)": round(change_pct, 2),
                    "거래량": int(hist["Volume"].iloc[-1]),
                }
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
                entry = {
                    "종목명": name,
                    "시장": market,
                    "공모가": StockDataCollector._ipo_labeled_field(td, "area_price"),
                    "업종": StockDataCollector._ipo_labeled_field(td, "area_type"),
                    "주간사": StockDataCollector._ipo_labeled_field(td, "area_sup"),
                    "경쟁률": StockDataCollector._ipo_labeled_field(td, "area_competition"),
                    "청약일": StockDataCollector._ipo_labeled_field(td, "area_private"),
                    "상장일": StockDataCollector._ipo_labeled_field(td, "area_list"),
                }
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
