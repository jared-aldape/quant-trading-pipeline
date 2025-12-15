import sys
import duckdb
import pandas as pd
import requests
import time
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
    """Fetches SPY price to determine ATM strike range."""
    d_str = target_date.strftime('%Y-%m-%d')
    url = f"{BASE_URL}/v2/aggs/ticker/{CONTEXT_TICKER}/range/1/day/{d_str}/{d_str}"
    params = {"adjusted": "true", "apiKey": API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            log.error(f"❌ Context Data Failed ({CONTEXT_TICKER}): {resp.status_code}")
            return None, None
            
        data = resp.json()
        if data.get('resultsCount', 0) > 0:
            res = data['results'][0]
            # Scale if necessary (1.0 for SPY->XSP)
            return res.get('h') * SCALE_FACTOR, res.get('l') * SCALE_FACTOR
        else:
            log.error(f"❌ No {CONTEXT_TICKER} data found for {d_str}")
            return None, None
            
    except Exception as e:
        log.error(f"Context Fetch Error: {e}")
        return None, None

def generate_target_tickers(target_date, high, low):
    """Generates O:XSP option tickers."""
    center = (high + low) / 2
    strike_min = int(center * 0.975)
    strike_max = int(center * 1.025)
    fmt_date = target_date.strftime('%y%m%d')
    
    tickers = []
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
                # Polygon often returns: v, vw, o, c, h, l, t, n
                df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                df['ticker'] = ticker.replace("O:", "") 
                
                # We return ALL cols here, but we will filter in the INSERT step to be safe
                return df
    except:
        pass
    
    return pd.DataFrame()

# ==============================================================================
# 3. MAIN HARVEST LOOP
# ==============================================================================
def run_daily_harvest():
    log.info("🚜 STARTING DAILY OPTION HARVEST (SPY-GUIDED)")
    
    if not config.DB_FILE.exists():
        log.error("❌ DB not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # Ensure Table Exists
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
    lookback = 3 # Look back to ensure we cover recent missing days
    
    total_saved = 0
    
    for i in range(lookback):
        target_date = today - timedelta(days=i)
        if target_date.weekday() > 4: continue
        
        log.info(f"📅 Target Session: {target_date}")
        
        # A. Get Context
        h, l = fetch_context_price(target_date)
        if h is None: continue
            
        # B. Generate Tickers
        tickers = generate_target_tickers(target_date, h, l)
        center_price = (h+l)/2
        log.info(f"   Generated {len(tickers)} potential contracts centered on ${center_price:.2f}")
        
        # C. Fetch Data
        day_dfs = []
        for t in tickers:
            df = fetch_option_bars(t, target_date)
            if not df.empty:
                day_dfs.append(df)
                
        # D. SAVE TO DB (EXPLICIT INSERT FIX)
        if day_dfs:
            full_df = pd.concat(day_dfs)
            count = len(full_df)
            
            # Register the raw dataframe (which might have 17 columns)
            con.register('temp_opts', full_df)
            
            # EXPLICITLY SELECT ONLY THE 7 COLUMNS WE WANT
            # This fixes the "7 columns available but 17 specified" crash
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                (datetime_utc, ticker, open, high, low, close, volume)
                SELECT datetime_utc, ticker, open, high, low, close, volume 
                FROM temp_opts
            """)
            
            log.info(f"   ✅ Saved {count} rows for {target_date}")
            total_saved += count
        else:
            log.info(f"   ⚠️ No option volume found for {target_date}")

    con.close()
    log.info(f"🏁 Option Harvest Complete. Total Rows: {total_saved}")

if __name__ == "__main__":
    run_daily_harvest()