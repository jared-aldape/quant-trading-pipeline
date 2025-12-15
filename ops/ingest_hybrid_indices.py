import sys
import time
import pandas as pd
import duckdb
import requests
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
except ImportError:
    print("❌ CRITICAL: Could not import 'src.utils'.")
    sys.exit(1)

log = get_logger("HybridIngest")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
THROTTLE_DELAY = 13.0 

# TARGET: Jan 1, 2025 to Now
START_DATE = datetime(2025, 1, 1).date()
END_DATE = datetime.now().date()
START_STR = START_DATE.strftime('%Y-%m-%d')
END_STR = END_DATE.strftime('%Y-%m-%d')

# HOLIDAYS (Skip for Polygon)
HOLIDAYS_2025 = {
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
    "2025-11-27", "2025-12-25"
}

# ==============================================================================
# 3. POLYGON WORKER (SPY -> SPX)
# ==============================================================================
def get_trading_days():
    days = []
    curr = START_DATE
    while curr <= END_DATE:
        d_str = curr.strftime('%Y-%m-%d')
        if curr.weekday() < 5 and d_str not in HOLIDAYS_2025:
            days.append(d_str)
        curr += timedelta(days=1)
    return days

def fetch_polygon_spy(date_str):
    """Fetches 1-minute SPY bars."""
    url = f"{BASE_URL}/SPY/range/1/minute/{date_str}/{date_str}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": config.POLYGON_API_KEY}
    
    try:
        resp = config.GLOBAL_SESSION.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("resultsCount", 0) > 0:
                df = pd.DataFrame(data["results"])
                df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 
                                   'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                return df
        elif resp.status_code == 429:
            log.warning("⚠️ Rate Limit! Sleeping 65s...")
            time.sleep(65)
            return None
    except Exception as e:
        log.error(f"SPY Fetch Error: {e}")
    return pd.DataFrame()

# ==============================================================================
# 4. YFINANCE WORKER (VIX -> VIX)
# ==============================================================================
def fetch_yfinance_vix():
    """Fetches 1-Hour VIX bars for the full year."""
    log.info(f"📊 Fetching VIX (1h) from YFinance ({START_STR} to {END_STR})...")
    try:
        # Fetch 1h data (valid for 730 days)
        df = yf.download("^VIX", start=START_STR, end=END_STR, interval="1h", progress=False, auto_adjust=True)
        if df.empty: return pd.DataFrame()
        
        df = df.reset_index()
        # Clean Columns (Handle MultiIndex if present)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.rename(columns={'Datetime': 'datetime_utc', 'Date': 'datetime_utc', 
                           'Open': 'open', 'High': 'high', 'Low': 'low', 
                           'Close': 'close', 'Volume': 'volume'}, inplace=True)
        
        # Strip Timezone
        if df['datetime_utc'].dt.tz is not None:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)

        # UPSAMPLE LOGIC (1h -> 1m)
        log.info("⚡ Upsampling VIX 1h -> 1m to match Schema...")
        df.set_index('datetime_utc', inplace=True)
        # Resample to 1min and forward fill the values (Step Function)
        df_1m = df.resample('1min').ffill()
        df_1m = df_1m.reset_index()
        
        # Filter strictly to market hours to reduce bloat (9:30 - 16:00)
        # (Optional, but keeps DB clean. For now, we keep all to be safe).
        
        return df_1m
    except Exception as e:
        log.error(f"VIX Fetch Error: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. EXECUTION
# ==============================================================================
def save_to_vault(df, ticker):
    if df.empty: return
    df['ticker'] = ticker
    try:
        con = duckdb.connect(str(config.DB_FILE))
        con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} (datetime_utc, ticker, open, high, low, close, volume) SELECT datetime_utc, ticker, open, high, low, close, volume FROM df")
        con.close()
    except Exception as e:
        log.error(f"DB Write Error: {e}")

def run_hybrid_ingest():
    log.info("🚀 STARTING HYBRID INDEX INGESTION")

    # PHASE 1: VIX (YFinance 1h -> Upsampled)
    df_vix = fetch_yfinance_vix()
    if not df_vix.empty:
        save_to_vault(df_vix, "VIX")
        log.info(f"✅ VIX HISTORY SECURED ({len(df_vix)} rows).")
    else:
        log.error("❌ VIX FETCH FAILED.")

    # PHASE 2: SPY (Polygon 1m)
    days = get_trading_days()
    log.info(f"📊 Starting SPY (SPX Proxy) Capture for {len(days)} days...")
    
    for i, date_str in enumerate(days):
        print(f"[{i+1}/{len(days)}] ⬇️ SPY {date_str} ... ", end='', flush=True)
        df = fetch_polygon_spy(date_str)
        if df is not None and not df.empty:
            save_to_vault(df, "SPX") # Save as SPX
            print(f"✅")
        else:
            print(f"⚠️")
        time.sleep(THROTTLE_DELAY)

    log.info("🎉 HYBRID INGEST COMPLETE.")

if __name__ == "__main__":
    run_hybrid_ingest()