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


SYSTEM_PROMPT = """You are an aggressive crypto scalper focused on MAXIMIZING DAILY PROFITS on 5-minute candles.

Your mandate: find and execute high-probability momentum trades. Be decisive. Capital sitting idle earns nothing.

ENTRY RULES:
- BUY when 2+ of these are true: MACD bullish, price above EMA9/21/50, RSI 40-75 (40-65 ideal, 65-75 = momentum zone), Stoch < 85 OR in strong uptrend, OBV rising, volume spike >1.2x
- HIGH CONFIDENCE (0.75+): 3+ signals align + volume confirms + clear structure
- MEDIUM CONFIDENCE (0.65-0.74): 2 strong signals (e.g. MACD bullish + price above all EMAs)
- MOMENTUM CONTINUATION: Price above all 3 EMAs + MACD bullish = valid BUY even with RSI 65-75 and Stoch 75-85. Rate this 0.65-0.72. This is a trending market, not reversal.
- OBV not rising is a CAUTION, not a veto. If price structure and MACD are bullish, trade with smaller size.
- PULLBACK ENTRY: RSI 40-55 + price above EMA50 + MACD turning bullish = buy the dip. Rate 0.65-0.72.
- RSI oversold (<35) OR Stoch K < 20: OVERSOLD BOUNCE. If also near lower BB or MACD turning bullish, rate 0.70-0.80. Price below EMAs is EXPECTED in an oversold bounce — it does NOT lower confidence.
- Stoch K < 10 = extremely oversold = HIGH priority bounce signal regardless of EMA position.

DO NOT HOLD when:
- Price above all 3 EMAs AND MACD bullish — this is a BUY setup, minimum 0.65 confidence
- Portfolio has room for new position
- Risk/reward is at least 1:1.5

RISK/REWARD: Minimum 1:1.5. Prefer 1:2. Use tight stops (0.6-1.0%) with 1.2-2.0% targets.

Respond ONLY with valid JSON:
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
        self.model = "claude-opus-5-5"
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
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next(b.text for b in response.content if hasattr(b, "text")).strip()
        # Extract JSON object robustly — handles thinking preamble and markdown fences
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start:end + 1]
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
        stoch_k = ind.get("stoch_k", 50)
        stoch_d = ind.get("stoch_d", 50)
        if rsi < 30: factors.append(f"RSI oversold ({rsi:.1f}) — bounce candidate")
        elif rsi > 70: factors.append(f"RSI overbought ({rsi:.1f})")
        if stoch_k < 20: factors.append(f"Stochastic OVERSOLD K={stoch_k:.1f} — strong bounce signal")
        elif stoch_k > 80: factors.append(f"Stochastic overbought K={stoch_k:.1f}")
        if stoch_k < 20 and stoch_k > stoch_d: factors.append("Stoch K crossing above D from oversold — BUY signal")
        if ind.get("macd_bullish"): factors.append("MACD bullish crossover")
        if ind.get("trend_up"): factors.append("EMA stack bullish (9>21>50)")
        # Price-vs-EMA signals (more relevant for 5-min scalping than EMA stacking order)
        above = sum([ind.get("price_above_ema9", False), ind.get("price_above_ema21", False), ind.get("price_above_ema50", False)])
        if above == 3: factors.append("Price above all EMAs (9/21/50) — bullish structure")
        elif above == 2: factors.append("Price above 2 of 3 EMAs — partial bullish")
        if ind.get("vol_ratio", 1) > 1.5: factors.append(f"Volume spike x{ind['vol_ratio']:.1f}")
        if ind.get("bb_pct", 0.5) < 0.15: factors.append("Price near lower Bollinger Band — potential bounce")
        if ind.get("bb_pct", 0.5) > 0.85: factors.append("Price near upper Bollinger Band — momentum or reversal zone")
        if ind.get("obv_rising"): factors.append("OBV rising — volume confirms move")

        return f"""Micro-trade analysis for {pair}

CURRENT PRICE: ${ind.get('price', 0):,.6f}
1-MIN CHANGE: {ind.get('change_pct', 0):+.3f}%

KEY INDICATORS:
  RSI(14):      {ind.get('rsi', 50):.2f}
  MACD:         {ind.get('macd', 0):.6f}  Signal: {ind.get('macd_signal', 0):.6f}  Bullish: {ind.get('macd_bullish', False)}
  EMA 9/21/50:  {ind.get('ema_9', 0):.4f} / {ind.get('ema_21', 0):.4f} / {ind.get('ema_50', 0):.4f}
  Price>EMA9:   {ind.get('price_above_ema9', False)}  Price>EMA21: {ind.get('price_above_ema21', False)}  Price>EMA50: {ind.get('price_above_ema50', False)}
  BB %:         {ind.get('bb_pct', 0.5):.3f}  Width: {ind.get('bb_width', 0):.4f}
  Stoch K/D:    {ind.get('stoch_k', 50):.1f} / {ind.get('stoch_d', 50):.1f}
  ATR:          {ind.get('atr', 0):.6f}
  Vol ratio:    {ind.get('vol_ratio', 1):.2f}x avg
  EMA stacked:  {ind.get('trend_up', False)}
  OBV rising:   {ind.get('obv_rising', False)}

SIGNALS DETECTED: {factors if factors else ['No strong signals']}

PORTFOLIO: ${usdt:.2f} USDT available | {len(positions)} open positions{pos_block}{history}

MIN CONFIDENCE NEEDED: {crypto_config.MIN_CONFIDENCE}
Target R/R: 1:2 (stop_loss * 2 = take_profit)

Return JSON only."""
