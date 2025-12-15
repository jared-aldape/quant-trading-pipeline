import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import sys
from pathlib import Path
import pytz

# ==============================================================================
# 0. ENVIRONMENT SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

try:
    import src.core.strat_fractal as strategy
except ImportError:
    strategy = None

log = get_logger("SignalScanner")

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
TBL_MANIFEST = getattr(config, 'TBL_MANIFEST', 'option_signal_manifest')
TARGET_TICKER = 'XSP' 

# ==============================================================================
# 2. HELPER: RTH FILTER
# ==============================================================================
def filter_rth(df):
    """
    Filters DataFrame to Regular Trading Hours only (09:30 - 16:00 EST).
    Handles UTC conversion automatically to ensuring strict alignment.
    """
    if df.empty: return df
    
    # Ensure UTC awareness
    if df['datetime_utc'].dt.tz is None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC')
    
    # Convert to Eastern Time for strict Rule Check
    df_eastern = df.copy()
    df_eastern['dt_est'] = df_eastern['datetime_utc'].dt.tz_convert('US/Eastern')
    
    # Define RTH Limits (Strict)
    market_open = time(9, 30)
    market_close = time(16, 00)
    
    mask = (df_eastern['dt_est'].dt.time >= market_open) & (df_eastern['dt_est'].dt.time < market_close)
    
    df_rth = df[mask].copy()
    
    dropped = len(df) - len(df_rth)
    if dropped > 0:
        log.info(f"🧹 RTH Filter: Dropped {dropped} off-hours candles. (Remaining: {len(df_rth)})")
        
    return df_rth

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    """
    Main Entry Point:
    1. Fetches Market Data (XSP Index).
    2. FILTERS FOR RTH ONLY.
    3. Runs Fractal Strategy on ENTIRE HISTORY.
    4. PURGES old signals for relevant dates (De-Fragmentation).
    5. Writes ALL valid signals to Manifest.
    """
    log.info(f"📡 SCANNER: Initiating Historical Scan on {TARGET_TICKER}...")

    if not config.DB_FILE.exists():
        log.error("❌ DB File not found. Skipping scan.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    try:
        # 1. FETCH DATA (XSP Index)
        query = f"""
            SELECT datetime_utc, open, high, low, close, volume
            FROM {config.TBL_INDICES} 
            WHERE ticker = '{TARGET_TICKER}' 
            ORDER BY datetime_utc ASC
        """
        df = con.execute(query).df()
        
        if df.empty:
            log.warning(f"⚠️ No {TARGET_TICKER} data found in Vault. Cannot scan.")
            return

        # 2. APPLY RTH FILTER
        df = filter_rth(df)
        
        if df.empty:
            log.warning("⚠️ No data remaining after RTH filter.")
            return

        # 3. RUN STRATEGY (Vectorized)
        log.info(f"🧠 Analyzing {len(df)} RTH candles for Fractals...")
        
        # --- STRATEGY LOGIC ---
        df['sma_50'] = df['close'].rolling(50).mean()
        df['signal'] = 0
        df.loc[df['close'] > df['sma_50'], 'signal'] = 1 # BULL
        df.loc[df['close'] < df['sma_50'], 'signal'] = -1 # BEAR
        df['change'] = df['signal'].diff()
        
        # Identify Crossovers
        all_signals = df[df['change'] != 0].dropna()
        
        if all_signals.empty:
            log.info("💤 No signals detected in history.")
            return

        log.info(f"⚡ Detected {len(all_signals)} potential signals. Processing...")

        # 4. DE-FRAGMENTATION (Purge old signals for these specific dates)
        # This prevents duplicate/ghost signals if re-running the same day.
        
        unique_dates = all_signals['datetime_utc'].dt.date.unique()
        if len(unique_dates) > 0:
            date_list_str = "', '".join([str(d) for d in unique_dates])
            log.warning(f"🧹 PURGING Manifest for {len(unique_dates)} active dates to prevent fragmentation...")
            
            # Delete any existing entries for these dates before inserting new ones
            con.execute(f"DELETE FROM {TBL_MANIFEST} WHERE date IN ('{date_list_str}')")
            log.info("✅ Purge complete. Inserting fresh signals...")

        # 5. WRITE TO MANIFEST
        count = 0
        for i, row in all_signals.iterrows():
            if row['signal'] == 0: continue
            
            # Timestamp
            sig_dt = pd.to_datetime(row['datetime_utc'])
            ts_bigint = int(sig_dt.timestamp() * 1000)
            sig_date = sig_dt.date()
            
            # Type
            sig_name = "BULL_FRACTAL" if row['signal'] == 1 else "BEAR_FRACTAL"
            trade_type = 'CALL' if row['signal'] == 1 else 'PUT'
            price = float(row['close']) 
            
            meta = 'Fractal Crossover (RTH) | Status: HISTORICAL'
            alloc = 1.0
            
            # Insert
            vals = [ts_bigint, sig_date, sig_name, price, trade_type, meta, alloc]
            
            con.execute(f"""
                INSERT OR IGNORE INTO {TBL_MANIFEST} 
                (entry_timestamp_utc, date, signal_type, xsp_price, trade_type, meta_data, allocation_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, vals)
            
            count += 1
            
        log.info(f"✅ Successfully cataloged {count} signals to Manifest.")

    except Exception as e:
        log.error(f"❌ Scanner Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        con.close()