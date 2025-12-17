import sys
import duckdb
import yfinance as yf
import pandas as pd
import time
import json
import os
import requests
import random
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

# ⚡ STEALTH FIX: Rotate User Agents to bypass Rate Limits
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0"
]

class RobustEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, (datetime, pd.Timestamp)): return obj.isoformat()
        if pd.isna(obj): return None
        return super(RobustEncoder, self).default(obj)

# ==============================================================================
# 2. LOGIC
# ==============================================================================
def check_cooldown():
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

def fetch_yahoo_data(y_ticker):
    """Fetches data with backoff and rotation."""
    start_date = datetime.now().date() - timedelta(days=2) 
    end_date = datetime.now().date() + timedelta(days=1)
    
    # ⚡ RETRY LOGIC
    for attempt in range(3):
        try:
            # Randomize Headers
            session = requests.Session()
            session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            
            # Random Sleep to act human
            time.sleep(random.uniform(1.0, 3.0)) 
            
            ticker_dat = yf.Ticker(y_ticker, session=session)
            df = ticker_dat.history(start=start_date, end=end_date, interval="1m")
            
            if df.empty: 
                log.warning(f"⚠️ Empty response for {y_ticker}")
                return pd.DataFrame()
            
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df.rename(columns={"datetime": "datetime_utc"}, inplace=True)
            df['ticker'] = y_ticker.replace('^', '')
            
            # Timezone Logic
            if pd.api.types.is_datetime64_any_dtype(df['datetime_utc']):
                if df['datetime_utc'].dt.tz is None:
                    df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('America/New_York')
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC').dt.tz_localize(None)
            
            return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]
            
        except Exception as e:
            log.warning(f"⏳ Attempt {attempt+1} failed for {y_ticker}: {e}")
            time.sleep(2 * (attempt + 1)) # Exponential backoff
            
    log.error(f"❌ Failed to fetch {y_ticker} after 3 attempts.")
    return pd.DataFrame()

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
    try:
        # Check freshness
        max_ts = con.execute(f"SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = 'XSP'").fetchone()[0]
        if not max_ts: return
        
        # Only snapshot if data is relatively recent (within 24h)
        last_data_time = pd.to_datetime(max_ts)
        if (datetime.now() - last_data_time).total_seconds() > 86400 * 3: # Allow weekend gaps
            log.warning("⚠️ Data in DB is stale (>3 days). Snapshot might be old.")

        target_date = last_data_time.date()
        s_str = f"{target_date} 00:00:00"
        
        xsp_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker = 'XSP' AND datetime_utc >= '{s_str}' ORDER BY datetime_utc ASC").df()
        vix_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker = 'VIX' AND datetime_utc >= '{s_str}' ORDER BY datetime_utc ASC").df()
        
        orb_h, orb_l = calculate_orb(xsp_df)
        
        snapshot = {
            "updated": datetime.now().isoformat(),
            "xsp": xsp_df.to_dict(orient='records'),
            "vix": vix_df.to_dict(orient='records'),
            "orb": {"h": orb_h, "l": orb_l}
        }
        
        temp_file = SNAPSHOT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(snapshot, f, cls=RobustEncoder)
            
        if Path(temp_file).exists():
            os.replace(temp_file, SNAPSHOT_FILE)
            
        log.info(f"📸 Snapshot Updated. (XSP: {len(xsp_df)} rows)")

    except Exception as e:
        log.error(f"Snapshot Failed: {e}")

def run_ingest():
    if check_cooldown():
        log.info("📊 FETCHING NEW DATA...")
        staged = []
        fetch_success = False
        
        for friendly, y_ticker in {'VIX': '^VIX', 'XSP': '^XSP'}.items():
            df = fetch_yahoo_data(y_ticker)
            if not df.empty: 
                staged.append((friendly, df))
                fetch_success = True
        
        if staged and config.DB_FILE.exists():
            try:
                con = duckdb.connect(str(config.DB_FILE), config={'access_mode': 'READ_WRITE'})
                con.execute(f"CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (datetime_utc TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, ticker VARCHAR, PRIMARY KEY (datetime_utc, ticker))")
                for friendly, df in staged:
                    con.register('temp_idx', df)
                    con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
                    con.unregister('temp_idx')
                    log.info(f"   ✅ {friendly}: Saved {len(df)} candles.")
                
                # Only snapshot if we actually got data or DB exists
                generate_snapshot_from_db(con)
                con.close()
            except Exception as e:
                log.error(f"DB Write Error: {e}")
        elif not fetch_success:
             log.warning("⚠️ Fetch failed. Skipping snapshot update to prevent stale data.")

if __name__ == "__main__":
    run_ingest()