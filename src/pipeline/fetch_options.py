import sys
import duckdb
import pandas as pd
import time
import requests
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionFetcher")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_KEY = config.POLYGON_API_KEY
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# FREE TIER SAFETY: 5 calls/min = 1 call every 12s.
# We use 20s to be extremely safe and account for network overhead.
SLEEP_SECONDS = 20
MAX_RETRIES = 3

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def construct_ticker(date_obj, xsp_price):
    try:
        yymmdd = date_obj.strftime('%y%m%d')
        strike = int(round(xsp_price))
        strike_str = f"{strike * 1000:08d}"
        return f"O:XSP{yymmdd}C{strike_str}"
    except:
        return None

def fetch_polygon_aggs(ticker, date_str):
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_KEY
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            # Use Global Session for consistent identity
            resp = config.GLOBAL_SESSION.get(url, params=params, timeout=15)
            
            if resp.status_code == 429:
                wait_time = 65 # Wait > 1 minute to reset the bucket
                log.warning(f"⚠️ Rate Limit Hit on {ticker}! Pausing for {wait_time}s...")
                time.sleep(wait_time)
                continue # Retry loop

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                    df = pd.DataFrame(data["results"])
                    # Map Polygon fields to our Schema
                    df.rename(columns={
                        't': 'datetime_utc', 
                        'o': 'open', 
                        'h': 'high', 
                        'l': 'low', 
                        'c': 'close', 
                        'v': 'volume'
                    }, inplace=True)
                    
                    # Convert timestamp (ms) to Datetime
                    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                    df['ticker'] = ticker
                    return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
                else:
                    # Valid response but no data (e.g. holiday or inactive contract)
                    return pd.DataFrame()

            # Handle non-200/429 errors (e.g., 500 Server Error)
            log.warning(f"⚠️ API Error {resp.status_code} for {ticker}. Retrying...")
            time.sleep(5)

        except requests.exceptions.RequestException as e:
            # Network errors (DNS, Timeout, Connection Refused)
            wait = (attempt + 1) * 10
            log.error(f"❌ Network Error for {ticker}: {e}. Retrying in {wait}s...")
            time.sleep(wait)
        
    return pd.DataFrame()

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def run_fetch_pipeline():
    log.info("🚀 Starting FREE TIER Option Data Ingestion (Safe Mode)...")
    log.info(f"⏳ Throttling: 1 request every {SLEEP_SECONDS} seconds")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Read Manifest
    try:
        manifest_df = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY date ASC").df()
    except Exception as e:
        log.error(f"Manifest missing. Run '02_scan_signals.py' first. ({e})")
        return

    if manifest_df.empty: return

    # 2. AUTO-HEAL TABLE (Schema & Index Check)
    rebuild_needed = False
    try:
        # A. Check Column Count
        col_count = con.execute(f"SELECT count(*) FROM pragma_table_info('{config.TBL_OPTIONS}')").fetchone()[0]
        if col_count != 7:
            log.warning(f"⚠️ Schema mismatch ({col_count} cols). Rebuilding...")
            rebuild_needed = True
        else:
            # B. Check for Primary Key
            pk_count = con.execute(f"""
                SELECT count(*) FROM duckdb_constraints 
                WHERE table_name = '{config.TBL_OPTIONS}' 
                AND constraint_type = 'PRIMARY KEY'
            """).fetchone()[0]
            if pk_count == 0:
                log.warning(f"⚠️ Missing Primary Key. Rebuilding...")
                rebuild_needed = True
    except:
        pass 

    if rebuild_needed:
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_OPTIONS}")

    # 3. Create Table (Correct Schema with PK)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_OPTIONS} (
            datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, 
            low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)

    # 4. Build Unique Task List
    unique_tasks = {}
    for _, row in manifest_df.iterrows():
        target_date = pd.to_datetime(row['date']).date()
        ticker = construct_ticker(target_date, row['xsp_price'])
        if ticker:
            unique_tasks[ticker] = target_date

    # 5. Filter Existing
    try:
        existing = set(con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS}").df()['ticker'])
    except:
        existing = set()

    final_queue = {k: v for k, v in unique_tasks.items() if k not in existing}
    
    log.info(f"📋 Manifest: {len(manifest_df)} | Unique: {len(unique_tasks)}")
    log.info(f"⬇️  Queue: {len(final_queue)} (Skipped {len(unique_tasks) - len(final_queue)} existing)")

    # 6. Execute Download
    processed = 0
    total = len(final_queue)
    
    for i, (ticker, target_date) in enumerate(final_queue.items()):
        date_str = target_date.strftime('%Y-%m-%d')
        print(f"[{i+1}/{total}] ⬇️ Downloading {ticker}...", end='\r')
        
        df = fetch_polygon_aggs(ticker, date_str)
        
        if not df.empty:
            con.execute(f"INSERT OR IGNORE INTO {config.TBL_OPTIONS} SELECT * FROM df")
            processed += 1
            log.info(f"✅ Saved {ticker} ({len(df)} bars)")
        else:
            log.warning(f"⚠️ No data found for {ticker} (Skipping)")

        # Force Sleep to respect Rate Limits
        time.sleep(SLEEP_SECONDS)

    con.close()
    log.info(f"\n🎉 Job Complete. Downloaded {processed} new contracts.")

if __name__ == "__main__":
    run_fetch_pipeline()