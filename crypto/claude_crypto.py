"""Claude AI analyst tuned for crypto micro-trading (scalping)."""
import json
from dataclasses import dataclass
from typing import Literal
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential
from crypto.crypto_config import crypto_config
from utils.logger import logger


@dataclass
class CryptoSignal:
    pair: str
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    reasoning: str
    usdt_amount: float        # USDT to deploy
    stop_loss_pct: float
    take_profit_pct: float
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    key_factors: list[str]


SYSTEM_PROMPT = """You are an expert crypto micro-trader (scalper) specializing in short-term momentum trades on 1-minute candles.

Your edge: finding high-probability 1.5-2% moves using technical confluence on liquid pairs.

Rules you ALWAYS follow:
- Only trade when at least 3 indicators align
- Risk/reward must be at least 1:2 (stop_loss_pct * 2 <= take_profit_pct)
- Never chase — if a move already happened, HOLD
- Crypto is 24/7: consider session context (Asian/European/US overlap = higher volume)
- Higher volume = more reliable signals
- DOGE/MATIC are highly volatile — require confidence >= 0.75

Respond ONLY with valid JSON matching exactly:
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<concise 1-2 sentence explanation>",
  "usdt_amount_pct": <float 0.0-1.0, fraction of available USDT to use>,
  "stop_loss_pct": <float, e.g. 0.008 for 0.8%>,
  "take_profit_pct": <float, e.g. 0.016 for 1.6%>,
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "key_factors": ["factor1", "factor2", "factor3"]
}"""


class ClaudeCryptoAnalyst:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=crypto_config.ANTHROPIC_API_KEY)
        self.model = "claude-opus-4-5"
        self._trade_history: list[dict] = []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    def analyze(
        self,
        pair: str,
        indicators: dict,
        portfolio_usdt: float,
        open_positions: dict,
    ) -> CryptoSignal:

        prompt = self._build_prompt(pair, indicators, portfolio_usdt, open_positions)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)
        usdt_to_use = portfolio_usdt * float(data.get("usdt_amount_pct", 0.5))

        signal = CryptoSignal(
            pair=pair,
            action=data["action"],
            confidence=float(data["confidence"]),
            reasoning=data["reasoning"],
            usdt_amount=usdt_to_use,
            stop_loss_pct=float(data.get("stop_loss_pct", crypto_config.STOP_LOSS_PCT)),
            take_profit_pct=float(data.get("take_profit_pct", crypto_config.TAKE_PROFIT_PCT)),
            risk_level=data.get("risk_level", "MEDIUM"),
            key_factors=data.get("key_factors", []),
        )

        color = "green" if signal.action == "BUY" else "red" if signal.action == "SELL" else "yellow"
        logger.info(
            f"[bold]{pair}[/] -> [bold {color}]{signal.action}[/] "
            f"conf={signal.confidence:.0%} | {signal.reasoning[:80]}"
        )
        return signal

    def record_outcome(self, pair: str, action: str, entry: float, exit_price: float, pnl_pct: float):
        self._trade_history.append({
            "pair": pair, "action": action,
            "entry": entry, "exit": exit_price,
            "pnl_pct": round(pnl_pct * 100, 3),
            "result": "WIN" if pnl_pct > 0 else "LOSS",
        })
        if len(self._trade_history) > 30:
            self._trade_history.pop(0)

    def _build_prompt(self, pair: str, ind: dict, usdt: float, positions: dict) -> str:
        history = ""
        if self._trade_history:
            wins = sum(1 for t in self._trade_history if t["result"] == "WIN")
            history = (
                f"\n\nRECENT PERFORMANCE: {wins}/{len(self._trade_history)} wins "
                f"| last trades: {json.dumps(self._trade_history[-5:])}"
            )

        existing = positions.get(pair)
        pos_block = f"\n\nEXISTING POSITION: {existing}" if existing else ""

        factors = []
        rsi = ind.get("rsi", 50)
        if rsi < 30: factors.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 70: factors.append(f"RSI overbought ({rsi:.1f})")
        if ind.get("macd_bullish"): factors.append("MACD bullish crossover")
        if ind.get("trend_up"): factors.append("EMA trend up (9>21>50)")
        if ind.get("vol_ratio", 1) > 1.5: factors.append(f"Volume spike x{ind['vol_ratio']:.1f}")
        if ind.get("bb_pct", 0.5) < 0.1: factors.append("Price at lower Bollinger Band")
        if ind.get("bb_pct", 0.5) > 0.9: factors.append("Price at upper Bollinger Band")

        return f"""Micro-trade analysis for {pair}

CURRENT PRICE: ${ind.get('price', 0):,.6f}
1-MIN CHANGE: {ind.get('change_pct', 0):+.3f}%

KEY INDICATORS:
  RSI(14):      {ind.get('rsi', 50):.2f}
  MACD:         {ind.get('macd', 0):.6f}  Signal: {ind.get('macd_signal', 0):.6f}  Bullish: {ind.get('macd_bullish', False)}
  EMA 9/21/50:  {ind.get('ema_9', 0):.4f} / {ind.get('ema_21', 0):.4f} / {ind.get('ema_50', 0):.4f}
  BB %:         {ind.get('bb_pct', 0.5):.3f}  Width: {ind.get('bb_width', 0):.4f}
  Stoch K/D:    {ind.get('stoch_k', 50):.1f} / {ind.get('stoch_d', 50):.1f}
  ATR:          {ind.get('atr', 0):.6f}
  Vol ratio:    {ind.get('vol_ratio', 1):.2f}x avg
  Trend up:     {ind.get('trend_up', False)}
  OBV rising:   {ind.get('obv_rising', False)}

SIGNALS DETECTED: {factors if factors else ['No strong signals']}

PORTFOLIO: ${usdt:.2f} USDT available | {len(positions)} open positions{pos_block}{history}

MIN CONFIDENCE NEEDED: {crypto_config.MIN_CONFIDENCE}
Target R/R: 1:2 (stop_loss * 2 = take_profit)

Return JSON only."""
