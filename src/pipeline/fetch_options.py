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

# FREE TIER SAFETY
SLEEP_SECONDS = 20
MAX_RETRIES = 3

# SMART AUDIT THRESHOLD
MIN_BAR_THRESHOLD = 30 

# [NEW] CLUSTER FETCHING
# Must match the STRIKE_RANGE in 08_dashboard.py
STRIKE_RANGE = 2 

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def construct_ticker_cluster(date_obj, xsp_price):
    """
    Returns a LIST of tickers (ATM +/- STRIKE_RANGE)
    """
    tickers = []
    try:
        yymmdd = date_obj.strftime('%y%m%d')
        atm_strike = int(round(xsp_price))
        
        # Generate Cluster
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm_strike + offset
            strike_str = f"{strike * 1000:08d}"
            ticker = f"O:XSP{yymmdd}C{strike_str}"
            tickers.append(ticker)
            
    except:
        pass
    return tickers

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
            resp = config.GLOBAL_SESSION.get(url, params=params, timeout=15)
            
            if resp.status_code == 403:
                log.warning(f"⛔ Permission Denied (403) for {ticker}. Check Subscription/Date.")
                return pd.DataFrame()

            if resp.status_code == 429:
                wait_time = 65 
                log.warning(f"⚠️ Rate Limit Hit on {ticker}! Pausing for {wait_time}s...")
                time.sleep(wait_time)
                continue 

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                    df = pd.DataFrame(data["results"])
                    df.rename(columns={
                        't': 'datetime_utc', 'o': 'open', 'h': 'high', 
                        'l': 'low', 'c': 'close', 'v': 'volume'
                    }, inplace=True)
                    
                    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                    df['ticker'] = ticker
                    return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
                else:
                    return pd.DataFrame()

            log.warning(f"⚠️ API Error {resp.status_code} for {ticker}. Retrying...")
            time.sleep(5)

        except requests.exceptions.RequestException as e:
            wait = (attempt + 1) * 10
            log.error(f"❌ Network Error for {ticker}: {e}. Retrying in {wait}s...")
            time.sleep(wait)
        
    return pd.DataFrame()

# ==============================================================================
# 4. CORE LOGIC
# ==============================================================================
def run_fetch_pipeline():
    log.info("🚀 Starting Option Data Ingestion (Cluster Mode)...")
    log.info(f"⏳ Throttling: 1 request every {SLEEP_SECONDS} seconds")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Read Manifest
    try:
        manifest_df = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY date ASC").df()
    except Exception as e:
        log.error(f"Manifest missing. Run '02_scan_signals.py' first. ({e})")
        return

    if manifest_df.empty: return

    # 2. Ensure Table Exists
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_OPTIONS} (
            datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, 
            low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)

    # 3. Build Task List (Cluster Expansion)
    unique_tasks = {}
    today = datetime.now().date()
    
    for _, row in manifest_df.iterrows():
        target_date = pd.to_datetime(row['date']).date()
        if target_date >= today: continue 
        
        # [NEW] Get List of 5 Tickers instead of 1
        cluster = construct_ticker_cluster(target_date, row['xsp_price'])
        for ticker in cluster:
            unique_tasks[ticker] = target_date

    # 4. Smart Audit
    log.info("🔍 Auditing existing data quality...")
    try:
        audit_df = con.execute(f"SELECT ticker, COUNT(*) as cnt FROM {config.TBL_OPTIONS} GROUP BY ticker").df()
        audit_map = dict(zip(audit_df['ticker'], audit_df['cnt']))
    except:
        audit_map = {}

    final_queue = {}
    skipped_count = 0
    
    for ticker, target_date in unique_tasks.items():
        row_count = audit_map.get(ticker, 0)
        
        if row_count >= MIN_BAR_THRESHOLD:
            skipped_count += 1
        else:
            final_queue[ticker] = target_date

    log.info(f"📋 Manifest Signals: {len(manifest_df)} | Total Contracts (ATM+/-2): {len(unique_tasks)}")
    log.info(f"⬇️  Queue: {len(final_queue)} (Skipped {skipped_count} healthy contracts)")

    # 5. Execute Download
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

        time.sleep(SLEEP_SECONDS)

    con.close()
    log.info(f"\n🎉 Job Complete. Downloaded/Repaired {processed} contracts.")

if __name__ == "__main__":
    run_fetch_pipeline()