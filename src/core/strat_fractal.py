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
# 3. CORE STRATEGY LOGIC (The Decision)
# ==============================================================================
def apply_fractal_logic(vix_df, xsp_df):
    """
    The Master Logic Function called by engine_scanner.py.
    
    LOGIC:
    - MACRO: VIX 1H Histogram (Trend)
    - MICRO: VIX 5m Histogram (Entry)
    - TRIGGER: When BOTH are Negative -> BULL FRACTAL (VIX Dying -> Stocks Fly)
    - TRIGGER: When BOTH are Positive -> BEAR FRACTAL (VIX Spiking -> Stocks Die)
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
    # We map VIX states to XSP candles using 'merge_asof' (Backward look)
    # This prevents look-ahead bias. We only know the VIX state that *just happened*.
    
    df = xsp_df.sort_values('datetime_utc').copy()
    vix_1h = vix_1h.sort_values('datetime_utc')
    vix_5m = vix_5m.sort_values('datetime_utc')

    # 1. Attach Macro State
    df = pd.merge_asof(
        df, 
        vix_1h[['datetime_utc', 'hist']].rename(columns={'hist': 'macro_hist'}),
        on='datetime_utc', 
        direction='backward'
    )

    # 2. Attach Micro State
    df = pd.merge_asof(
        df, 
        vix_5m[['datetime_utc', 'hist', 'rsi']].rename(columns={'hist': 'micro_hist', 'rsi': 'vix_rsi'}),
        on='datetime_utc', 
        direction='backward'
    )

    # --- D. SIGNAL GENERATION ---
    # 1 = BULL FRACTAL (Call) | -1 = BEAR FRACTAL (Put) | 0 = NO SIGNAL
    
    conditions = [
        # SCENARIO A: VIX BREAKDOWN (Macro < 0 AND Micro < 0) -> BUY CALLS
        # Guardrail: Don't short VIX if RSI < 30 (Oversold/Bounce Risk)
        (df['macro_hist'] < 0) & (df['micro_hist'] < 0) & (df['vix_rsi'] > 30),
        
        # SCENARIO B: VIX BREAKOUT (Macro > 0 AND Micro > 0) -> BUY PUTS
        # Guardrail: Don't long VIX if RSI > 70 (Overbought/Cool-off Risk)
        (df['macro_hist'] > 0) & (df['micro_hist'] > 0) & (df['vix_rsi'] < 70)
    ]
    
    choices = [1, -1] # 1=Call, -1=Put
    
    df['raw_signal'] = np.select(conditions, choices, default=0)
    
    # --- E. CHANGE DETECTION (Pivot Points Only) ---
    # We only want the *moment* the regime flips, not every candle inside the trend.
    df['prev_signal'] = df['raw_signal'].shift(1)
    
    # Filter: Current is Signal (1/-1) AND Previous was different
    # This captures the entry point.
    signals = df[
        (df['raw_signal'] != 0) & 
        (df['raw_signal'] != df['prev_signal'])
    ].copy()
    
    # Formatting for Scanner
    signals.rename(columns={'raw_signal': 'signal'}, inplace=True)
    
    return signals[['datetime_utc', 'close', 'signal', 'macro_hist', 'micro_hist', 'vix_rsi']]