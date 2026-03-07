import pandas as pd
import numpy as np
import sys
import json
from pathlib import Path

# ==============================================================================
# 1. CONFIGURATION & CACHING
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

log = get_logger("FractalStrat")
PARAMS_FILE = ROOT_DIR / "data" / "strat_params.json"

# MEMORY CACHE: Prevents Disk I/O thrashing
_STRAT_PARAMS_CACHE = None 

# ==============================================================================
# 2. INDICATOR MATH (The Physics) - Zero-Copy Optimizations
# ==============================================================================
def calculate_macd(df, close_col='close', fast=12, slow=26, signal=9):
    """Calculates Standard MACD & Histogram. (Zero-Copy)"""
    if df.empty: return df
    
    ema_fast = df[close_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[close_col].ewm(span=slow, adjust=False).mean()
    
    df['macd'] = ema_fast - ema_slow
    # ⚡ FIX: Renamed from 'signal' to 'macd_signal' to prevent column collision
    df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    df['hist'] = df['macd'] - df['macd_signal']
    
    return df

def calculate_rsi(df, close_col='close', period=14):
    """Calculates RSI. (Zero-Copy)"""
    if df.empty: return df
    
    delta = df[close_col].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

# ==============================================================================
# 3. DYNAMIC PARAMETER LOADER (Optimized)
# ==============================================================================
def get_strategy_params(force_reload=False):
    """Loads strategy params with in-memory caching to eliminate Disk I/O overhead."""
    global _STRAT_PARAMS_CACHE
    defaults = {"rsi_floor": 20, "rsi_ceil": 80}
    
    if _STRAT_PARAMS_CACHE is not None and not force_reload:
        return _STRAT_PARAMS_CACHE

    if not PARAMS_FILE.exists(): 
        _STRAT_PARAMS_CACHE = defaults
        return defaults
        
    try:
        with open(PARAMS_FILE, 'r') as f: 
            _STRAT_PARAMS_CACHE = json.load(f)
            return _STRAT_PARAMS_CACHE
    except: 
        _STRAT_PARAMS_CACHE = defaults
        return defaults

# ==============================================================================
# 4. FRACTAL LOGIC (The Core)
# ==============================================================================
def apply_fractal_logic(vix_1m, xsp_1m):
    """
    Applies the VIX Fractal Strategy with Change Detection and High-Speed Merges.
    """
    if vix_1m.empty or xsp_1m.empty: return pd.DataFrame()
    
    # 1. Load Params (Instantly from RAM)
    params = get_strategy_params()
    RSI_FLOOR = params.get('rsi_floor', 20)
    RSI_CEIL = params.get('rsi_ceil', 80)
    
    # Only log once per session to avoid console spam in large backtests
    if not hasattr(apply_fractal_logic, "logged"):
        log.info(f"⚙️ Strategy Active: RSI {RSI_FLOOR}/{RSI_CEIL}")
        apply_fractal_logic.logged = True

    # 2. Prepare Base Data (Avoid blind sorting if already chronological)
    vix_df = vix_1m.copy()
    if not vix_df['datetime_utc'].is_monotonic_increasing:
        vix_df = vix_df.sort_values('datetime_utc')
    
    # MACRO (1 Hour)
    vix_1h = vix_df.set_index('datetime_utc').resample('1h').agg({'close': 'last'}).dropna().reset_index()
    calculate_macd(vix_1h, close_col='close') # Mutates in place (faster)
    
    # MICRO (5 Minute)
    vix_5m = vix_df.set_index('datetime_utc').resample('5min').agg({'close': 'last'}).dropna().reset_index()
    vix_5m.rename(columns={'close': 'close_vix'}, inplace=True)
    
    calculate_macd(vix_5m, close_col='close_vix') # Mutates in place
    calculate_rsi(vix_5m, close_col='close_vix')  # Mutates in place
    
    # 3. MERGE (The Alignment)
    df = pd.merge_asof(
        vix_5m, 
        vix_1h[['datetime_utc', 'hist']].rename(columns={'hist': 'macro_hist'}),
        on='datetime_utc', 
        direction='backward'
    )
    df.rename(columns={'hist': 'micro_hist', 'rsi': 'vix_rsi'}, inplace=True)
    
    # 4. SIGNAL GENERATION
    conditions = [
        # BULL FRACTAL
        (df['macro_hist'] <= 0) & (df['micro_hist'] <= 0) & (df['vix_rsi'] > RSI_FLOOR),
        # BEAR FRACTAL
        (df['macro_hist'] >= 0) & (df['micro_hist'] >= 0) & (df['vix_rsi'] < RSI_CEIL)
    ]
    
    df['raw_signal'] = np.select(conditions, [1, -1], default=0)
    
    # ⚡ INSTITUTIONAL FIX: The "Regime Flip" Detector
    # Only fire a signal when the state strictly changes from 0 to 1, or -1 to 1.
    # This prevents the engine from generating duplicate trades inside a chop box.
    df['prev_signal'] = df['raw_signal'].shift(1).fillna(0)
    
    signals = df[(df['raw_signal'] != 0) & (df['raw_signal'] != df['prev_signal'])].copy()
    
    if not signals.empty:
        # Rename raw_signal to signal for pipeline compatibility
        signals.rename(columns={'raw_signal': 'signal'}, inplace=True)
        signals.drop(columns=['prev_signal'], inplace=True)
        
        # 5. ATTACH XSP PRICE CONTEXT
        xsp_clean = xsp_1m[['datetime_utc', 'close']]
        if not xsp_clean['datetime_utc'].is_monotonic_increasing:
            xsp_clean = xsp_clean.sort_values('datetime_utc')
            
        signals = pd.merge_asof(signals, xsp_clean, on='datetime_utc', direction='backward')
    
    return signals