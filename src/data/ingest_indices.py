import sys
import duckdb
import yfinance as yf
import pandas as pd
import time
import json
import os
import requests
import numpy as np
from datetime import datetime, time as t_time, timedelta, timezone
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IndexIngest")
SNAPSHOT_FILE = ROOT_DIR / "data" / "live_snapshot.json"

# CONFIG FOR BACKUP
POLYGON_KEY = config.POLYGON_API_KEY
USE_POLYGON_BACKUP = True

class RobustEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.floating)): return float(obj)
        if isinstance(obj, (datetime, pd.Timestamp)): return obj.isoformat()
        return super(RobustEncoder, self).default(obj)

# ==============================================================================
# 2. QUALITY CONTROL
# ==============================================================================
def validate_and_clean(df, ticker):
    if df.empty: return df
    # Remove flat-line data (bad ticks)
    df['amp'] = (df['high'] - df['low']).abs()
    flat_mask = df['amp'] < 0.0001
    flat_count = flat_mask.sum()
    
    if flat_count > 0:
        clean_df = df[~flat_mask].copy()
        return clean_df.drop(columns=['amp'])
    
    return df.drop(columns=['amp'])

def check_cooldown():
    """Bypassed for manual refreshes."""
    return True

# ==============================================================================
# 3. FETCH ENGINES (STRICT UTC MODE)
# ==============================================================================
def fetch_polygon_backup(ticker):
    """
    Fallback method if Yahoo Fails. Fetches 1-minute aggregates.
    """
    if not POLYGON_KEY: return pd.DataFrame()
    poly_ticker = f"I:{ticker}" 
    log.info(f"🛡️ ACTIVATING BACKUP: Polygon.io ({poly_ticker})")
    
    try:
        # Always fetch last 2 days for backup
        end_dt = datetime.now(timezone.utc) - timedelta(minutes=16)
        start_dt = end_dt - timedelta(days=2)
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{poly_ticker}/range/1/minute/{int(start_dt.timestamp()*1000)}/{int(end_dt.timestamp()*1000)}"
        params = {"apiKey": POLYGON_KEY, "limit": 50000, "adjusted": "true"}
        
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        if data.get('status') != 'OK' or not data.get('results'): return pd.DataFrame()
            
        df = pd.DataFrame(data['results'])
        df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
        
        # 🛡️ POLYGON IS ALWAYS UTC -> Just Strip TZ
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms').dt.tz_localize('UTC').dt.tz_localize(None)
        
        df['ticker'] = ticker
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]
    except: return pd.DataFrame()

def fetch_yahoo_data(y_ticker, friendly_name, days=5, interval="1m"):
    """
    Primary Fetcher. Includes ROBUST UTC ENFORCEMENT to prevent 'Local Drift'.
    """
    start_date = datetime.now().date() - timedelta(days=days) 
    end_date = datetime.now().date() + timedelta(days=1)
    
    try:
        ticker_dat = yf.Ticker(y_ticker)
        # Fetch data with variable interval
        df = ticker_dat.history(start=start_date, end=end_date, interval=interval, auto_adjust=True)
        
        if df.empty: return pd.DataFrame()
        
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        
        # Normalize Date Column Name
        if 'date' in df.columns: df.rename(columns={"date": "datetime_utc"}, inplace=True)
        df.rename(columns={"datetime": "datetime_utc"}, inplace=True)
        
        df['ticker'] = friendly_name
        
        # 🛡️ CRITICAL FIX: FORCE UTC CONVERSION 🛡️
        # Yahoo often returns "America/New_York" (aware) or Local Time (naive) depending on the system.
        # We must standardize this before saving to DuckDB.
        
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
        
        if df['datetime_utc'].dt.tz is None:
            # Case A: Naive Timestamp (Likely Local Time or NY Time from YF)
            # We assume NY Time for market data to be safe, then convert to UTC.
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('America/New_York').dt.tz_convert('UTC')
        else:
            # Case B: Aware Timestamp (Convert directly to UTC)
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC')
            
        # 🛡️ FINAL STRIP: DuckDB prefers Naive UTC timestamps
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)
        
        if 'volume' not in df.columns: df['volume'] = 0
        
        # Select schema columns only
        schema_cols = ['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']
        df_clean = df[schema_cols].copy()
        
        return validate_and_clean(df_clean, friendly_name)
        
    except Exception as e:
        log.warning(f"⏳ Yahoo Fetch Issue ({friendly_name}): {str(e)[:100]}")
        return pd.DataFrame()

# ==============================================================================
# 4. SNAPSHOT (UI Support)
# ==============================================================================
def calculate_orb(df):
    if df.empty: return None, None
    df = df.copy()
    # Convert Naive UTC -> Aware UTC -> NY Time
    df['dt_ny'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    start = t_time(9, 30)
    end = t_time(10, 0)
    orb_df = df[(df['dt_ny'].dt.time >= start) & (df['dt_ny'].dt.time < end)]
    
    if len(orb_df) > 5:
        return orb_df['high'].max(), orb_df['low'].min()
    return None, None

def generate_snapshot_from_db(con):
    """
    Creates a JSON snapshot for the frontend to display without hitting DB.
    """
    try:
        max_ts = con.execute(f"SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = 'XSP'").fetchone()[0]
        if not max_ts: return
        
        current_time = datetime.now(timezone.utc)
        target_time = datetime.now() - timedelta(days=2) 
        
        q = f"SELECT * FROM {config.TBL_INDICES} WHERE datetime_utc >= '{target_time}' ORDER BY datetime_utc ASC"
        df_all = con.execute(q).df()
        
        xsp_df = df_all[df_all['ticker'] == 'XSP'].copy()
        vix_df = df_all[df_all['ticker'] == 'VIX'].copy()
        
        orb_h, orb_l = calculate_orb(xsp_df)
        
        snapshot = {
            "updated": current_time.isoformat(),
            "xsp": xsp_df.to_dict(orient='records'),
            "vix": vix_df.to_dict(orient='records'),
            "orb": {"h": orb_h, "l": orb_l}
        }
        
        with open(SNAPSHOT_FILE, 'w') as f:
            json.dump(snapshot, f, cls=RobustEncoder)
            
    except Exception as e:
        log.error(f"Snapshot Fail: {e}")

# ==============================================================================
# 5. EXECUTION
# ==============================================================================
def run_ingest(lookback_days=30):
    log.info(f"📊 STARTING INDEX INGESTION (Lookback: {lookback_days} days)...")
    staged = []
    targets = [('VIX', '^VIX'), ('XSP', '^XSP')]
    
    # PASS 1: HIGH PRECISION (1m, last 5 days)
    for friendly, y_ticker in targets:
        df = fetch_yahoo_data(y_ticker, friendly, days=5, interval="1m")
        if df.empty and USE_POLYGON_BACKUP:
            df = fetch_polygon_backup(friendly)
        
        if not df.empty: staged.append(df)

    # PASS 2: DEEP HISTORY (5m, last 59 days)
    if lookback_days > 7:
        log.info("   ⏳ Fetching Deep History (5m)...")
        for friendly, y_ticker in targets:
            # Yahoo limit for 5m data is ~60 days. We clip lookback to 59.
            fetch_days = min(lookback_days, 59)
            df_hist = fetch_yahoo_data(y_ticker, friendly, days=fetch_days, interval="5m")
            if not df_hist.empty: staged.append(df_hist)
    
    # DB COMMIT
    if config.DB_FILE.exists():
        try:
            con = duckdb.connect(str(config.DB_FILE), config={'access_mode': 'READ_WRITE'})
            con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (datetime_utc TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, ticker VARCHAR, PRIMARY KEY (datetime_utc, ticker))")
            
            if staged:
                for df in staged:
                    con.register('temp_idx', df)
                    # INSERT OR IGNORE protects the high-res 1m data from being overwritten by 5m data
                    con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
                    con.unregister('temp_idx')
                
                log.info(f"✅ Ingested {len(staged)} batches.")

            generate_snapshot_from_db(con)
            con.close()
            
        except Exception as e:
            log.error(f"DB Write Error: {e}")

if __name__ == "__main__":
    run_ingest(lookback_days=30)