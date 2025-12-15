import sys
import time
import duckdb
import pandas as pd
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE SETUP
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
    log = get_logger("VIX_Heavy")
except ImportError:
    print("❌ CRITICAL: Run this script from the project root or ops/ folder.")
    sys.exit(1)

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_URL = "https://api.polygon.io/v2/aggs/ticker"
TICKER = "I:VIX"
MULTIPLIER = 1
TIMESPAN = "minute"  # <--- CRITICAL: Changed from 'day' to 'minute' for Fractal Logic
LIMIT = 50000        # Polygon Max per Page

# Lookback: 1 Year (Aligned with your request)
END_DATE = datetime.now().date()
START_DATE = END_DATE - timedelta(days=365)
START_STR = START_DATE.strftime('%Y-%m-%d')
END_STR = END_DATE.strftime('%Y-%m-%d')

def fetch_polygon_pagination(start, end):
    """
    Fetches massive datasets using Polygon's 'next_url' cursor pagination.
    """
    log.info(f"⬇️  Initiating MASSIVE Ingest: {TICKER} [{TIMESPAN}]")
    log.info(f"📅  Range: {start} -> {end}")

    # Initial Request
    url = f"{POLYGON_URL}/{TICKER}/range/{MULTIPLIER}/{TIMESPAN}/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": LIMIT,
        "apiKey": config.POLYGON_API_KEY
    }

    all_results = []
    
    while url:
        try:
            # If we are using next_url, params are part of the URL, so we clear explicit params
            request_params = params if "polygon.io/v2" in url else {}
            
            resp = requests.get(url, params=request_params, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                
                # 1. Harvest Data
                if "results" in data:
                    all_results.extend(data["results"])
                    count = len(data["results"])
                    log.info(f"📦  Captured chunk: {count} bars... (Total: {len(all_results)})")
                
                # 2. Check for Pagination Cursor
                url = data.get("next_url", None)
                if url:
                    # Polygon requires API Key on next_url too
                    url += f"&apiKey={config.POLYGON_API_KEY}"
                    time.sleep(0.2) # Polite throttle
                
            elif resp.status_code == 429:
                log.warning("⚠️  Rate Limit (429). Holding for 65s...")
                time.sleep(65)
                # Do not advance URL, retry logic handles loop naturally if we implemented it,
                # but for simplicity here we just pause and continue.
                # Ideally, a retry loop is needed here, but keeping it simple:
                continue 
            else:
                log.error(f"❌ API Error {resp.status_code}: {resp.text}")
                break

        except Exception as e:
            log.error(f"❌ Network Failure: {e}")
            break

    return pd.DataFrame(all_results)

def process_and_store(df):
    if df.empty:
        log.warning("⚠️  No data retrieved.")
        return

    # 1. Rename Columns to Schema
    df.rename(columns={
        't': 'datetime_utc', 'o': 'open', 'h': 'high', 
        'l': 'low', 'c': 'close', 'v': 'volume'
    }, inplace=True)

    # 2. THE TIMEZONE LAW: Enforce UTC Naive
    # Polygon sends Unix MS -> Convert to UTC -> Drop Offset
    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms').dt.tz_localize('UTC').dt.tz_convert(None)
    
    # 3. Add Ticker Identity
    df['ticker'] = "VIX" # Storing as 'VIX', not '^VIX' to match Engine lookup
    df['volume'] = 0.0   # VIX has no volume

    # 4. Filter Columns
    final_df = df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
    
    # 5. Connect and Upsert
    try:
        log.info(f"🔌  Connecting to Vault: {config.DB_FILE}")
        con = duckdb.connect(str(config.DB_FILE))
        
        # Register for SQL access
        con.register('df_staging', final_df)
        
        # Transactional Upsert
        con.execute("BEGIN TRANSACTION")
        
        # Delete overlap to prevent duplicates (The precise surgical approach)
        con.execute(f"""
            DELETE FROM {config.TBL_INDICES} 
            WHERE ticker = 'VIX' 
            AND datetime_utc >= '{START_STR}' 
            AND datetime_utc <= '{END_STR}'
        """)
        
        # Insert Fresh Data
        con.execute(f"""
            INSERT INTO {config.TBL_INDICES} 
            SELECT * FROM df_staging
        """)
        
        con.execute("COMMIT")
        con.close()
        log.info(f"✅  SUCCESS: Ingested {len(final_df)} bars into {config.TBL_INDICES}.")
        
    except Exception as e:
        log.critical(f"❌  DB Write Crash: {e}")
        try: con.rollback() 
        except: pass

if __name__ == "__main__":
    print(f"\n⚔️  QUANT OS v3.3: VIX MASSIVE INGEST")
    print("=======================================")
    print(f"Target: {TICKER}")
    print(f"Resolution: {TIMESPAN} (Required for Fractal Flow)")
    
    # Fetch
    raw_df = fetch_polygon_pagination(START_STR, END_STR)
    
    # Store
    process_and_store(raw_df)