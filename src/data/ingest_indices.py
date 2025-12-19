import sys
import duckdb
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ==============================================================================
# 1. SETUP & ALIGNMENT
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IndexIngest")

# CONFIGURATION
# Yahoo allows ~60 days of 5m data history
LOOKBACK_DAYS = 30
SYMBOLS = [("XSP", "^XSP"), ("VIX", "^VIX"), ("SPX", "^GSPC")]

# ==============================================================================
# 2. DATA SYNTHESIS ENGINE (The "Bridge")
# ==============================================================================
def resample_to_1m(df_5m):
    """
    Mathematically smooths 5-minute candles into 1-minute candles.
    Used when Yahoo's 1-minute data (7-day limit) is unavailable.
    """
    if df_5m.empty: return pd.DataFrame()
    
    # 1. Ensure Time Index
    if not isinstance(df_5m.index, pd.DatetimeIndex):
        df_5m.index = pd.to_datetime(df_5m.index)

    # 2. Create Target Timeline (1m)
    start_time = df_5m.index.min()
    end_time = df_5m.index.max() + timedelta(minutes=4)
    full_idx = pd.date_range(start=start_time, end=end_time, freq='1min')
    
    # 3. Expand DataFrame
    df_1m = df_5m.reindex(full_idx)
    
    # 4. Interpolate Price (Linear Path)
    cols_to_smooth = ['open', 'high', 'low', 'close']
    existing_cols = [c for c in cols_to_smooth if c in df_1m.columns]
    if existing_cols:
        df_1m[existing_cols] = df_1m[existing_cols].interpolate(method='time')
    
    # 5. Distribute Volume (Even Split)
    if 'volume' in df_1m.columns:
        df_1m['volume'] = df_1m['volume'].fillna(0) / 5.0
        
    return df_1m.dropna()

def clean_df(df, ticker):
    """Standardizes columns and enforces UTC timestamps."""
    if df.empty: return pd.DataFrame()
    
    # Flatten MultiIndex (Common YF Artifact)
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
    
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    
    # Normalize Date Column
    for date_col in ['index', 'date', 'datetime']:
        if date_col in df.columns:
            df.rename(columns={date_col: 'datetime_utc'}, inplace=True)
            break
            
    # TIMEZONE TRAP: Fix Naive NY Times
    if df['datetime_utc'].dt.tz is not None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(None)
        
    first_hour = df.iloc[0]['datetime_utc'].hour
    # If 9:30 AM (09:00), it's NY Time. Shift to UTC (14:00).
    if first_hour == 9:
        # log.debug(f"   ⏱️ shifting NY time (+5h) for {ticker}")
        df['datetime_utc'] = df['datetime_utc'] + timedelta(hours=5)
    elif first_hour == 6: # Pre-market 6:30 AM
        df['datetime_utc'] = df['datetime_utc'] + timedelta(hours=5)

    df['ticker'] = ticker
    
    # Enforce Schema
    required = ['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']
    for c in required:
        if c not in df.columns: df[c] = 0.0
        
    return df[required].copy()

# ==============================================================================
# 3. FETCH LOGIC (Hybrid Mode)
# ==============================================================================
def fetch_day(internal_ticker, yahoo_ticker, target_date):
    """
    Smart Fetch: Tries 1m -> Fails -> Tries 5m + Synthesis.
    """
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)
    
    # STRATEGY A: 1-Minute (High Precision)
    # Only works for last 7 days
    try:
        df = yf.download(yahoo_ticker, start=start_dt, end=end_dt, interval="1m", progress=False, auto_adjust=True)
        if not df.empty:
            return clean_df(df, internal_ticker)
    except: pass

    # STRATEGY B: 5-Minute (Deep History)
    # Works for last 60 days
    try:
        df_5m = yf.download(yahoo_ticker, start=start_dt, end=end_dt, interval="5m", progress=False, auto_adjust=True)
        if not df_5m.empty:
            # log.info(f"   Using 5m Synthesis for {internal_ticker} on {target_date}")
            df_1m = resample_to_1m(df_5m)
            return clean_df(df_1m, internal_ticker)
    except: pass
    
    return pd.DataFrame()

# ==============================================================================
# 4. PIPELINE RUNNER
# ==============================================================================
def run_pipeline():
    if not config.DB_FILE.exists():
        log.error("❌ Database not found!")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Identify Missing Days (Audit)
    # We check the last 30 days for gaps
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    
    # Get existing dates from DB
    existing_dates = set()
    try:
        q = f"SELECT DISTINCT CAST(datetime_utc AS DATE) as d FROM {config.TBL_INDICES} WHERE datetime_utc >= '{start_date}'"
        res = con.execute(q).fetchall()
        existing_dates = {r[0] for r in res}
    except: pass # Table might not exist yet

    log.info(f"🔎 Scanning for gaps from {start_date} to {end_date}...")
    
    total_ingested = 0
    current_date = start_date
    
    while current_date <= end_date:
        # Skip Weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
            
        # If missing or it's TODAY (always refresh today), fetch it
        if current_date not in existing_dates or current_date == end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            # log.info(f"⚡ Backfilling {date_str}...")
            
            # Atomic Wipe (Prevent Duplicates)
            con.execute(f"DELETE FROM {config.TBL_INDICES} WHERE CAST(datetime_utc AS DATE) = '{date_str}'")
            
            day_count = 0
            for internal, yahoo in SYMBOLS:
                df = fetch_day(internal, yahoo, current_date)
                if not df.empty:
                    con.register('temp_idx', df)
                    con.execute(f"INSERT INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
                    con.unregister('temp_idx')
                    day_count += len(df)
            
            if day_count > 0:
                print(f"   ✅ Recovered {date_str}: {day_count} rows")
                total_ingested += day_count
            else:
                print(f"   ⚠️ No data available for {date_str}")
        
        current_date += timedelta(days=1)

    con.close()
    log.info(f"✅ INGESTION COMPLETE. Added {total_ingested} total rows.")

if __name__ == "__main__":
    run_pipeline()