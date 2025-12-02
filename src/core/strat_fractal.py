import pandas as pd
import numpy as np
from src.utils.logger import get_logger

# ==============================================================================
# STRATEGY DEFINITION: VIX FRACTAL FLOW
# ==============================================================================
# "The River and the Ripple"
# 1. Macro (River): 1H VIX MACD Histogram < 0 (Bearish Volatility = Bullish Market)
# 2. Micro (Ripple): 5m VIX MACD Line crosses BELOW Signal Line
# ==============================================================================

log = get_logger("FractalStrat")

def calculate_macd(df, close_col='close'):
    """
    Standard MACD (12, 26, 9).
    Returns DataFrame with 'macd', 'signal', and 'hist' columns.
    """
    if df is None or df.empty: return df
    
    # Copy to avoid SettingWithCopy warnings on slices
    df = df.copy()
    
    # Standard MACD Calculation
    df['ema12'] = df[close_col].ewm(span=12, adjust=False).mean()
    df['ema26'] = df[close_col].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    return df

def check_fractal_setup(vix_1h, vix_5m):
    """
    Evaluates the Fractal Flow conditions.
    
    Args:
        vix_1h (pd.DataFrame): 1-Hour VIX data (must contain 'hist')
        vix_5m (pd.DataFrame): 5-Minute VIX data (must contain 'macd', 'signal')
        
    Returns:
        dict: {
            'signal': bool,          # True if Triggered
            'macro_trend': str,      # 'BEARISH_VOL' (Good) or 'BULLISH_VOL' (Bad)
            'micro_cross': bool,     # True if 5m crossed down
            'reason': str            # Human readable explanation
        }
    """
    # 1. SAFETY CHECKS
    if vix_1h.empty or vix_5m.empty:
        return {'signal': False, 'reason': "Insufficient Data"}

    # 2. MACRO ANALYSIS (The River)
    # Condition: 1H MACD Histogram must be NEGATIVE (Red Bars)
    # This indicates Bearish Volatility Momentum -> Bullish Market conditions
    current_macro = vix_1h.iloc[-1]
    is_macro_aligned = current_macro['hist'] < 0
    
    macro_status = "BEARISH_VOL (SAFE)" if is_macro_aligned else "BULLISH_VOL (DANGER)"

    # 3. MICRO ANALYSIS (The Ripple)
    # We need at least 2 bars to detect a crossover (Previous vs Current)
    if len(vix_5m) < 2:
        return {'signal': False, 'reason': "Insufficient Micro Data"}

    curr_micro = vix_5m.iloc[-1]
    prev_micro = vix_5m.iloc[-2]

    # CROSSUNDER LOGIC:
    # Previous: MACD >= Signal (Yellow above Cyan)
    # Current:  MACD < Signal  (Yellow below Cyan)
    was_above = prev_micro['macd'] >= prev_micro['signal']
    is_below = curr_micro['macd'] < curr_micro['signal']
    
    is_micro_cross = was_above and is_below

    # 4. FINAL VERDICT
    # Both River and Ripple must align
    signal = is_macro_aligned and is_micro_cross
    
    reason = []
    if not is_macro_aligned: reason.append(f"Macro Disagreement (Hist: {current_macro['hist']:.2f})")
    if not is_micro_cross: reason.append("No Micro Crossover")
    if signal: reason.append("FRACTAL FLOW TRIGGER")

    return {
        'signal': signal,
        'macro_trend': macro_status,
        'micro_cross': is_micro_cross,
        'timestamp': curr_micro.name if hasattr(curr_micro, 'name') else None,
        'reason': " | ".join(reason)
    }

# ==============================================================================
# HELPER: RSI FILTER (Optional for v2.5+)
# ==============================================================================
def calculate_rsi(df, window=14):
    """
    Calculates Relative Strength Index (RSI).
    Used for overextension checks in the dashboards.
    """
    if df is None or df.empty: return df
    
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    ma_up = up.ewm(com=window-1, adjust=False, min_periods=window).mean()
    ma_down = down.ewm(com=window-1, adjust=False, min_periods=window).mean()
    
    rs = ma_up / ma_down
    df['rsi'] = 100 - (100 / (1 + rs))
    return df