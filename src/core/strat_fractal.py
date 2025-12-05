import pandas as pd
import numpy as np
import json
from pathlib import Path
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("FractalStrat")
PARAMS_FILE = config.DATA_DIR / "strat_params.json"

def load_params():
    """Loads the latest evolutionary parameters."""
    default = {
        "macro_bearish_threshold": -0.05,
        "macro_bullish_threshold": 0.05,
        "rsi_call_limit": 70,
        "rsi_put_limit": 30
    }
    if not PARAMS_FILE.exists(): return default
    try:
        with open(PARAMS_FILE, 'r') as f: return json.load(f)
    except: return default

def calculate_macd(df, close_col='close'):
    if df is None or df.empty: return df
    df = df.copy()
    df['ema12'] = df[close_col].ewm(span=12, adjust=False).mean()
    df['ema26'] = df[close_col].ewm(span=26, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal']
    return df

def calculate_rsi(df, window=14):
    if df is None or df.empty: return df
    df = df.copy()
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=window-1, adjust=False).mean()
    ema_down = down.ewm(com=window-1, adjust=False).mean()
    rs = ema_up / ema_down
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def check_fractal_flow(vix_1h_df, vix_5m_df, timestamp, rsi_val):
    """
    Checks for signals using Dynamic Evolutionary Parameters.
    """
    # LOAD DNA
    params = load_params()
    
    ts_1h = timestamp.floor('1h')
    ts_5m = timestamp.floor('5min')
    
    if ts_1h not in vix_1h_df.index or ts_5m not in vix_5m_df.index:
        return {'signal_type': None, 'reason': 'Data Gap'}

    current_macro = vix_1h_df.loc[ts_1h]
    curr_micro = vix_5m_df.loc[ts_5m]
    
    prev_ts_5m = ts_5m - pd.Timedelta(minutes=5)
    if prev_ts_5m not in vix_5m_df.index:
         return {'signal_type': None, 'reason': 'Initializing Micro'}
    prev_micro = vix_5m_df.loc[prev_ts_5m]

    # USE DYNAMIC THRESHOLDS
    macro_bearish_vix = current_macro['hist'] < params['macro_bearish_threshold']
    macro_bullish_vix = current_macro['hist'] > params['macro_bullish_threshold']
    
    cross_below = (prev_micro['macd'] >= prev_micro['signal']) and (curr_micro['macd'] < curr_micro['signal'])
    cross_above = (prev_micro['macd'] <= prev_micro['signal']) and (curr_micro['macd'] > curr_micro['signal'])

    rsi_safe_for_call = rsi_val < params['rsi_call_limit']
    rsi_safe_for_put = rsi_val > params['rsi_put_limit']

    signal_type = None
    reason = []

    if macro_bearish_vix and cross_below and rsi_safe_for_call:
        signal_type = 'call'
        reason.append(f"VIX CRUSH (Hist {current_macro['hist']:.2f} | RSI {rsi_val:.1f})")

    elif macro_bullish_vix and cross_above and rsi_safe_for_put:
        signal_type = 'put'
        reason.append(f"VIX SPIKE (Hist {current_macro['hist']:.2f} | RSI {rsi_val:.1f})")

    return {
        'signal_type': signal_type,
        'timestamp': timestamp,
        'reason': " | ".join(reason) if reason else "No Signal"
    }