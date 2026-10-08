import json
from dataclasses import dataclass
from typing import Literal
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from config import config
from utils.logger import logger


@dataclass
class TradeSignal:
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float          # 0.0 - 1.0
    reasoning: str
    suggested_qty_pct: float   # % of available buying power to use
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    key_factors: list[str]
    stop_loss_pct: float
    take_profit_pct: float


SYSTEM_PROMPT = """You are an aggressive algorithmic stock trader focused on MAXIMIZING DAILY PROFITS.
You analyze technical indicators and news to find high-probability momentum trades during market hours.

Your mandate: Find and execute winning trades. Capital sitting idle earns nothing.

ENTRY RULES:
- BUY when 2+ of these align: MACD bullish, price above EMA9/21/50, RSI 40-65, volume spike >1.3x avg, positive news catalyst
- HIGH CONFIDENCE (0.75+): 3+ signals + volume confirms + positive news + clear breakout structure
- MEDIUM CONFIDENCE (0.65-0.74): 2 strong signals + one supporting factor (news or volume)
- MOMENTUM PLAY: Price above all EMAs + MACD bullish + RSI 50-65 = BUY with 0.68-0.75 confidence
- BREAKOUT: New high on above-average volume + MACD bullish = BUY with 0.72-0.80 confidence
- PULLBACK BUY: RSI 40-50 + price bouncing off EMA21/50 + MACD turning = 0.65-0.72 confidence

DO NOT HOLD when clear bullish signals are present. Capital must work.

AI/SEMICONDUCTOR sector (NVDA, AMD, MU, AVGO, PLTR, ARM, SMCI): Treat positive news as a strong catalyst. These are the highest-momentum names in 2026. Be more aggressive with entries.

RISK: Use 2-3% stop-loss, 5-8% take-profit for momentum plays. Minimum 1:2 R/R.

You must respond with ONLY valid JSON:
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<one paragraph explaining your decision>",
  "suggested_qty_pct": <float 0.0-1.0, fraction of buying power to deploy>,
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
  "stop_loss_pct": <float, e.g. 0.03 for 3%>,
  "take_profit_pct": <float, e.g. 0.06 for 6%>
}"""


class ClaudeAnalyst:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-opus-5-5"
        self._trade_history: list[dict] = []   # In-memory learning context

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    def analyze(
        self,
        symbol: str,
        indicators: dict,
        news: list[str],
        portfolio_context: dict,
        current_positions: dict,
    ) -> TradeSignal:

        user_message = self._build_prompt(symbol, indicators, news, portfolio_context, current_positions)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = next(b.text for b in response.content if hasattr(b, "text")).strip()
        # Extract JSON object robustly — handles thinking preamble and markdown fences
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start:end + 1]
        data = json.loads(raw)

        signal = TradeSignal(
            symbol=symbol,
            action=data["action"],
            confidence=float(data["confidence"]),
            reasoning=data["reasoning"],
            suggested_qty_pct=float(data.get("suggested_qty_pct", 0.5)),
            risk_level=data.get("risk_level", "MEDIUM"),
            key_factors=data.get("key_factors", []),
            stop_loss_pct=float(data.get("stop_loss_pct", config.STOP_LOSS_PCT)),
            take_profit_pct=float(data.get("take_profit_pct", config.TAKE_PROFIT_PCT)),
        )

        color = "green" if signal.action == "BUY" else "red" if signal.action == "SELL" else "yellow"
        logger.info(
            f"[bold cyan]{symbol}[/] -> [bold {color}]{signal.action}[/] "
            f"confidence={signal.confidence:.0%} risk={signal.risk_level}"
        )
        logger.debug(f"{symbol} reasoning: {signal.reasoning}")

        return signal

    def record_trade_outcome(self, symbol: str, action: str, entry_price: float, exit_price: float, pnl_pct: float):
        """Feed trade outcomes back — Claude will see these in future analysis prompts."""
        self._trade_history.append({
            "symbol": symbol,
            "action": action,
            "entry": entry_price,
            "exit": exit_price,
            "pnl_pct": round(pnl_pct * 100, 2),
            "outcome": "PROFIT" if pnl_pct > 0 else "LOSS",
        })
        # Keep last 20 trades for context
        if len(self._trade_history) > 20:
            self._trade_history.pop(0)

    def _build_prompt(
        self,
        symbol: str,
        indicators: dict,
        news: list[str],
        portfolio: dict,
        positions: dict,
    ) -> str:
        history_block = ""
        if self._trade_history:
            history_block = f"\n\nRECENT TRADE HISTORY (learn from these):\n{json.dumps(self._trade_history[-10:], indent=2)}"

        existing_position = positions.get(symbol)
        position_block = ""
        if existing_position:
            position_block = f"\n\nEXISTING POSITION in {symbol}: {existing_position}"

        news_block = "\n".join(f"  - {h}" for h in news) if news else "  (no recent news)"

        return f"""Analyze {symbol} and decide: BUY / SELL / HOLD

TECHNICAL INDICATORS:
{json.dumps(indicators, indent=2)}

RECENT NEWS HEADLINES:
{news_block}

PORTFOLIO CONTEXT:
  Buying power available: ${portfolio.get('cash', 0):,.2f}
  Total portfolio value: ${portfolio.get('total_value', 0):,.2f}
  Daily P&L so far: {portfolio.get('daily_pnl_pct', 0):.2%}
  Positions held: {portfolio.get('num_positions', 0)}
{position_block}{history_block}

RULES:
- Only BUY if confidence >= {config.MIN_CONFIDENCE}
- Suggest stop_loss_pct between 0.01 and 0.05
- Suggest take_profit_pct = 1.5x to 3x the stop_loss_pct (good risk/reward)
- suggested_qty_pct should be lower for HIGH risk trades
- If already holding {symbol}, evaluate whether to add, hold, or exit

Respond with ONLY the JSON object. No other text."""
