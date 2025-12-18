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
LOCK_FILE = ROOT_DIR / ".ingest_cooldown"
COOLDOWN_SECONDS = 30 

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
    """
    [CRITICAL GATEKEEPER]
    Filters out 'Flat' candles (High == Low) which corrupt the signals.
    """
    if df.empty: return df
    
    # Calculate amplitude
    df['amp'] = (df['high'] - df['low']).abs()
    
    # Identify flat rows (floating point tolerance)
    flat_mask = df['amp'] < 0.0001
    flat_count = flat_mask.sum()
    
    if flat_count > 0:
        log.warning(f"⚠️ {ticker}: Filtering {flat_count} flat snapshots to preserve wicks.")
        # Return only healthy rows
        clean_df = df[~flat_mask].copy()
        return clean_df.drop(columns=['amp'])
    
    return df.drop(columns=['amp'])

def check_cooldown():
    """Prevents spamming if run frequently by the launcher."""
    now = time.time()
    if LOCK_FILE.exists():
        try:
            last_run = float(LOCK_FILE.read_text().strip())
            if now - last_run < COOLDOWN_SECONDS:
                return False
        except: pass 
    try: LOCK_FILE.write_text(str(now))
    except: pass 
    return True

# ==============================================================================
# 3. FETCH ENGINES
# ==============================================================================
def fetch_polygon_backup(ticker):
    """
    Backup: Delayed Stream (16m ago) to guarantee FULL CANDLES on Free Tier.
    """
    if not POLYGON_KEY: return pd.DataFrame()
    poly_ticker = f"I:{ticker}" 
    
    log.info(f"🛡️ ACTIVATING BACKUP: Polygon.io ({poly_ticker}) [Delayed Stream]")
    
    try:
        # STRATEGY: Enforce 16-minute offset
        end_dt = datetime.now(timezone.utc) - timedelta(minutes=16)
        start_dt = end_dt - timedelta(days=2) # Get history to fill gaps
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{poly_ticker}/range/1/minute/{int(start_dt.timestamp()*1000)}/{int(end_dt.timestamp()*1000)}"
        params = {"apiKey": POLYGON_KEY, "limit": 50000, "adjusted": "true"}
        
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        if data.get('status') != 'OK' or not data.get('results'):
            log.warning(f"⚠️ Polygon Backup Failed for {poly_ticker}: {data.get('status')}")
            return pd.DataFrame()
            
        df = pd.DataFrame(data['results'])
        df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
        
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms').dt.tz_localize('UTC')
        df['ticker'] = ticker
        
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]
        
    except Exception as e:
        log.error(f"❌ Polygon Backup Error: {e}")
        return pd.DataFrame()

def fetch_yahoo_data(y_ticker, friendly_name):
    """
    Primary: Fetches data using yfinance (Historical Block Mode).
    """
    # 2-Day Historical Window
    start_date = datetime.now().date() - timedelta(days=2) 
    end_date = datetime.now().date() + timedelta(days=1)
    
    try:
        ticker_dat = yf.Ticker(y_ticker)
        df = ticker_dat.history(start=start_date, end=end_date, interval="1m", auto_adjust=True)
        
        if df.empty: return pd.DataFrame()
        
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        
        if 'date' in df.columns: df.rename(columns={"date": "datetime_utc"}, inplace=True)
        df.rename(columns={"datetime": "datetime_utc"}, inplace=True)
        df['ticker'] = friendly_name
        
        # Ensure UTC Alignment
        if df['datetime_utc'].dt.tz is None:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('America/New_York')
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC')
        
        if 'volume' not in df.columns: df['volume'] = 0
        
        # [CRITICAL FIX] Explicitly select ONLY the 7 columns the DB expects.
        # This removes 'dividends' and 'stock splits' which caused the crash.
        schema_cols = ['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']
        df_clean = df[schema_cols].copy()
        
        return validate_and_clean(df_clean, friendly_name)
        
    except Exception as e:
        log.warning(f"⏳ Yahoo Fetch Error for {y_ticker}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. SNAPSHOT LOGIC
# ==============================================================================
def calculate_orb(df):
    if df.empty: return None, None
    df = df.copy()
    df['dt_ny'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    start = t_time(9, 30)
    end = t_time(10, 0)
    orb_df = df[(df['dt_ny'].dt.time >= start) & (df['dt_ny'].dt.time < end)]
    
    if len(orb_df) > 5:
        return orb_df['high'].max(), orb_df['low'].min()
    return None, None

def generate_snapshot_from_db(con):
    try:
        max_ts = con.execute(f"SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = 'XSP'").fetchone()[0]
        if not max_ts: return
        
        # Use UTC for dashboard timestamp
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
        
        temp_file = SNAPSHOT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(snapshot, f, cls=RobustEncoder)
            
        if Path(temp_file).exists():
            os.replace(temp_file, SNAPSHOT_FILE)
            
        log.info(f"📸 Snapshot Generated. (UTC: {current_time.strftime('%H:%M:%S')})")

    except Exception as e:
        log.error(f"Snapshot Generation Failed: {e}")

# ==============================================================================
# 5. EXECUTION
# ==============================================================================
def run_ingest():
    if check_cooldown():
        log.info("📊 STARTING INDEX INGESTION (SUCCESS PROTOCOL)...")
        staged = []
        
        targets = [('VIX', '^VIX'), ('XSP', '^XSP')]
        
        for friendly, y_ticker in targets:
            df = fetch_yahoo_data(y_ticker, friendly)
            
            if df.empty and USE_POLYGON_BACKUP:
                df = fetch_polygon_backup(friendly)
                
            if not df.empty: 
                staged.append((friendly, df))
            else:
                log.error(f"❌ DATA LOSS: Could not fetch {friendly} from any source.")
        
        if config.DB_FILE.exists():
            try:
                con = duckdb.connect(str(config.DB_FILE), config={'access_mode': 'READ_WRITE'})
                con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (datetime_utc TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, ticker VARCHAR, PRIMARY KEY (datetime_utc, ticker))")
                
                if staged:
                    for friendly, df in staged:
                        con.register('temp_idx', df)
                        con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
                        con.unregister('temp_idx')
                        log.info(f"   ✅ {friendly}: Ingested {len(df)} candles.")
                else:
                    log.warning("⚠️ No new data to write.")

                generate_snapshot_from_db(con)
                con.close()
                
            except Exception as e:
                log.error(f"DB Write Error: {e}")
        else:
            log.error(f"CRITICAL: DB File not found at {config.DB_FILE}")

if __name__ == "__main__":
    run_ingest()