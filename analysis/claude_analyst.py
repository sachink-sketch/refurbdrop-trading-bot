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


SYSTEM_PROMPT = """You are an expert algorithmic stock trader and quantitative analyst.
You analyze market data, technical indicators, and news sentiment to make precise trading decisions.

Your role:
- Evaluate BUY / SELL / HOLD signals based on the data provided
- Be conservative and protect capital — only trade when the edge is clear
- Always consider the risk/reward ratio
- Provide confidence scores that reflect genuine conviction (not always high)

You must respond with ONLY valid JSON matching exactly this schema:
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
        self.model = "claude-opus-4-5"
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
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

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
