import sys
import duckdb
import pandas as pd
import requests
import time
import math
from datetime import datetime, timedelta, date
from pathlib import Path

# ==============================================================================
# 1. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("DailyHarvest")

CONTEXT_TICKER = "SPY" 
TARGET_ROOT = "XSP"    
SCALE_FACTOR = 1.0     
BASE_URL = "https://api.polygon.io"
API_KEY = config.POLYGON_API_KEY

# --- ADAPTIVE RATE LIMITING ---
CURRENT_SLEEP = 0.2 
STRICT_MODE_TRIGGERED = False

def enforce_rate_limit(is_retry=False):
    global CURRENT_SLEEP, STRICT_MODE_TRIGGERED
    if is_retry and not STRICT_MODE_TRIGGERED:
        log.warning("⚠️ FREE TIER DETECTED. Switching to Low-Velocity Mode (13s delay).")
        CURRENT_SLEEP = 13.0 
        STRICT_MODE_TRIGGERED = True
    time.sleep(CURRENT_SLEEP)

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def safe_request(url, params):
    attempts = 0
    max_retries = 3
    while attempts < max_retries:
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                enforce_rate_limit(is_retry=False)
                return resp
            if resp.status_code == 429:
                enforce_rate_limit(is_retry=True)
                attempts += 1
                continue
            if resp.status_code == 403: return None
            log.warning(f"⚠️ API Error {resp.status_code}. Retrying...")
            attempts += 1
            time.sleep(5)
        except Exception as e:
            log.warning(f"⚠️ Network Error: {e}")
            attempts += 1
            time.sleep(5)
    return None

def fetch_context_price(target_date):
    d_str = target_date.strftime('%Y-%m-%d')
    url = f"{BASE_URL}/v2/aggs/ticker/{CONTEXT_TICKER}/range/1/day/{d_str}/{d_str}"
    params = {"adjusted": "true", "apiKey": API_KEY}
    resp = safe_request(url, params)
    if not resp: return None, None
    try:
        data = resp.json()
        if data.get('resultsCount', 0) > 0:
            res = data['results'][0]
            return res.get('h') * SCALE_FACTOR, res.get('l') * SCALE_FACTOR
    except: pass
    return None, None

def generate_target_tickers(target_date, high, low):
    strike_min = math.floor(low) - 2
    strike_max = math.ceil(high) + 2
    fmt_date = target_date.strftime('%y%m%d')
    tickers = []
    for k in range(strike_min, strike_max + 1):
        strike_fmt = f"{k * 1000:08d}"
        tickers.append(f"O:{TARGET_ROOT}{fmt_date}C{strike_fmt}")
        tickers.append(f"O:{TARGET_ROOT}{fmt_date}P{strike_fmt}")
    return tickers

def fetch_option_bars(ticker, target_date):
    d_str = target_date.strftime('%Y-%m-%d')
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{d_str}/{d_str}"
    params = {"adjusted": "true", "limit": 5000, "apiKey": API_KEY}
    resp = safe_request(url, params)
    if not resp: return pd.DataFrame()
    try:
        data = resp.json()
        if data.get('resultsCount', 0) > 0:
            df = pd.DataFrame(data['results'])
            df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
            df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
            df['ticker'] = ticker.replace("O:", "") 
            return df
    except: pass
    return pd.DataFrame()

# ==============================================================================
# 3. MAIN HARVEST LOOP (SMART SKIPPING ENABLED)
# ==============================================================================
def run_daily_harvest(lookback_days=30):
    log.info(f"🚜 STARTING HARVEST (Lookback: {lookback_days} days)")
    
    if not config.DB_FILE.exists():
        log.error("❌ DB not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_OPTIONS} (
            datetime_utc TIMESTAMP,
            ticker VARCHAR,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)
    
    today = date.today()
    total_saved = 0
    
    for i in range(1, lookback_days + 1):
        target_date = today - timedelta(days=i)
        if target_date.weekday() > 4: continue
        
        # ⚡ INTELLIGENT SKIP LOGIC ⚡
        # Check if we already have significant data for this day
        start_ts = target_date.strftime('%Y-%m-%d 00:00:00')
        end_ts = (target_date + timedelta(days=1)).strftime('%Y-%m-%d 00:00:00')
        
        try:
            count_check = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS} WHERE datetime_utc >= '{start_ts}' AND datetime_utc < '{end_ts}'").fetchone()[0]
            if count_check > 500: # Threshold: If >500 rows exist, assume day is captured
                log.info(f"⏭️  Skipping {target_date} (Already have {count_check} rows)")
                continue
        except Exception as e:
            log.warning(f"⚠️ Skip Check Failed: {e}")

        # If not skipped, PROCEED WITH DOWNLOAD
        log.info(f"📅 Processing: {target_date}")
        h, l = fetch_context_price(target_date)
        if h is None: continue 
            
        tickers = generate_target_tickers(target_date, h, l)
        log.info(f"   🎯 Surgical Target: {len(tickers)} contracts")
        
        day_dfs = []
        for t in tickers:
            df = fetch_option_bars(t, target_date)
            if not df.empty: day_dfs.append(df)
            
            if STRICT_MODE_TRIGGERED:
                print(f"      ⏳ Slow Mode: Fetched {t}...", end='\r')
                
        if day_dfs:
            full_df = pd.concat(day_dfs)
            count = len(full_df)
            con.register('temp_opts', full_df)
            con.execute(f"INSERT OR IGNORE INTO {config.TBL_OPTIONS} (datetime_utc, ticker, open, high, low, close, volume) SELECT datetime_utc, ticker, open, high, low, close, volume FROM temp_opts")
            con.unregister('temp_opts')
            log.info(f"   ✅ Saved {count} rows.")
            total_saved += count
        else:
            log.info(f"   ⚠️ No option volume found.")

    con.close()
    log.info(f"🏁 Harvest Complete. Total Rows: {total_saved}")

def run_fetch_pipeline():
    run_daily_harvest(lookback_days=30)

if __name__ == "__main__":
    run_daily_harvest(lookback_days=30)