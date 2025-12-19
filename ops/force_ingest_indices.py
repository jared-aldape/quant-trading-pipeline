import sys
import duckdb
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("ForceIngest")

# CONFIGURATION
# Yahoo allows ~60 days of 5m data history
DAYS_TO_BACKFILL = 60 
SYMBOLS = [("XSP", "^XSP"), ("VIX", "^VIX"), ("SPX", "^GSPC")]

def resample_to_1m(df_5m):
    """Interpolates 5m data into 1m data."""
    if df_5m.empty: return pd.DataFrame()
    
    # Ensure index is datetime
    if not isinstance(df_5m.index, pd.DatetimeIndex):
        df_5m.index = pd.to_datetime(df_5m.index)

    start_time = df_5m.index.min()
    end_time = df_5m.index.max() + timedelta(minutes=4)
    full_idx = pd.date_range(start=start_time, end=end_time, freq='1min')
    
    # Reindex
    df_1m = df_5m.reindex(full_idx)
    
    # Interpolate Prices
    cols_to_smooth = ['open', 'high', 'low', 'close']
    existing_cols = [c for c in cols_to_smooth if c in df_1m.columns]
    
    if existing_cols:
        df_1m[existing_cols] = df_1m[existing_cols].interpolate(method='time')
    
    # Distribute Volume
    if 'volume' in df_1m.columns:
        df_1m['volume'] = df_1m['volume'].fillna(0) / 5.0
        
    return df_1m.dropna()

def clean_df(df, ticker):
    if df.empty: return pd.DataFrame()
    
    # Reset Index to make datetime a column
    df = df.reset_index()
    
    # Rename Date Col
    if 'index' in df.columns: df.rename(columns={'index': 'datetime_utc'}, inplace=True)
    if 'date' in df.columns: df.rename(columns={'date': 'datetime_utc'}, inplace=True)
    if 'datetime' in df.columns: df.rename(columns={'datetime': 'datetime_utc'}, inplace=True)
    
    # --- TIMEZONE TRAP ---
    # 1. Force Naive first to inspect the raw hour
    if df['datetime_utc'].dt.tz is not None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(None)
        
    first_hour = df.iloc[0]['datetime_utc'].hour
    
    # 2. Logic: If hour is 9 (9:30 AM), it's NY time. We need UTC (14:30).
    if first_hour == 9:
        # log.warning(f"   ⚠️ Detected NY Time ({first_hour}:XX). Shifting +5 Hours to UTC...")
        df['datetime_utc'] = df['datetime_utc'] + timedelta(hours=5)
    elif first_hour == 6: # Pre-market
         # log.warning(f"   ⚠️ Detected Early NY Time ({first_hour}:XX). Shifting +5 Hours to UTC...")
         df['datetime_utc'] = df['datetime_utc'] + timedelta(hours=5)

    df['ticker'] = ticker
    
    # Ensure Schema
    required = ['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']
    for c in required:
        if c not in df.columns: df[c] = 0.0
        
    return df[required].copy()

def fetch_yahoo_day(internal_ticker, yahoo_ticker, date_str):
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    try:
        # Fetch 5m data
        df_5m = yf.download(yahoo_ticker, start=start_dt, end=end_dt, interval="5m", progress=False, auto_adjust=True)
        
        if not df_5m.empty:
            # --- FIX: NORMALIZE COLUMNS IMMEDIATELY ---
            if isinstance(df_5m.columns, pd.MultiIndex):
                try: df_5m.columns = df_5m.columns.get_level_values(0)
                except: pass
            
            df_5m.columns = [c.lower() for c in df_5m.columns]
            
            # log.info(f"   ✅ Yahoo (5m) Success. Synthesizing...")
            df_1m = resample_to_1m(df_5m)
            return clean_df(df_1m, internal_ticker)
            
    except Exception as e:
        log.error(f"   ❌ Yahoo Failed for {internal_ticker}: {e}")
        
    return pd.DataFrame()

def run_bulk_backfill():
    if not config.DB_FILE.exists(): return

    con = duckdb.connect(str(config.DB_FILE))
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=DAYS_TO_BACKFILL)
    
    log.info(f"🚀 STARTING BULK BACKFILL: {start_date} to {end_date} ({DAYS_TO_BACKFILL} days)")
    
    total_ingested = 0
    current_date = start_date
    
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip Weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
            
        print(f"📅 Processing {date_str}...", end="\r")
        
        # Atomic Wipe for this day
        con.execute(f"DELETE FROM {config.TBL_INDICES} WHERE CAST(datetime_utc AS DATE) = '{date_str}'")
        
        day_rows = 0
        for internal, yahoo in SYMBOLS:
            df = fetch_yahoo_day(internal, yahoo, date_str)
            if not df.empty:
                con.register('temp_df', df)
                con.execute(f"INSERT INTO {config.TBL_INDICES} SELECT * FROM temp_df")
                con.unregister('temp_df')
                day_rows += len(df)
        
        total_ingested += day_rows
        current_date += timedelta(days=1)
            
    con.close()
    print(f"\n🎉 BULK OPERATION COMPLETE. Ingested {total_ingested} rows.")

if __name__ == "__main__":
    run_bulk_backfill()