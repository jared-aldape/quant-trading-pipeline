import sys
import duckdb
import pandas as pd
import requests
import time
import math
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("DailyHarvest")

BASE_URL = "https://api.polygon.io"
API_KEY = getattr(config, 'POLYGON_API_KEY', 'YOUR_API_KEY')
TARGET_ROOT = "XSP"
TBL_OPTIONS = getattr(config, 'TBL_OPTIONS', 'options_1m')

# Adaptive Rate Limiting
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
# 2. DIRECT POLYGON BOUNDARY MATH (THE SPY PROXY)
# ==============================================================================
def get_xsp_range_from_polygon(target_date_str):
    """
    Fetches the True High/Low directly from Polygon's API using the SPY ETF.
    SPY is an equity, bypassing all 'Indices' subscription blocks, and scales 1:1 with XSP.
    Zero dependency on the local DuckDB database.
    """
    url = f"{BASE_URL}/v2/aggs/ticker/SPY/range/1/day/{target_date_str}/{target_date_str}"
    params = {"adjusted": "true", "apiKey": API_KEY}
    
    try:
        enforce_rate_limit()
        res = requests.get(url, params=params, timeout=10)
        
        if res.status_code == 429:
            enforce_rate_limit(is_retry=True)
            res = requests.get(url, params=params, timeout=10)
            
        if res.status_code == 403:
            log.warning(f"⚠️ Polygon 403 (Tier Limit): Cannot fetch real-time or unsettled data for {target_date_str}.")
            return None, None
            
        if res.status_code == 200:
            data = res.json()
            if data.get('resultsCount', 0) > 0:
                result = data['results'][0]
                return result['h'], result['l']
            else:
                log.warning(f"Polygon returned empty data for SPY on {target_date_str}.")
        else:
            log.warning(f"Polygon API returned {res.status_code}: {res.text}")
    except Exception as e:
        log.error(f"Polygon boundary fetch failed: {e}")
        
    return None, None

def generate_target_tickers(target_date_str, high, low):
    """Generates ALL option tickers 2 strikes below the low and 2 strikes above the high."""
    dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    date_code = dt.strftime("%y%m%d")

    # The Non-Negotiable Rule: 2 Strikes Below Low, 2 Strikes Above High
    min_strike = math.floor(low) - 2
    max_strike = math.ceil(high) + 2

    tickers = []
    # Generate every single strike in between
    for strike in range(min_strike, max_strike + 1):
        # Format strike to 8 digits (e.g., 585 -> 00585000)
        strike_str = f"{int(strike * 1000):08d}"
        tickers.append(f"O:{TARGET_ROOT}{date_code}C{strike_str}")
        tickers.append(f"O:{TARGET_ROOT}{date_code}P{strike_str}")

    return tickers, min_strike, max_strike

# ==============================================================================
# 3. POLYGON AGGREGATE FETCHER
# ==============================================================================
def fetch_option_bars(ticker, date_str):
    """Fetches 1-minute aggregates for the specific option ticker."""
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": API_KEY
    }
    
    while True:
        enforce_rate_limit()
        try:
            res = requests.get(url, params=params, timeout=10)
            
            if res.status_code == 429:
                enforce_rate_limit(is_retry=True)
                continue
                
            if res.status_code == 403:
                return pd.DataFrame() # Handled silently at this level to avoid console spam
            
            res.raise_for_status()
            data = res.json()
            
            if data.get('resultsCount', 0) > 0:
                df = pd.DataFrame(data['results'])
                # Convert Polygon timestamp (ms) to UTC datetime
                df['datetime_utc'] = pd.to_datetime(df['t'], unit='ms', utc=True)
                df['ticker'] = ticker
                df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
            else:
                return pd.DataFrame()
        except Exception as e:
            log.error(f"Error fetching {ticker}: {e}")
            return pd.DataFrame()

# ==============================================================================
# 4. EXECUTION ENGINE
# ==============================================================================
def sync_date(target_date_str):
    log.info(f"📅 Executing Surgical Harvest for: {target_date_str}")
    
    # ⚡ DIRECT POLYGON PING using SPY Equity Proxy
    h, l = get_xsp_range_from_polygon(target_date_str)
    if h is None or l is None:
        log.warning(f"⚠️ No equity data returned from Polygon for SPY on {target_date_str}. (Market closed, weekend, or tier limit).")
        return

    tickers, min_s, max_s = generate_target_tickers(target_date_str, h, l)
    log.info(f"🎯 Target Acquired: SPY Range ${l:.2f}-${h:.2f} | Fetching {len(tickers)} options (Strikes {min_s} to {max_s})")
    
    day_dfs = []
    for t in tickers:
        df = fetch_option_bars(t, target_date_str)
        if not df.empty:
            day_dfs.append(df)
        
        if STRICT_MODE_TRIGGERED:
            print(f"      ⏳ Slow Mode: Fetched {t}...                 ", end='\r')

    if day_dfs:
        full_df = pd.concat(day_dfs)
        count = len(full_df)
        
        try:
            con = duckdb.connect(str(config.DB_FILE))
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {TBL_OPTIONS} (
                    datetime_utc TIMESTAMP,
                    ticker VARCHAR,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    PRIMARY KEY (datetime_utc, ticker)
                )
            """)
            
            # NO EXCEPTIONS. Delete any corrupted/partial data for this day and rewrite.
            date_start = f"{target_date_str} 00:00:00"
            date_end = f"{target_date_str} 23:59:59"
            con.execute(f"DELETE FROM {TBL_OPTIONS} WHERE datetime_utc >= '{date_start}' AND datetime_utc <= '{date_end}'")
            
            con.register('temp_opts', full_df)
            con.execute(f"""
                INSERT INTO {TBL_OPTIONS} (datetime_utc, ticker, open, high, low, close, volume) 
                SELECT datetime_utc, ticker, open, high, low, close, volume FROM temp_opts
            """)
            con.unregister('temp_opts')
            con.close()
            log.info(f"✅ Success! Saved {count} 1-minute option bars to Vault.")
        except Exception as e:
            log.error(f"❌ Database Write Error: {e}")
    else:
        log.info(f"⚠️ No option data returned from Polygon for {target_date_str}.")

def run_sync(days_back=29):
    """Syncs the exact target range for the last N days. NO SKIPS."""
    log.info(f"🚀 INITIATING UNRESTRICTED OPTIONS HARVEST (Last {days_back} Days)")
    tz_ny = pytz.timezone('US/Eastern')
    today_ny = datetime.now(tz_ny).date()
    
    # 🩹 FIX: range now terminates at 1 (Yesterday). 
    # We do not attempt to fetch 'i=0' (Today) to prevent 403 API tier violations on active/unsettled sessions.
    for i in range(days_back, 0, -1):
        target_date = today_ny - timedelta(days=i)
        if target_date.weekday() >= 5: # Skip Sat/Sun
            continue
        sync_date(target_date.strftime('%Y-%m-%d'))

if __name__ == "__main__":
    days = 2
    if len(sys.argv) > 1:
        try: days = int(sys.argv[1])
        except: pass
    run_sync(days)