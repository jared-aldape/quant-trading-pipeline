import pandas as pd
import numpy as np
import sys
import json
from pathlib import Path

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

log = get_logger("FractalStrat")
PARAMS_FILE = ROOT_DIR / "data" / "strat_params.json"

# ==============================================================================
# 2. INDICATOR MATH (The Physics)
# ==============================================================================
def calculate_macd(df, close_col='close', fast=12, slow=26, signal=9):
    """Calculates Standard MACD & Histogram."""
    if df.empty: return df
    df = df.copy()
    
    # ⚡ FIX: Use specific column name
    ema_fast = df[close_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[close_col].ewm(span=slow, adjust=False).mean()
    
    df['macd'] = ema_fast - ema_slow
    df['signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    
    return df

def calculate_rsi(df, close_col='close', period=14):
    """Calculates RSI."""
    if df.empty: return df
    df = df.copy()
    
    delta = df[close_col].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

# ==============================================================================
# 3. DYNAMIC PARAMETER LOADER
# ==============================================================================
def get_strategy_params():
    defaults = {"rsi_floor": 20, "rsi_ceil": 80}
    if not PARAMS_FILE.exists(): return defaults
    try:
        with open(PARAMS_FILE, 'r') as f: return json.load(f)
    except: return defaults

# ==============================================================================
# 4. FRACTAL LOGIC (The Core)
# ==============================================================================
def apply_fractal_logic(vix_1m, xsp_1m):
    """
    Applies the VIX Fractal Strategy with DYNAMIC RSI Thresholds.
    Returns signals with 'close' (XSP) and 'close_vix' (VIX).
    """
    if vix_1m.empty or xsp_1m.empty: return pd.DataFrame()
    
    # 1. Load Dynamic Parameters
    params = get_strategy_params()
    RSI_FLOOR = params.get('rsi_floor', 20)
    RSI_CEIL = params.get('rsi_ceil', 80)
    log.info(f"⚙️ Strategy Active: RSI {RSI_FLOOR}/{RSI_CEIL}")

    # 2. Resample VIX
    # ⚡ FIX: '5min' instead of '5m' for Pandas 2.0+
    vix_df = vix_1m.copy().sort_values('datetime_utc')
    
    # MACRO (1 Hour)
    vix_1h = vix_df.set_index('datetime_utc').resample('1h').agg({'close': 'last'}).dropna().reset_index()
    vix_1h = calculate_macd(vix_1h, close_col='close')
    
    # MICRO (5 Minute)
    vix_5m = vix_df.set_index('datetime_utc').resample('5min').agg({'close': 'last'}).dropna().reset_index()
    
    # ⚡ FIX: Rename VIX Close NOW to prevent collision later
    vix_5m = vix_5m.rename(columns={'close': 'close_vix'})
    
    vix_5m = calculate_macd(vix_5m, close_col='close_vix')
    vix_5m = calculate_rsi(vix_5m, close_col='close_vix')
    
    # 3. MERGE (The Fractal)
    df = pd.merge_asof(
        vix_5m, 
        vix_1h[['datetime_utc', 'hist']].rename(columns={'hist': 'macro_hist'}),
        on='datetime_utc', 
        direction='backward'
    )

    df = df.rename(columns={'hist': 'micro_hist', 'rsi': 'vix_rsi'})
    
    # 4. SIGNAL GENERATION
    conditions = [
        # BULL (Calls)
        (df['macro_hist'] <= 0) & (df['micro_hist'] <= 0) & (df['vix_rsi'] > RSI_FLOOR),
        # BEAR (Puts)
        (df['macro_hist'] >= 0) & (df['micro_hist'] >= 0) & (df['vix_rsi'] < RSI_CEIL)
    ]
    
    choices = [1, -1]
    df['signal'] = np.select(conditions, choices, default=0)
    
    signals = df[df['signal'] != 0].copy()
    
    if not signals.empty:
        # 5. ATTACH XSP PRICE (Context)
        # We explicitly select 'close' from XSP so it keeps that name
        xsp_clean = xsp_1m[['datetime_utc', 'close']].sort_values('datetime_utc')
        signals = pd.merge_asof(signals, xsp_clean, on='datetime_utc', direction='backward')
    
    return signals