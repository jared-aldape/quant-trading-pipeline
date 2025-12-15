import sys
import duckdb
import pandas as pd
import requests
import time
import math  # REQUIRED for Surgical Logic (floor/ceil)
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

# ------------------------------------------------------------------------------
# ⚡ CONFIGURATION: SPY PROXY FOR XSP OPTIONS
# ------------------------------------------------------------------------------
CONTEXT_TICKER = "SPY" 
TARGET_ROOT = "XSP"    
SCALE_FACTOR = 1.0     # SPY (~$590) ~= XSP (~$590)

BASE_URL = "https://api.polygon.io"
API_KEY = config.POLYGON_API_KEY

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def fetch_context_price(target_date):
    """Fetches SPY price range to define the Daily Battlefield."""
    d_str = target_date.strftime('%Y-%m-%d')
    url = f"{BASE_URL}/v2/aggs/ticker/{CONTEXT_TICKER}/range/1/day/{d_str}/{d_str}"
    params = {"adjusted": "true", "apiKey": API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 403:
            log.warning(f"⚠️ Polygon 403 (Locked) for {d_str}. Skipping.")
            return None, None
            
        if resp.status_code != 200:
            log.error(f"❌ Context Data Failed ({CONTEXT_TICKER}): {resp.status_code}")
            return None, None
            
        data = resp.json()
        if data.get('resultsCount', 0) > 0:
            res = data['results'][0]
            # Return the Day's High and Low
            return res.get('h') * SCALE_FACTOR, res.get('l') * SCALE_FACTOR
        else:
            log.warning(f"⚠️ No {CONTEXT_TICKER} data found for {d_str}")
            return None, None
            
    except Exception as e:
        log.error(f"Context Fetch Error: {e}")
        return None, None

def generate_target_tickers(target_date, high, low):
    """
    GEN 2 SURGICAL LOGIC (Restored M27 Standard):
    Range = [Floor(Low) - 2] to [Ceil(High) + 2]
    
    This captures the entire trading range of the day, plus a 
    2-strike safety buffer on both ends.
    """
    strike_min = math.floor(low) - 2
    strike_max = math.ceil(high) + 2
    
    fmt_date = target_date.strftime('%y%m%d')
    
    tickers = []
    # Iterate through every integer strike in the surgical range
    for k in range(strike_min, strike_max + 1):
        strike_fmt = f"{k * 1000:08d}"
        tickers.append(f"O:{TARGET_ROOT}{fmt_date}C{strike_fmt}")
        tickers.append(f"O:{TARGET_ROOT}{fmt_date}P{strike_fmt}")
        
    return tickers

def fetch_option_bars(ticker, target_date):
    """Fetches 1-minute bars for a specific option contract."""
    d_str = target_date.strftime('%Y-%m-%d')
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{d_str}/{d_str}"
    params = {"adjusted": "true", "limit": 5000, "apiKey": API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('resultsCount', 0) > 0:
                df = pd.DataFrame(data['results'])
                
                # Standardize Columns
                df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                
                # Convert Milliseconds to Timestamp (UTC)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                
                # Clean Ticker
                df['ticker'] = ticker.replace("O:", "") 
                
                return df
    except:
        pass
    
    return pd.DataFrame()

# ==============================================================================
# 3. MAIN HARVEST LOOP
# ==============================================================================
def run_daily_harvest():
    log.info("🚜 STARTING DAILY OPTION HARVEST (Surgical Logic | T-1)")
    
    if not config.DB_FILE.exists():
        log.error("❌ DB not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_OPTIONS} (
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
    
    today = date.today()
    lookback = 3 
    
    total_saved = 0
    
    # Range starts at 1 (Yesterday) to respect Free Tier
    for i in range(1, lookback + 1):
        target_date = today - timedelta(days=i)
        
        if target_date.weekday() > 4: continue
        
        log.info(f"📅 Target Session: {target_date}")
        
        # A. Get Range
        h, l = fetch_context_price(target_date)
        if h is None: continue 
            
        # B. Generate Surgical List
        tickers = generate_target_tickers(target_date, h, l)
        log.info(f"   🎯 Surgical Target: {len(tickers)} contracts (Range: {math.floor(l)-2} - {math.ceil(h)+2})")
        
        # C. Fetch Data
        day_dfs = []
        for t in tickers:
            df = fetch_option_bars(t, target_date)
            if not df.empty:
                day_dfs.append(df)
                
        # D. Save
        if day_dfs:
            full_df = pd.concat(day_dfs)
            count = len(full_df)
            con.register('temp_opts', full_df)
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                (datetime_utc, ticker, open, high, low, close, volume)
                SELECT datetime_utc, ticker, open, high, low, close, volume 
                FROM temp_opts
            """)
            log.info(f"   ✅ Saved {count} rows.")
            total_saved += count
        else:
            log.info(f"   ⚠️ No option volume found.")

    con.close()
    log.info(f"🏁 Option Harvest Complete. Total Rows: {total_saved}")

if __name__ == "__main__":
    run_daily_harvest()