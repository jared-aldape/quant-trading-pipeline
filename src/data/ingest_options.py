import sys
import duckdb
import pandas as pd
import time
import requests
import re
from datetime import datetime, timedelta  # <--- FIXED IMPORT
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionIngest")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_KEY = config.POLYGON_API_KEY
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# BATCH CONFIG
BURST_DELAY = 12.5       # Safe pacing for Basic Plan (5 calls/min)
BATCH_SIZE = 5           # Commit to DB every 5 contracts
DNS_ERROR_DELAY = 30     # Long pause if network chokes
MAX_RETRIES = 3
STRIKE_RANGE = 2         

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def parse_ticker_metadata(ticker):
    try:
        match = re.search(r'O:[A-Z]+(\d{6})([CP])(\d{8})', ticker)
        if match:
            date_str, type_char, strike_str = match.groups()
            exp_date = datetime.strptime(date_str, '%y%m%d').date()
            strike = float(strike_str) / 1000.0
            return exp_date, type_char, strike
    except: pass
    return None, None, None

def construct_ticker_cluster(date_obj, xsp_price, trade_type='call'):
    tickers = []
    try:
        yymmdd = date_obj.strftime('%y%m%d')
        atm_strike = int(round(xsp_price))
        types = ['C'] if trade_type.lower() == 'call' else ['P']
        
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm_strike + offset
            strike_str = f"{strike * 1000:08d}"
            for t in types:
                tickers.append(f"O:XSP{yymmdd}{t}{strike_str}")
    except: pass
    return tickers

def fetch_polygon_aggs(ticker, date_str):
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": POLYGON_KEY}
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=20)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                    df = pd.DataFrame(data["results"])
                    df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
                    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                    df['ticker'] = ticker
                    return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']], "OK"
                else:
                    return pd.DataFrame(), "EMPTY"

            if resp.status_code == 429:
                log.warning(f"🛑 RATE LIMIT on {ticker}. Cooling down 65s...")
                time.sleep(65)
                continue 

            if resp.status_code in [403, 404]:
                return pd.DataFrame(), "MISSING"

            time.sleep(2)

        except requests.exceptions.RequestException as e:
            # Handle DNS/Connection errors specifically
            log.error(f"❌ Network Error ({e}). Pausing {DNS_ERROR_DELAY}s...")
            time.sleep(DNS_ERROR_DELAY)
        
    return pd.DataFrame(), "FAILED"

# ==============================================================================
# 4. PIPELINE RUNNER
# ==============================================================================
def run_fetch_pipeline():
    log.info("🚀 Starting Option Data Ingestion (Batch Mode)...")
    
    # 1. READ MANIFEST
    try:
        with duckdb.connect(str(config.DB_FILE), read_only=True) as con_read:
            query = f"SELECT date, xsp_price, COALESCE(trade_type, 'call') as trade_type FROM {config.TBL_MANIFEST} ORDER BY date ASC"
            manifest_df = con_read.execute(query).df()
    except Exception as e:
        log.error(f"Manifest Error: {e}")
        return

    if manifest_df.empty: return

    # 2. BUILD QUEUE
    unique_tasks = {}
    today = datetime.now().date()
    
    for _, row in manifest_df.iterrows():
        target_date = pd.to_datetime(row['date']).date()
        if target_date >= today: continue 
        cluster = construct_ticker_cluster(target_date, row['xsp_price'], row['trade_type'])
        for ticker in cluster: unique_tasks[ticker] = target_date
            
    # 3. AUDIT
    log.info("🔍 Auditing existing data...")
    try:
        with duckdb.connect(str(config.DB_FILE), read_only=True) as con_audit:
             audit_df = con_audit.execute(f"SELECT ticker FROM {config.TBL_OPTIONS} GROUP BY ticker").df()
             existing_tickers = set(audit_df['ticker'].tolist())
    except: existing_tickers = set()

    final_queue = {}
    skipped_count = 0
    for ticker, target_date in unique_tasks.items():
        if ticker in existing_tickers: skipped_count += 1
        else: final_queue[ticker] = target_date

    queue_list = list(final_queue.items())
    total_items = len(queue_list)
    log.info(f"📋 Queue: {total_items} contracts (Skipped {skipped_count})")

    # 4. EXECUTION
    processed = 0
    errors = 0
    start_time = time.time()
    
    # Process in Batches
    for i, (ticker, target_date) in enumerate(queue_list):
        date_str = target_date.strftime('%Y-%m-%d')
        
        # Calculate ETA
        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        remaining_items = total_items - (i + 1)
        eta_seconds = avg_time * remaining_items
        eta_str = str(timedelta(seconds=int(eta_seconds)))
        
        # Progress Bar
        pct = int(((i+1) / total_items) * 100)
        bar = "█" * (pct // 5) + "-" * (20 - (pct // 5))
        
        print(f"\r[{bar}] {pct}% | {i+1}/{total_items} | ETA: {eta_str} | Fetching {ticker}...", end='')
        
        df, status = fetch_polygon_aggs(ticker, date_str)
        
        if status == "FAILED":
            errors += 1
        elif not df.empty:
            exp, typ, strk = parse_ticker_metadata(ticker)
            df['expiration'] = exp
            df['type'] = typ
            df['strike'] = strk
            
            try:
                # Commit immediately to save progress
                with duckdb.connect(str(config.DB_FILE)) as con_write:
                    con_write.register('df', df)
                    con_write.execute(f"INSERT OR IGNORE INTO {config.TBL_OPTIONS} SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume, NULL, NULL, NULL, NULL, NULL, NULL, NULL FROM df")
                processed += 1
            except Exception as e:
                log.error(f"\n❌ DB Error: {e}")

        # Pacing
        time.sleep(BURST_DELAY)

    print("") # Newline after progress bar
    log.info(f"🎉 Job Complete. Downloaded {processed} contracts. Errors: {errors}")

if __name__ == "__main__":
    run_fetch_pipeline()