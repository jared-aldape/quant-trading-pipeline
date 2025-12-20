import sys
import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("EngineAuditor")

def fetch_day_data(date_str):
    """
    Fetches 1-minute XSP candles for a specific target date (RTH Only).
    """
    if not config.DB_FILE.exists():
        log.error("Database not found.")
        return pd.DataFrame()

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # Construct RTH Window for the specific date
        dt = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # We need to handle timezone carefully. DB is UTC.
        # RTH is 09:30 - 16:00 ET.
        tz_ny = pytz.timezone('America/New_York')
        start_ny = tz_ny.localize(datetime.combine(dt, time(9, 30)))
        end_ny = tz_ny.localize(datetime.combine(dt, time(16, 0)))
        
        start_utc = start_ny.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        end_utc = end_ny.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        query = f"""
            SELECT datetime_utc, open, high, low, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'XSP' 
            AND datetime_utc >= '{start_utc}' 
            AND datetime_utc <= '{end_utc}'
            ORDER BY datetime_utc ASC
        """
        df = con.execute(query).df()
        con.close()
        
        if df.empty:
            log.warning(f"No XSP data found for {date_str}")
            return pd.DataFrame()
            
        return df
        
    except Exception as e:
        log.error(f"Audit Data Fetch Error: {e}")
        return pd.DataFrame()

def find_optimal_trades(df):
    """
    Reverse engineers the perfect CALL and PUT trades for the session.
    """
    if df.empty: return None

    df = df.reset_index(drop=True)
    
    # --- 1. OPTIMAL CALL (Long) ---
    # Logic: Find Global High -> Look back for Lowest Low before it
    idx_high = df['high'].idxmax()
    global_high = df.loc[idx_high, 'high']
    high_ts = df.loc[idx_high, 'datetime_utc']
    
    # Slice data BEFORE the high
    pre_high_df = df.iloc[:idx_high+1]
    
    if not pre_high_df.empty:
        idx_low = pre_high_df['low'].idxmin()
        entry_low = pre_high_df.loc[idx_low, 'low']
        entry_ts_call = pre_high_df.loc[idx_low, 'datetime_utc']
        call_gain = global_high - entry_low
    else:
        # Edge case: High is at open
        entry_low = global_high
        entry_ts_call = high_ts
        call_gain = 0.0

    # --- 2. OPTIMAL PUT (Short) ---
    # Logic: Find Global Low -> Look back for Highest High before it
    idx_low_global = df['low'].idxmin()
    global_low = df.loc[idx_low_global, 'low']
    low_ts = df.loc[idx_low_global, 'datetime_utc']
    
    # Slice data BEFORE the low
    pre_low_df = df.iloc[:idx_low_global+1]
    
    if not pre_low_df.empty:
        idx_high_entry = pre_low_df['high'].idxmax()
        entry_high = pre_low_df.loc[idx_high_entry, 'high']
        entry_ts_put = pre_low_df.loc[idx_high_entry, 'datetime_utc']
        put_gain = entry_high - global_low
    else:
        # Edge case: Low is at open
        entry_high = global_low
        entry_ts_put = low_ts
        put_gain = 0.0

    return {
        "call": {
            "type": "CALL",
            "entry_ts": entry_ts_call,
            "exit_ts": high_ts,
            "entry_px": entry_low,
            "exit_px": global_high,
            "points": call_gain
        },
        "put": {
            "type": "PUT",
            "entry_ts": entry_ts_put,
            "exit_ts": low_ts,
            "entry_px": entry_high,
            "exit_px": global_low,
            "points": put_gain
        }
    }

def run_audit(target_date=None):
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')
        
    log.info(f"🕵️ STARTING AUDIT FOR: {target_date}")
    
    df = fetch_day_data(target_date)
    if df.empty: return
    
    results = find_optimal_trades(df)
    
    if results:
        c = results['call']
        p = results['put']
        
        print("\n" + "="*40)
        print(f"💎 OPTIMAL TRUTH MANIFEST: {target_date}")
        print("="*40)
        print(f"📈 PERFECT CALL (Long)")
        print(f"   ENTRY: {c['entry_ts'].strftime('%H:%M:%S')} @ {c['entry_px']:.2f}")
        print(f"   EXIT:  {c['exit_ts'].strftime('%H:%M:%S')} @ {c['exit_px']:.2f}")
        print(f"   GAIN:  +{c['points']:.2f} pts")
        print("-" * 40)
        print(f"📉 PERFECT PUT (Short)")
        print(f"   ENTRY: {p['entry_ts'].strftime('%H:%M:%S')} @ {p['entry_px']:.2f}")
        print(f"   EXIT:  {p['exit_ts'].strftime('%H:%M:%S')} @ {p['exit_px']:.2f}")
        print(f"   GAIN:  +{p['points']:.2f} pts")
        print("="*40 + "\n")
        
        return results

if __name__ == "__main__":
    # Default to today, or pass a date string like '2025-12-18'
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_audit(date_arg)