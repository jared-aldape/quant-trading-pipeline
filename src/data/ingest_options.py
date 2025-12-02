import sys
import duckdb
import pandas as pd
import time
import requests
import re
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: src/data/ingest_options.py
# Root: ../../
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

# SAFETY & LIMITS
SLEEP_SECONDS = 20 # Free Tier throttling
MAX_RETRIES = 3
MIN_BAR_THRESHOLD = 30 
STRIKE_RANGE = 2   # ATM +/- 2 strikes

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================
def parse_ticker_metadata(ticker):
    """
    Parses O:XSP231215C00460000 into components.
    Returns: (expiration_date, type, strike)
    """
    try:
        # Regex for Polygon Options Ticker
        match = re.search(r'O:[A-Z]+(\d{6})([CP])(\d{8})', ticker)
        if match:
            date_str, type_char, strike_str = match.groups()
            
            # 1. Expiration Date
            exp_date = datetime.strptime(date_str, '%y%m%d').date()
            
            # 2. Strike Price (Polygon uses 1/1000th scaling)
            strike = float(strike_str) / 1000.0
            
            return exp_date, type_char, strike
    except Exception as e:
        pass
    return None, None, None

def construct_ticker_cluster(date_obj, xsp_price, trade_type='call'):
    """
    Returns a LIST of tickers based on Trade Type.
    """
    tickers = []
    try:
        yymmdd = date_obj.strftime('%y%m%d')
        atm_strike = int(round(xsp_price))
        
        # Determine necessary types
        types_to_fetch = []
        if trade_type.lower() == 'call':
            types_to_fetch = ['C']
        elif trade_type.lower() == 'put':
            types_to_fetch = ['P']
        elif trade_type.lower() == 'straddle':
            types_to_fetch = ['C', 'P']
        else:
            types_to_fetch = ['C'] # Default
            
        # Generate Cluster (Strikes x Types)
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1): # FIX: Corrected typo STRike_RANGE -> STRIKE_RANGE
            strike = atm_strike + offset
            strike_str = f"{strike * 1000:08d}"
            
            for t_char in types_to_fetch:
                ticker = f"O:XSP{yymmdd}{t_char}{strike_str}"
                tickers.append(ticker)
            
    except Exception as e:
        log.error(f"Ticker construction failed: {e}")
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
                log.warning(f"⛔ 403 Forbidden for {ticker}. (Data unavailable/Date range?)")
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
# 4. PIPELINE RUNNER
# ==============================================================================
def run_fetch_pipeline():
    log.info("🚀 Starting Option Data Ingestion (Cluster Mode)...")
    log.info(f"⏳ Throttling: 1 request every {SLEEP_SECONDS} seconds")
    
    # 1. READ MANIFEST (Need a connection to READ, which we close immediately)
    try:
        with duckdb.connect(str(config.DB_FILE), read_only=True) as con_read:
            query = f"""
                SELECT date, xsp_price, COALESCE(trade_type, 'call') as trade_type 
                FROM {config.TBL_MANIFEST} 
                ORDER BY date ASC
            """
            manifest_df = con_read.execute(query).df()
    except Exception as e:
        log.error(f"Manifest missing or schema error. Run 'engine_scanner.py' first. ({e})")
        return

    if manifest_df.empty: return

    # 2. BUILD QUEUE & AUDIT (Audit must also be read-only/closed)
    unique_tasks = {}
    today = datetime.now().date()
    
    for _, row in manifest_df.iterrows():
        target_date = pd.to_datetime(row['date']).date()
        if target_date >= today: continue 
        
        cluster = construct_ticker_cluster(target_date, row['xsp_price'], row['trade_type'])
        
        for ticker in cluster:
            unique_tasks[ticker] = target_date
            
    # AUDIT: Determine which contracts are missing in the new table
    log.info("🔍 Auditing existing data...")
    try:
        with duckdb.connect(str(config.DB_FILE), read_only=True) as con_audit:
             audit_df = con_audit.execute(f"SELECT ticker, COUNT(*) as cnt FROM {config.TBL_OPTIONS} GROUP BY ticker").df()
             audit_map = dict(zip(audit_df['ticker'], audit_df['cnt']))
    except Exception as e:
        log.warning(f"Audit failed (Likely empty new table). Proceeding to full download. Error: {e}")
        audit_map = {}

    final_queue = {}
    skipped_count = 0
    
    for ticker, target_date in unique_tasks.items():
        if audit_map.get(ticker, 0) >= MIN_BAR_THRESHOLD:
            skipped_count += 1
        else:
            final_queue[ticker] = target_date

    log.info(f"📋 Manifest Signals: {len(manifest_df)} | Total Contracts: {len(unique_tasks)}")
    log.info(f"⬇️  Queue: {len(final_queue)} (Skipped {skipped_count} healthy contracts)")

    # 3. DOWNLOAD & INSERT (Acquire Lock ONLY for Insertion)
    processed = 0
    total = len(final_queue)
    
    for i, (ticker, target_date) in enumerate(final_queue.items()):
        date_str = target_date.strftime('%Y-%m-%d')
        print(f"[{i+1}/{total}] ⬇️ Downloading {ticker}...", end='\r')
        
        df = fetch_polygon_aggs(ticker, date_str)
        
        if not df.empty:
            # PARSE METADATA (Expiration, Type, Strike)
            exp, typ, strk = parse_ticker_metadata(ticker)
            
            df['expiration'] = exp
            df['type'] = typ
            df['strike'] = strk
            
            # INSERT: Acquire Write Lock (briefly)
            try:
                with duckdb.connect(str(config.DB_FILE)) as con_write:
                    con_write.register('df', df)
                    con_write.execute(f"""
                        INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                        (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume)
                        SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume
                        FROM df
                    """)
                log.info(f"✅ Saved {ticker} ({len(df)} bars)")
                processed += 1
            except Exception as e:
                log.error(f"Database insertion failed for {ticker}: {e}")
        else:
            log.warning(f"⚠️ No data for {ticker} (Skipping)")

        # Release lock during long wait period
        time.sleep(SLEEP_SECONDS)

    log.info(f"\n🎉 Job Complete. Downloaded {processed} contracts.")

if __name__ == "__main__":
    run_fetch_pipeline()
