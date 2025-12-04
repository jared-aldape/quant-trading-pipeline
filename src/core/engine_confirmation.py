import yfinance as yf
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# ==============================================================================
# PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("MTC_Engine")

class ConfirmationEngine:
    def __init__(self, ticker="SPY"):
        self.ticker = ticker
        
    def _fetch_data(self, interval, period="5d"):
        """
        Fetches 'Glass' data (Yahoo) for real-time confirmation.
        """
        try:
            df = yf.Ticker(self.ticker).history(period=period, interval=interval)
            if df.empty: 
                return pd.DataFrame()
            return df
        except Exception as e:
            log.error(f"Data Fetch Error ({interval}): {e}")
            return pd.DataFrame()

    def _calculate_sma(self, df, window=50):
        """Calculates Simple Moving Average."""
        if df.empty: return None
        return df['Close'].rolling(window=window).mean().iloc[-1]

    def _calculate_rsi(self, df, window=14):
        """Calculates RSI manually to avoid TA-Lib dependencies."""
        if df.empty: return None
        
        delta = df['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        
        ema_up = up.ewm(com=window-1, adjust=False).mean()
        ema_down = down.ewm(com=window-1, adjust=False).mean()
        
        rs = ema_up / ema_down
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]

    def check_trend_alignment(self):
        """
        Gatekeeper Law Part 1: Trend Filter.
        Checks if current price is above the 1H 50-SMA.
        Returns: (bool, reason_string)
        """
        df_1h = self._fetch_data(interval="1h", period="20d") # Need history for 50 SMA
        if df_1h.empty: return False, "Data Error (1H)"
        
        current_price = df_1h['Close'].iloc[-1]
        sma_50 = self._calculate_sma(df_1h, window=50)
        
        if sma_50 is None: return False, "Initializing SMA"

        # BULLISH CHECK (For Calls/Longs)
        is_bullish = current_price > sma_50
        
        status = "BULLISH" if is_bullish else "BEARISH"
        log.info(f"🛡️ Trend Check: Price ${current_price:.2f} vs SMA50 ${sma_50:.2f} [{status}]")
        
        return is_bullish, f"Trend is {status} (Price vs 1H SMA)"

    def check_momentum_health(self):
        """
        Gatekeeper Law Part 2: Momentum Filter.
        Checks if 15m RSI is healthy (not overbought/oversold).
        Returns: (bool, rsi_value)
        """
        df_15m = self._fetch_data(interval="15m", period="5d")
        if df_15m.empty: return False, 0.0
        
        rsi = self._calculate_rsi(df_15m)
        if rsi is None: return False, 0.0
        
        # Valid range: 30 to 70 (Avoid extremes)
        is_healthy = 30 < rsi < 70
        
        log.info(f"🛡️ Momentum Check: 15m RSI = {rsi:.2f}")
        
        return is_healthy, rsi

    def validate_signal(self):
        """
        Master Validation Function.
        """
        is_trend_ok, trend_msg = self.check_trend_alignment()
        is_rsi_ok, rsi_val = self.check_momentum_health()
        
        if is_trend_ok and is_rsi_ok:
            return {
                "valid": True,
                "reason": "CONFIRMED: Trend Aligned + RSI Healthy"
            }
        else:
            fail_reasons = []
            if not is_trend_ok: fail_reasons.append(f"Counter-Trend ({trend_msg})")
            if not is_rsi_ok: fail_reasons.append(f"RSI Extended ({rsi_val:.2f})")
            
            return {
                "valid": False,
                "reason": " | ".join(fail_reasons)
            }

if __name__ == "__main__":
    # Test Block
    engine = ConfirmationEngine()
    result = engine.validate_signal()
    print("\n--- MTC DIAGNOSTIC ---")
    print(f"RESULT: {result['valid']}")
    print(f"REASON: {result['reason']}")