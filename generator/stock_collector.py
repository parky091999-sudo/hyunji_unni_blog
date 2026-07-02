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
        """미국 핵심 ETF(TQQQ, QLD, JEPQ, SCHD) 주가·등락률 + 배당률·총보수·전략 프로필."""
        target_tickers = ["TQQQ", "QLD", "JEPQ", "SCHD"]
        etf_data: dict = {}
        logger.info("미국 코어 ETF 데이터 수집 시작")

        for ticker in target_tickers:
            try:
                stock = yf.Ticker(ticker)
                # 6개월치를 한 번에 받아 당일 등락률과 실제 과거 수익률(1·3개월)·최대낙폭을 함께 계산
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
                }

                # 실제 과거 가격 기반 수익률·최대낙폭 (거래일 기준 근사치, 21일≈1개월/63일≈3개월)
                def _trailing_return(days_back: int) -> float | None:
                    if len(closes) <= days_back:
                        return None
                    old = float(closes.iloc[-(days_back + 1)])
                    if old <= 0:
                        return None
                    return round((current_price - old) / old * 100, 2)

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

                # 배당률·총보수 (best-effort — 실패 필드는 생략)
                info = {}
                try:
                    info = stock.info or {}
                except Exception as e:
                    logger.warning(f"{ticker} info 조회 실패(무시): {e}")

                dy = info.get("yield") or info.get("trailingAnnualDividendYield")
                if isinstance(dy, (int, float)) and dy > 0:
                    row["배당수익률(%)"] = round(dy * 100, 2)
                exp = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
                # 실측 확인: yfinance가 이 필드를 '퍼센트 숫자 그대로'(0.06=0.06%) 반환함.
                # 과거에 ×100 정규화를 넣었다가 SCHD 0.06%→6.0%, QLD/TQQQ→95%/82%로
                # 100배 부풀려지는 실데이터 오류가 실제 발행 초안에서 발견되어 제거.
                if isinstance(exp, (int, float)) and 0 < exp <= 5:
                    row["총보수(%)"] = round(exp, 2)

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
            entry = {"종목명": stock_name, "현재가": price, "등락률": change}
            if len(cols) > 7:
                volume = cols[7].get_text(strip=True)
                if volume:
                    entry["거래량"] = volume
            a = cols[3].find("a")
            code = StockDataCollector._code_from_href(a.get("href")) if a else None
            if code:
                entry["_code"] = code
            rows.append(entry)
        return rows

    @staticmethod
    def _code_from_href(href: str | None) -> str | None:
        if not href:
            return None
        m = re.search(r"code=(\d{6})", href)
        return m.group(1) if m else None

    @staticmethod
    def get_today_upper_limit() -> list[dict]:
        """국내 증시 당일 상한가 종목 (네이버 금융)."""
        return StockDataCollector._fetch_limit_table(
            "https://finance.naver.com/sise/sise_upper.naver", "상한가"
        )

    @staticmethod
    def get_today_lower_limit() -> list[dict]:
        """국내 증시 당일 하한가 종목 (네이버 금융)."""
        return StockDataCollector._fetch_limit_table(
            "https://finance.naver.com/sise/sise_lower.naver", "하한가"
        )

    @staticmethod
    def _fetch_limit_table(url: str, label: str) -> list[dict]:
        rows: list[dict] = []
        logger.info(f"국내 {label} 종목 크롤링 시작")
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            tables = soup.find_all("table", {"class": "type_5"})
            if not tables:
                legacy = soup.find("table", {"class": "type_2"})
                tables = [legacy] if legacy else []
            for table in tables:
                rows.extend(StockDataCollector._parse_upper_limit_table(table))
            if not rows:
                logger.warning(f"{label} 테이블 미발견 또는 데이터 없음")
        except Exception as e:
            logger.error(f"{label} 크롤링 에러: {e}")
        return rows

    @staticmethod
    def get_kr_popular() -> list[dict]:
        """네이버 실시간 인기검색 종목 (검색량 기준, 종목코드 포함)."""
        url = "https://finance.naver.com/sise/lastsearch2.naver"
        results: list[dict] = []
        logger.info("네이버 인기검색 종목 크롤링 시작")
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", {"class": "type_5"})
            if not table:
                logger.warning("인기검색 테이블 미발견")
                return results
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 12:
                    continue
                name = cols[1].get_text(strip=True)
                if not name or name == "종목명":
                    continue
                a = cols[1].find("a")
                code = StockDataCollector._code_from_href(a.get("href")) if a else None
                entry = {
                    "종목명": name,
                    "검색비율(%)": cols[2].get_text(strip=True),
                    "현재가": cols[3].get_text(strip=True),
                    "등락률": cols[5].get_text(strip=True),
                    "거래량": cols[6].get_text(strip=True),
                    "PER": cols[10].get_text(strip=True),
                    "PBR": cols[11].get_text(strip=True),
                }
                if code:
                    entry["_code"] = code
                results.append(entry)
        except Exception as e:
            logger.error(f"인기검색 종목 크롤링 에러: {e}")
        return results[:10]

    @staticmethod
    def get_kr_stock_detail(code: str) -> dict:
        """네이버 종목 상세: PER/EPS/PBR/BPS/배당수익률·투자의견/목표주가·52주고저·동일업종PER·최근뉴스."""
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        detail: dict = {}
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            t_opinion = soup.find("table", {"summary": "투자의견 정보"})
            if t_opinion:
                ems = t_opinion.find_all("em")
                if len(ems) >= 4:
                    grade = ems[0].next_sibling
                    grade_text = grade.strip() if isinstance(grade, str) else ""
                    score = ems[0].get_text(strip=True)
                    if score:
                        detail["투자의견(컨센서스)"] = f"{score} {grade_text}".strip()
                    if ems[1].get_text(strip=True):
                        detail["목표주가(컨센서스)"] = ems[1].get_text(strip=True)
                    if ems[2].get_text(strip=True):
                        detail["52주최고"] = ems[2].get_text(strip=True)
                    if ems[3].get_text(strip=True):
                        detail["52주최저"] = ems[3].get_text(strip=True)

            t_per = soup.find("table", {"summary": "PER/EPS 정보"})
            if t_per:
                ems = t_per.find_all("em")
                labels = ["PER", "EPS", "추정PER(컨센서스)", "추정EPS(컨센서스)", "PBR", "BPS", "배당수익률(%)"]
                for lbl, em in zip(labels, ems):
                    v = em.get_text(strip=True)
                    if v:
                        detail[lbl] = v

            t_sector = soup.find("table", {"summary": "동일업종 PER 정보"})
            if t_sector:
                ems = t_sector.find_all("em")
                if ems and ems[0].get_text(strip=True):
                    detail["동일업종PER"] = ems[0].get_text(strip=True)
                pct = t_sector.find(string=lambda s: s and "%" in s)
                if pct:
                    detail["동일업종등락률"] = pct.strip()

            news: list[dict] = []
            seen_titles: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "news_read.naver" in href and f"code={code}" in href:
                    title = a.get_text(strip=True)
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        link = href if href.startswith("http") else f"https://finance.naver.com{href}"
                        news.append({"제목": title, "링크": link})
                if len(news) >= 3:
                    break
            if news:
                detail["최근뉴스"] = news
        except Exception as e:
            logger.error(f"{code} 종목 상세 크롤링 에러: {e}")
        return detail

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

    # 미국 대형·인기 종목 워치리스트 (검색 유입이 잦은 종목 위주) — 이 중 당일 등락폭이 큰 종목을 선정
    _US_WATCHLIST = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX", "AVGO",
        "PLTR", "COIN", "MSTR", "SMCI", "JPM", "V", "UNH", "XOM", "WMT", "BRK-B",
    ]

    @staticmethod
    def get_us_movers() -> list[dict]:
        """워치리스트 내 미국 종목의 당일 등락률·펀더멘털·애널리스트 컨센서스(실데이터)."""
        results: list[dict] = []
        logger.info("미국 종목 워치리스트 등락률 수집 시작")
        for ticker in StockDataCollector._US_WATCHLIST:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="6mo")
                if hist.empty or len(hist) < 2:
                    continue
                closes = hist["Close"]
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                chg = (current - prev) / prev * 100

                info = {}
                try:
                    info = stock.info or {}
                except Exception:
                    pass

                entry = {
                    "종목명": info.get("shortName") or ticker,
                    "티커": ticker,
                    "현재가(USD)": round(current, 2),
                    "등락률(%)": round(chg, 2),
                    "거래량": int(hist["Volume"].iloc[-1]),
                }
                pe = info.get("trailingPE")
                if isinstance(pe, (int, float)):
                    entry["PER"] = round(pe, 2)
                pb = info.get("priceToBook")
                if isinstance(pb, (int, float)):
                    entry["PBR"] = round(pb, 2)
                mc = info.get("marketCap")
                if isinstance(mc, (int, float)) and mc > 0:
                    entry["시가총액(USD)"] = mc
                hi = info.get("fiftyTwoWeekHigh")
                lo = info.get("fiftyTwoWeekLow")
                if isinstance(hi, (int, float)):
                    entry["52주최고(USD)"] = hi
                if isinstance(lo, (int, float)):
                    entry["52주최저(USD)"] = lo
                sector = info.get("sector")
                if sector:
                    entry["섹터"] = sector
                # 애널리스트 컨센서스(실데이터) — 목표주가·투자의견
                tgt = info.get("targetMeanPrice")
                if isinstance(tgt, (int, float)) and tgt > 0:
                    entry["목표주가평균(USD, 컨센서스)"] = round(tgt, 2)
                tgt_hi = info.get("targetHighPrice")
                tgt_lo = info.get("targetLowPrice")
                if isinstance(tgt_hi, (int, float)):
                    entry["목표주가상단(USD)"] = round(tgt_hi, 2)
                if isinstance(tgt_lo, (int, float)):
                    entry["목표주가하단(USD)"] = round(tgt_lo, 2)
                rec = info.get("recommendationKey")
                if rec and rec != "none":
                    entry["투자의견(컨센서스)"] = rec
                n_analysts = info.get("numberOfAnalystOpinions")
                if isinstance(n_analysts, (int, float)) and n_analysts > 0:
                    entry["애널리스트수"] = int(n_analysts)

                results.append(entry)
            except Exception as e:
                logger.warning(f"{ticker} 수집 실패: {e}")

        results.sort(key=lambda r: abs(r.get("등락률(%)", 0)), reverse=True)
        return results

    @staticmethod
    def pick_featured_stock(recent_names: set[str] | None = None, history_len: int = 0) -> dict | None:
        """검색량 상위 / 급등락 상위(국내·미국)를 순환하며 오늘의 심층분석 대상 1종목을 선정."""
        recent_names = recent_names or set()
        mode = history_len % 3
        candidates: list[dict] = []
        market = "국내"

        if mode == 0:
            candidates = StockDataCollector.get_kr_popular()
            for c in candidates:
                c["선정사유"] = f"네이버 실시간 인기검색 상위(검색비율 {c.get('검색비율(%)', '-')})"
        elif mode == 1:
            market = "미국"
            candidates = StockDataCollector.get_us_movers()
            for c in candidates:
                c["선정사유"] = "관심 종목군 내 당일 등락률 상위"
        else:
            ups = StockDataCollector.get_today_upper_limit()
            downs = StockDataCollector.get_today_lower_limit()
            for c in ups:
                c["선정사유"] = "코스피·코스닥 상한가"
            for c in downs:
                c["선정사유"] = "코스피·코스닥 하한가"
            candidates = ups + downs

        if not candidates:
            logger.warning(f"모드 {mode}({market}) 후보 없음 — 대체 소스로 폴백")
            candidates = StockDataCollector.get_kr_popular()
            for c in candidates:
                c["선정사유"] = f"네이버 실시간 인기검색 상위(검색비율 {c.get('검색비율(%)', '-')})"
            market = "국내"
        if not candidates:
            return None

        picked = None
        for c in candidates:
            if c.get("종목명") not in recent_names:
                picked = c
                break
        if picked is None:
            picked = candidates[0]

        picked = dict(picked)
        picked["시장"] = market

        # 국내 종목이면 상세 페이지(펀더멘털·투자의견·목표주가·최근뉴스)로 보강
        # _code는 차트 생성(yfinance 티커 조립)용으로 남겨두고, LLM 프롬프트 빌드 시에만 제외한다.
        code = picked.get("_code")
        if market == "국내" and code:
            try:
                detail = StockDataCollector.get_kr_stock_detail(code)
                picked.update(detail)
            except Exception as e:
                logger.warning(f"{picked.get('종목명')} 상세 보강 실패(무시): {e}")

        return picked

    @staticmethod
    def collect(topic_id: str) -> dict | list | None:
        """topic_id별 팩트 데이터 수집."""
        collectors = {
            "etf포트폴리오": StockDataCollector.get_core_etf_data,
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
