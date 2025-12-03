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

def check_fractal_flow(vix_1h_df, vix_5m_df, timestamp):
    """
    Checks if the Fractal Flow conditions are met at a specific timestamp.
    
    Args:
        vix_1h_df (pd.DataFrame): 1-Hour resampled VIX data with MACD
        vix_5m_df (pd.DataFrame): 5-Minute resampled VIX data with MACD
        timestamp (pd.Timestamp): The current 1-minute bar timestamp
        
    Returns:
        dict: {'signal': bool, 'reason': str, ...}
    """
    
    # 1. ALIGNMENT (Get nearest prior closed bars)
    # We look for the 1H bar that closed just before or at current time
    # And the 5m bar that closed just before or at current time
    
    # Truncate timestamp to hour and 5min to find the relevant row
    ts_1h = timestamp.floor('1h')
    ts_5m = timestamp.floor('5min')
    
    if ts_1h not in vix_1h_df.index or ts_5m not in vix_5m_df.index:
        return {'signal': False, 'reason': 'Insufficient Data'}

    current_macro = vix_1h_df.loc[ts_1h]
    curr_micro = vix_5m_df.loc[ts_5m]
    
    # Need previous 5m bar to detect crossover
    # We step back 5 minutes
    prev_ts_5m = ts_5m - pd.Timedelta(minutes=5)
    if prev_ts_5m not in vix_5m_df.index:
         return {'signal': False, 'reason': 'Initializing Micro Trend'}
         
    prev_micro = vix_5m_df.loc[prev_ts_5m]

    # 2. MACRO CONDITION (The River)
    # VIX 1H MACD Histogram must be NEGATIVE (Red)
    # Negative VIX Momentum = Stabilizing Market (Bullish for Stocks)
    is_macro_aligned = current_macro['hist'] < 0

    # 3. MICRO CONDITION (The Ripple)
    # VIX 5m MACD Line crosses BELOW Signal Line (Bearish Cross)
    # This indicates an immediate volatility crush
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
        'macro_trend': "BEARISH VIX (Bullish SPX)" if is_macro_aligned else "BULLISH VIX",
        'micro_cross': is_micro_cross,
        'timestamp': timestamp,
        'reason': " | ".join(reason)
    }

def calculate_rsi(df, window=14):
    """
    Calculates Relative Strength Index (RSI).
    Used for overextension checks in the dashboards.
    """
    if df is None or df.empty: return df
    
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    ema_up = up.ewm(com=window-1, adjust=False).mean()
    ema_down = down.ewm(com=window-1, adjust=False).mean()
    
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    return df