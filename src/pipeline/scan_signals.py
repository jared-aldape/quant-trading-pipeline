import sys
import duckdb
import pandas as pd
import pandas_ta as ta
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SignalScanner")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
VIX_RSI_THRESHOLD = 30
VIX_RSI_PERIOD = 14
COOLDOWN_MINUTES = 30  # Prevent signal spam (only 1 signal every 30 mins)

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def fetch_intraday_data(ticker):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    query = f"""
        SELECT datetime_utc, close 
        FROM {config.TBL_INDICES} 
        WHERE ticker = '{ticker}' 
        ORDER BY datetime_utc ASC
    """
    try:
        df = con.execute(query).df()
        if not df.empty:
            df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
            if df['datetime_utc'].dt.tz is None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_UTC)
            else:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
    except Exception as e:
        log.error(f"Failed to fetch {ticker}: {e}")
        df = pd.DataFrame()
    finally:
        con.close()
    return df

def calculate_indicators(df):
    if df.empty: return df
    df['rsi'] = ta.rsi(df['close'], length=VIX_RSI_PERIOD)
    return df

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def scan_and_generate_manifest():
    log.info("📡 Scanning Intraday Data for Multiple Signals...")
    
    df_spx = fetch_intraday_data("SPX")
    df_vix = fetch_intraday_data("VIX")
    
    if df_spx.empty or df_vix.empty:
        log.error("❌ Missing Data. Run 'ingest_indices.py' first.")
        return

    df_vix = calculate_indicators(df_vix)
    
    df_merged = pd.merge_asof(
        df_vix.sort_values('datetime_utc'), 
        df_spx[['datetime_utc', 'close']].rename(columns={'close': 'spx_close'}).sort_values('datetime_utc'),
        on='datetime_utc',
        direction='backward'
    )
    
    signals = []
    # Track cooldowns PER DAY
    # Format: { date_obj: last_signal_timestamp }
    last_signal_times = {} 
    
    for i, row in df_merged.iterrows():
        if pd.isna(row['rsi']): continue
        
        is_signal = row['rsi'] < VIX_RSI_THRESHOLD
        
        if is_signal:
            trade_date = row['datetime_utc'].date()
            entry_time = row['datetime_utc']
            
            # --- COOLDOWN LOGIC ---
            # Check if we already fired a signal recently on this day
            last_time = last_signal_times.get(trade_date)
            
            if last_time:
                delta = (entry_time - last_time).total_seconds() / 60
                if delta < COOLDOWN_MINUTES:
                    continue # Skip (In Cooldown)

            # Valid Signal -> Add it
            xsp_est = row['spx_close'] / 10.0
            
            signals.append({
                'date': trade_date,
                'entry_timestamp_utc': int(entry_time.timestamp() * 1000),
                'signal_type': 'VIX_RSI_LONG',
                'xsp_price': xsp_est,
                'meta_data': f"VIX_RSI:{row['rsi']:.2f}"
            })
            
            # Update cooldown timer
            last_signal_times[trade_date] = entry_time

    # Write to Manifest
    if not signals:
        log.info("⚠️ No signals found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
    con.execute(f"""
        CREATE TABLE {config.TBL_MANIFEST} (
            date DATE,
            entry_timestamp_utc BIGINT,
            signal_type VARCHAR,
            xsp_price DOUBLE,
            meta_data VARCHAR
        )
    """)
    
    signals_df = pd.DataFrame(signals)
    con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM signals_df")
    
    log.info(f"💾 Manifest Updated: {len(signals)} Signals (Multi-Signal/Day Enabled).")
    con.close()

if __name__ == "__main__":
    scan_and_generate_manifest()