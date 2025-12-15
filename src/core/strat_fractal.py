import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

log = get_logger("FractalStrat")

def calculate_macd(df, close_col='close', fast=12, slow=26, signal=9):
    """
    Calculates Standard MACD (12, 26, 9).
    """
    df = df.copy()
    
    # 1. Fast & Slow EMAs
    ema_fast = df[close_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[close_col].ewm(span=slow, adjust=False).mean()
    
    # 2. MACD Line & Signal Line
    df['macd'] = ema_fast - ema_slow
    df['signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    
    # 3. Histogram (The Momentum)
    df['hist'] = df['macd'] - df['signal']
    
    return df

def calculate_rsi(df, close_col='close', window=14):
    """
    Calculates RSI (Relative Strength Index) using Wilder's Smoothing.
    """
    df = df.copy()
    delta = df[close_col].diff()
    
    # Separate gains and losses
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    # Wilder's Smoothing (Exponential Moving Average)
    avg_gain = gain.ewm(com=window - 1, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, min_periods=window).mean()
    
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Fill NaN initialization gaps with 50 (neutral) to prevent crashes
    df['rsi'] = df['rsi'].fillna(50.0)
    
    return df

def check_fractal_flow(vix_1h_df, vix_5m_df, ts_current, rsi_val):
    """
    Determines Strategy Signal based on VIX Fractal alignment.
    
    THEORY:
    - VIX DOWN -> SPX UP (BULL/CALLS)
    - VIX UP   -> SPX DOWN (BEAR/PUTS)
    """
    
    # --- TIMEZONE NORMALIZATION FIX ---
    # Ensure ts_current matches the timezone of vix_1h_df.index
    target_tz = vix_1h_df.index.tz
    
    if ts_current.tzinfo is not None and target_tz is None:
        # If current is Aware but index is Naive -> Make current Naive
        ts_current = ts_current.tz_localize(None)
    elif ts_current.tzinfo is None and target_tz is not None:
        # If current is Naive but index is Aware -> Make current Aware (UTC assumed)
        ts_current = ts_current.tz_localize('UTC')
    
    # 1. Align 1H Data (Macro View)
    # We find the 1H candle that contains the current 5m timestamp
    ts_1h_floor = ts_current.floor('1h')
    
    if ts_1h_floor not in vix_1h_df.index:
        # Fallback: take the last known 1H candle if exact match missing
        # searchsorted requires compatible timezones (which we fixed above)
        idx = vix_1h_df.index.searchsorted(ts_current)
        
        # Adjust index if it points beyond the end
        if idx >= len(vix_1h_df):
            idx = len(vix_1h_df) - 1
            
        if idx > 0:
            row_1h = vix_1h_df.iloc[idx - 1]
        else:
            return {'signal_type': None, 'reason': 'No Macro Data'}
    else:
        row_1h = vix_1h_df.loc[ts_1h_floor]

    # 2. Extract Metrics
    vix_1h_hist = row_1h['hist']  # Macro Momentum
    
    # Get current 5m row
    try:
        # We need to look up using the same timezone logic
        # If ts_current was modified above, it matches 1h index, 
        # but 5m index might be different (though scanner usually aligns them).
        # We try strict lookup first.
        if ts_current in vix_5m_df.index:
             row_5m = vix_5m_df.loc[ts_current]
        else:
            # Try naive version if exact match fails due to tz
            ts_naive = ts_current.tz_localize(None) if ts_current.tzinfo else ts_current
            if ts_naive in vix_5m_df.index:
                 row_5m = vix_5m_df.loc[ts_naive]
            else:
                 # Last resort: nearest
                 idx_5m = vix_5m_df.index.searchsorted(ts_current)
                 if idx_5m >= len(vix_5m_df): idx_5m = len(vix_5m_df) - 1
                 row_5m = vix_5m_df.iloc[idx_5m]

        vix_5m_hist = row_5m['hist'] # Micro Momentum
    except KeyError:
        return {'signal_type': None, 'reason': 'No Micro Data'}

    # 3. Signal Logic
    
    # --- SCENARIO A: VIX BREAKDOWN (SPX CALLS) ---
    # VIX 1H is cooling off AND VIX 5m is cooling off
    if vix_1h_hist < 0 and vix_5m_hist < 0:
        
        # RSI Guardrail: Don't short VIX if it's already on the floor (Mean Reversion Risk)
        if rsi_val < 20.0:
            return {'signal_type': None, 'reason': 'VIX_OVERSOLD_RISK'}
            
        return {
            'signal_type': 'BULL_FRACTAL', # Implies SPX CALL
            'reason': f"VIX_COOLING (1H:{vix_1h_hist:.2f}, 5m:{vix_5m_hist:.2f})"
        }

    # --- SCENARIO B: VIX BREAKOUT (SPX PUTS) ---
    # VIX 1H is heating up AND VIX 5m is heating up
    elif vix_1h_hist > 0 and vix_5m_hist > 0:
        
        # RSI Guardrail: Don't long VIX if it's hitting the roof (Mean Reversion Risk)
        if rsi_val > 80.0:
            return {'signal_type': None, 'reason': 'VIX_OVERBOUGHT_RISK'}
            
        return {
            'signal_type': 'BEAR_FRACTAL', # Implies SPX PUT
            'reason': f"VIX_HEATING (1H:{vix_1h_hist:.2f}, 5m:{vix_5m_hist:.2f})"
        }

    # --- NEUTRAL / CONFLICT ---
    return {'signal_type': None, 'reason': 'FRACTAL_CONFLICT'}