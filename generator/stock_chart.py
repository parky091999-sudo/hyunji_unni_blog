"""
주식/ETF 가격 차트 이미지 생성 (matplotlib, 실제 시세 데이터만 사용).
"""
import logging
import os
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import yfinance as yf

logger = logging.getLogger("stock_chart")

_FONT_CANDIDATES = ["NanumGothic", "Malgun Gothic", "AppleGothic"]


def _set_korean_font():
    available = {f.name for f in fm.fontManager.ttflist}
    for name in _FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.family"] = name
            return


_set_korean_font()
plt.rcParams["axes.unicode_minus"] = False


def _save(fig) -> str:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="chart_")
    os.close(fd)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_comparison_chart(
    tickers: list[str], labels: dict[str, str] | None = None,
    period: str = "3mo", title: str = "",
) -> str | None:
    """여러 티커의 정규화(시작일=100) 가격 흐름을 한 차트에 비교."""
    labels = labels or {}
    try:
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        plotted = 0
        for ticker in tickers:
            try:
                hist = yf.Ticker(ticker).history(period=period)
                if hist.empty or len(hist) < 5:
                    continue
                closes = hist["Close"]
                normalized = closes / closes.iloc[0] * 100
                ax.plot(normalized.index, normalized.values, label=labels.get(ticker, ticker), linewidth=1.8)
                plotted += 1
            except Exception as e:
                logger.warning(f"{ticker} 차트 데이터 실패: {e}")
        if plotted == 0:
            plt.close(fig)
            return None
        ax.set_title(title or "최근 가격 흐름 비교 (시작일=100 기준)", fontsize=13)
        ax.set_ylabel("상대 수익률 (시작일=100)")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"비교 차트 생성 실패: {e}")
        return None


def generate_price_chart(ticker: str, label: str = "", period: str = "6mo") -> str | None:
    """단일 종목/ETF 가격 추이 + 20일 이동평균선."""
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty or len(hist) < 10:
            return None
        closes = hist["Close"]
        sma20 = closes.rolling(20).mean()

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        ax.plot(closes.index, closes.values, label=label or ticker, linewidth=1.8, color="#1f77b4")
        ax.plot(sma20.index, sma20.values, label="20일 이동평균", linewidth=1.2, color="#ff7f0e", linestyle="--")
        ax.set_title(f"{label or ticker} 최근 가격 추이", fontsize=13)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"{ticker} 가격 차트 생성 실패: {e}")
        return None
