import sys
import duckdb
import yfinance as yf
import pandas as pd
import time
import json
import os
import requests
import numpy as np
from datetime import datetime, time as t_time, timedelta
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
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, (datetime, pd.Timestamp)): return obj.isoformat()
        if pd.isna(obj): return None
        return super(RobustEncoder, self).default(obj)

# ==============================================================================
# 2. DATA HARVESTING LOGIC
# ==============================================================================
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

def fetch_polygon_backup(ticker):
    """
    Fallback: Fetches Index Data from Polygon (Massive.com).
    Protocol: I:VIX, I:XSP
    
    [MAGITEK UPDATE]: Applied 16-minute offset for Free Tier to ensure 
    full candle formation (prevents flat candles).
    """
    if not POLYGON_KEY: return pd.DataFrame()
    
    # Polygon Index Ticker Format
    poly_ticker = f"I:{ticker}" 
    
    log.info(f"🛡️ ACTIVATING BACKUP: Polygon.io ({poly_ticker}) [Delayed Stream]")
    
    try:
        # FIX: Force the window to end 16 minutes ago.
        # This accesses the 'Delayed' bucket which allows full aggregates on Free Tier.
        end_dt = datetime.now() - timedelta(minutes=16)
        start_dt = end_dt - timedelta(days=2)
        
        url = f"https://api.polygon.io/v2/aggs/ticker/{poly_ticker}/range/1/minute/{int(start_dt.timestamp()*1000)}/{int(end_dt.timestamp()*1000)}"
        params = {"apiKey": POLYGON_KEY, "limit": 50000, "adjusted": "true"}
        
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        if data.get('status') != 'OK' or not data.get('results'):
            log.warning(f"⚠️ Polygon Backup Failed for {poly_ticker}: {data.get('status')}")
            return pd.DataFrame()
            
        # Parse
        df = pd.DataFrame(data['results'])
        df.rename(columns={
            't': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'
        }, inplace=True)
        
        # Convert Timestamp
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
        df['ticker'] = ticker # Store as standard ticker (VIX/XSP)
        
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]
        
    except Exception as e:
        log.error(f"❌ Polygon Backup Error: {e}")
        return pd.DataFrame()

def fetch_yahoo_data(y_ticker, friendly_name):
    """
    Primary: Fetches data using yfinance (Auto-Stealth).
    Updated v3.5: Removed requests.Session() to fix curl_cffi conflict.
    """
    start_date = datetime.now().date() - timedelta(days=2) 
    end_date = datetime.now().date() + timedelta(days=1)
    
    try:
        # v3.5 FIX: Let yfinance handle the session/headers internally
        ticker_dat = yf.Ticker(y_ticker)
        df = ticker_dat.history(start=start_date, end=end_date, interval="1m", auto_adjust=True)
        
        if df.empty: 
            log.warning(f"⚠️ Yahoo returned empty data for {y_ticker}")
            return pd.DataFrame()
        
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        
        # Standardize Columns
        if 'date' in df.columns: df.rename(columns={"date": "datetime"}, inplace=True)
        df.rename(columns={"datetime": "datetime_utc"}, inplace=True)
        df['ticker'] = friendly_name
        
        # Timezone Normalization (Strict UTC)
        if pd.api.types.is_datetime64_any_dtype(df['datetime_utc']):
            if df['datetime_utc'].dt.tz is None:
                # If naive, assume NY time (YF default) then convert to UTC
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('America/New_York')
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC').dt.tz_localize(None)
        
        # Add volume if missing (Indices often have 0 vol on YF)
        if 'volume' not in df.columns: df['volume'] = 0
        
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]
        
    except Exception as e:
        log.warning(f"⏳ Yahoo Fetch Error for {y_ticker}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 3. SNAPSHOT LOGIC (THE GLASS FEED)
# ==============================================================================
def calculate_orb(df):
    if df.empty: return None, None
    df = df.copy()
    # ORB Logic (NY Time)
    df['dt_ny'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    start = t_time(9, 30)
    end = t_time(10, 0)
    orb_df = df[(df['dt_ny'].dt.time >= start) & (df['dt_ny'].dt.time < end)]
    
    if len(orb_df) > 5:
        return orb_df['high'].max(), orb_df['low'].min()
    return None, None

def generate_snapshot_from_db(con):
    """
    Generates the UI JSON from the Database.
    Robustness: Runs even if ingest failed, using whatever data is in the Vault.
    """
    try:
        # Check freshness
        max_ts = con.execute(f"SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = 'XSP'").fetchone()[0]
        if not max_ts: return
        
        last_data_time = pd.to_datetime(max_ts)
        time_diff = (datetime.now() - last_data_time).total_seconds()
        
        status = "LIVE"
        if time_diff > 3600: status = "STALE (>1h)"
        if time_diff > 86400: status = "STALE (>24h)"

        # Fetch Window (Last 24h of data points)
        # We fetch by TIME, not just date, to handle overnight transitions
        target_time = datetime.now() - timedelta(days=2) 
        
        q = f"SELECT * FROM {config.TBL_INDICES} WHERE datetime_utc >= '{target_time}' ORDER BY datetime_utc ASC"
        df_all = con.execute(q).df()
        
        xsp_df = df_all[df_all['ticker'] == 'XSP'].copy()
        vix_df = df_all[df_all['ticker'] == 'VIX'].copy()
        
        orb_h, orb_l = calculate_orb(xsp_df)
        
        snapshot = {
            "updated": datetime.now().isoformat(),
            "data_status": status,
            "last_candle": last_data_time.isoformat(),
            "xsp": xsp_df.to_dict(orient='records'),
            "vix": vix_df.to_dict(orient='records'),
            "orb": {"h": orb_h, "l": orb_l}
        }
        
        temp_file = SNAPSHOT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(snapshot, f, cls=RobustEncoder)
            
        if Path(temp_file).exists():
            os.replace(temp_file, SNAPSHOT_FILE)
            
        log.info(f"📸 Snapshot Generated. Status: {status} (XSP: {len(xsp_df)} rows)")

    except Exception as e:
        log.error(f"Snapshot Generation Failed: {e}")

# ==============================================================================
# 4. EXECUTION
# ==============================================================================
def run_ingest():
    if check_cooldown():
        log.info("📊 STARTING INDEX INGESTION CYCLE...")
        staged = []
        
        targets = [('VIX', '^VIX'), ('XSP', '^XSP')]
        
        for friendly, y_ticker in targets:
            # 1. Try Yahoo
            df = fetch_yahoo_data(y_ticker, friendly)
            
            # 2. Try Polygon Backup if Yahoo Failed OR returned empty
            if df.empty and USE_POLYGON_BACKUP:
                df = fetch_polygon_backup(friendly)
                
            if not df.empty: 
                staged.append((friendly, df))
            else:
                log.error(f"❌ DATA LOSS: Could not fetch {friendly} from any source.")
        
        # 3. DB Transaction
        if config.DB_FILE.exists():
            try:
                con = duckdb.connect(str(config.DB_FILE), config={'access_mode': 'READ_WRITE'})
                
                # Schema Assurance
                con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (datetime_utc TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, ticker VARCHAR, PRIMARY KEY (datetime_utc, ticker))")
                
                if staged:
                    for friendly, df in staged:
                        con.register('temp_idx', df)
                        con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
                        con.unregister('temp_idx')
                        log.info(f"   ✅ {friendly}: Ingested {len(df)} candles.")
                else:
                    log.warning("⚠️ No new data to write. Attempting to update snapshot from existing Vault data.")

                # 4. Generate Snapshot (Always Run)
                generate_snapshot_from_db(con)
                con.close()
                
            except Exception as e:
                log.error(f"DB Write Error: {e}")
        else:
            log.error(f"CRITICAL: DB File not found at {config.DB_FILE}")

if __name__ == "__main__":
    run_ingest()