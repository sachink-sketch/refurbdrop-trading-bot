import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from utils.logger import logger


class MarketDataFetcher:
    """Fetches OHLCV data and basic fundamentals using yfinance as the fallback source."""

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_ohlcv(
        self,
        symbol: str,
        period: str = "5d",
        interval: str = "5m",
    ) -> pd.DataFrame:
        """Return OHLCV dataframe for the given symbol."""
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data returned for {symbol}")
        df.index = df.index.tz_localize(None) if df.index.tzinfo is not None else df.index
        return df[["Open", "High", "Low", "Close", "Volume"]].rename(
            columns=str.lower
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_current_price(self, symbol: str) -> float:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        if price is None:
            hist = ticker.history(period="1d", interval="1m")
            if hist.empty:
                raise ValueError(f"Cannot get price for {symbol}")
            price = float(hist["Close"].iloc[-1])
        return float(price)

    def get_news_headlines(self, symbol: str, max_items: int = 5) -> list[str]:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            return [item.get("content", {}).get("title", "") or item.get("title", "") for item in news[:max_items]]
        except Exception as e:
            logger.warning(f"Could not fetch news for {symbol}: {e}")
            return []

    def get_fundamentals(self, symbol: str) -> dict:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "eps": info.get("trailingEps"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "avg_volume": info.get("averageVolume"),
                "sector": info.get("sector"),
            }
        except Exception as e:
            logger.warning(f"Could not fetch fundamentals for {symbol}: {e}")
            return {}

    def is_market_open(self) -> bool:
        now = datetime.now()
        # Simple US market hours check (9:30 AM - 4:00 PM ET, Mon-Fri)
        # For production, use a proper market calendar library
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close


market_data = MarketDataFetcher()
