import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Claude AI
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Broker
    BROKER: str = os.getenv("BROKER", "ROBINHOOD").upper()

    # Robinhood
    ROBINHOOD_USERNAME: str = os.getenv("ROBINHOOD_USERNAME", "")
    ROBINHOOD_PASSWORD: str = os.getenv("ROBINHOOD_PASSWORD", "")
    ROBINHOOD_MFA_CODE: str = os.getenv("ROBINHOOD_MFA_CODE", "")

    # Webull
    WEBULL_EMAIL: str = os.getenv("WEBULL_EMAIL", "")
    WEBULL_PASSWORD: str = os.getenv("WEBULL_PASSWORD", "")
    WEBULL_TRADE_PIN: str = os.getenv("WEBULL_TRADE_PIN", "")
    WEBULL_DEVICE_ID: str = os.getenv("WEBULL_DEVICE_ID", "")

    # TD Ameritrade / Schwab
    TD_CLIENT_ID: str = os.getenv("TD_CLIENT_ID", "")
    TD_CLIENT_SECRET: str = os.getenv("TD_CLIENT_SECRET", "")
    TD_REDIRECT_URI: str = os.getenv("TD_REDIRECT_URI", "https://localhost:8080")
    TD_TOKEN_PATH: str = os.getenv("TD_TOKEN_PATH", "./td_token.json")
    TD_ACCOUNT_NUMBER: str = os.getenv("TD_ACCOUNT_NUMBER", "")

    # Bot behavior
    PAPER_TRADING: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"
    TRADE_INTERVAL_MINUTES: int = int(os.getenv("TRADE_INTERVAL_MINUTES", "15"))
    MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "10"))

    # Watchlist
    WATCHLIST: list[str] = [
        s.strip().upper()
        for s in os.getenv("WATCHLIST", "AAPL,TSLA,NVDA,AMZN,META,MSFT,SPY,QQQ").split(",")
        if s.strip()
    ]

    # Risk management
    MAX_POSITION_PCT: float = float(os.getenv("MAX_POSITION_PCT", "0.10"))
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.02"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0.03"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.06"))
    MIN_CONFIDENCE: float = float(os.getenv("MIN_CONFIDENCE", "0.65"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "./logs/bot.log")

    def validate(self) -> list[str]:
        errors = []
        if not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required")
        if self.BROKER == "ROBINHOOD":
            if not self.ROBINHOOD_USERNAME or not self.ROBINHOOD_PASSWORD:
                errors.append("ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD are required")
        elif self.BROKER == "WEBULL":
            if not self.WEBULL_EMAIL or not self.WEBULL_PASSWORD:
                errors.append("WEBULL_EMAIL and WEBULL_PASSWORD are required")
            if not self.WEBULL_TRADE_PIN:
                errors.append("WEBULL_TRADE_PIN is required")
        elif self.BROKER == "TDAMERITRADE":
            if not self.TD_CLIENT_ID or not self.TD_CLIENT_SECRET:
                errors.append("TD_CLIENT_ID and TD_CLIENT_SECRET are required")
        else:
            errors.append(f"Unknown broker: {self.BROKER}. Use ROBINHOOD, WEBULL, or TDAMERITRADE")
        return errors


config = Config()
