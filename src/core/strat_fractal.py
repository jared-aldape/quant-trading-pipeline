import pandas as pd
import numpy as np
import sys
from pathlib import Path

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

log = get_logger("FractalStrat")

# ==============================================================================
# 2. INDICATOR MATH (The Physics)
# ==============================================================================
def calculate_macd(df, close_col='close', fast=12, slow=26, signal=9):
    """
    Calculates Standard MACD (12, 26, 9) & Histogram.
    """
    if df.empty: return df
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
    Calculates RSI (Relative Strength Index).
    """
    if df.empty: return df
    df = df.copy()
    
    delta = df[close_col].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

# ==============================================================================
# 3. CORE STRATEGY LOGIC (Synthetic-Aware)
# ==============================================================================
def apply_fractal_logic(vix_df, xsp_df):
    """
    The Master Logic Function calibrated for Quant OS v3.4 (Synthetic-Aware).
    
    LOGIC:
    - MACRO: VIX 1H Histogram (Trend)
    - MICRO: VIX 5m Histogram (Entry)
    - BULL FRACTAL (Call): Macro <= 0 AND Micro <= 0 (VIX dying/flat)
    - BEAR FRACTAL (Put): Macro >= 0 AND Micro >= 0 (VIX rising/flat)
    
    NOTE: Uses inclusive bounds (<=, >=) to handle flat data from linear interpolation.
    """
    if vix_df.empty or xsp_df.empty:
        return pd.DataFrame()

    # --- A. PREPARE MACRO (VIX 1H) ---
    vix_1h = vix_df.set_index('datetime_utc').resample('1h').agg({'close': 'last'}).dropna().reset_index()
    vix_1h = calculate_macd(vix_1h)
    
    # --- B. PREPARE MICRO (VIX 5m) ---
    vix_5m = vix_df.set_index('datetime_utc').resample('5m').agg({'close': 'last'}).dropna().reset_index()
    vix_5m = calculate_macd(vix_5m)
    vix_5m = calculate_rsi(vix_5m)

    # --- C. ALIGNMENT (The Merge) ---
    df = xsp_df.sort_values('datetime_utc').copy()
    vix_1h = vix_1h.sort_values('datetime_utc')
    vix_5m = vix_5m.sort_values('datetime_utc')

    # Attach Macro State
    df = pd.merge_asof(
        df, 
        vix_1h[['datetime_utc', 'hist']].rename(columns={'hist': 'macro_hist'}),
        on='datetime_utc', 
        direction='backward'
    )

    # Attach Micro State
    df = pd.merge_asof(
        df, 
        vix_5m[['datetime_utc', 'hist', 'rsi']].rename(columns={'hist': 'micro_hist', 'rsi': 'vix_rsi'}),
        on='datetime_utc', 
        direction='backward'
    )

    # --- D. SIGNAL GENERATION (SYNTHETIC-AWARE) ---
    # We allow equality (>=0, <=0) to handle perfectly flat synthetic candles found in backfills.
    
    conditions = [
        # SCENARIO A: BULL FRACTAL (VIX is dying or flat-negative)
        # Guardrail: RSI > 20 (Avoid bottom tick reversals)
        (df['macro_hist'] <= 0) & (df['micro_hist'] <= 0) & (df['vix_rsi'] > 20),
        
        # SCENARIO B: BEAR FRACTAL (VIX is rising or flat-positive)
        # Guardrail: RSI < 80 (Avoid top tick reversals)
        (df['macro_hist'] >= 0) & (df['micro_hist'] >= 0) & (df['vix_rsi'] < 80)
    ]
    
    choices = [1, -1] 
    
    df['raw_signal'] = np.select(conditions, choices, default=0)
    
    # --- E. CHANGE DETECTION (Pivot Points Only) ---
    df['prev_signal'] = df['raw_signal'].shift(1)
    
    # Filter for the exact moment the regime flips
    signals = df[
        (df['raw_signal'] != 0) & 
        (df['raw_signal'] != df['prev_signal'])
    ].copy()
    
    signals.rename(columns={'raw_signal': 'signal'}, inplace=True)
    
    return signals[['datetime_utc', 'close', 'signal', 'macro_hist', 'micro_hist', 'vix_rsi']]