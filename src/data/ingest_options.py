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

# SMART CONFIG
# We start fast. We slow down only if forced.
BURST_DELAY = 0.25       # Quarter second between requests (Optimistic)
COOLDOWN_DELAY = 65      # If 429 hit, wait 1 minute + buffer
MAX_RETRIES = 3
MIN_BAR_THRESHOLD = 30   # If DB has >30 bars, skip download
STRIKE_RANGE = 2         # ATM +/- 2 strikes

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
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
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
    """
    Fetches data using the Optimistic Burst Protocol.
    Returns: (DataFrame, Status_String)
    """
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
            
            # --- SCENARIO A: SUCCESS ---
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
                    # Normalize columns
                    return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']], "OK"
                else:
                    return pd.DataFrame(), "EMPTY"

            # --- SCENARIO B: RATE LIMIT (The Wall) ---
            if resp.status_code == 429:
                log.warning(f"🛑 RATE LIMIT HIT on {ticker}. Engaging Cool Down ({COOLDOWN_DELAY}s)...")
                time.sleep(COOLDOWN_DELAY) 
                continue # Retry immediately loop

            # --- SCENARIO C: PERMANENT ERROR ---
            if resp.status_code == 403:
                # log.warning(f"⛔ 403 Forbidden for {ticker}.")
                return pd.DataFrame(), "FORBIDDEN"

            # --- SCENARIO D: SERVER ERROR ---
            log.warning(f"⚠️ API Error {resp.status_code} for {ticker}. Retrying...")
            time.sleep(5)

        except requests.exceptions.RequestException as e:
            wait = (attempt + 1) * 5
            log.error(f"❌ Network Error for {ticker}: {e}. Retrying in {wait}s...")
            time.sleep(wait)
        
    return pd.DataFrame(), "FAILED"

# ==============================================================================
# 4. PIPELINE RUNNER
# ==============================================================================
def run_fetch_pipeline():
    log.info("🚀 Starting Option Data Ingestion (Optimistic Burst Mode)...")
    
    # 1. READ MANIFEST
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

    # 2. BUILD QUEUE
    unique_tasks = {}
    today = datetime.now().date()
    
    for _, row in manifest_df.iterrows():
        target_date = pd.to_datetime(row['date']).date()
        if target_date >= today: continue 
        
        cluster = construct_ticker_cluster(target_date, row['xsp_price'], row['trade_type'])
        for ticker in cluster:
            unique_tasks[ticker] = target_date
            
    # 3. AUDIT (Skip what we already have)
    log.info("🔍 Auditing existing data...")
    try:
        with duckdb.connect(str(config.DB_FILE), read_only=True) as con_audit:
             audit_df = con_audit.execute(f"SELECT ticker, COUNT(*) as cnt FROM {config.TBL_OPTIONS} GROUP BY ticker").df()
             audit_map = dict(zip(audit_df['ticker'], audit_df['cnt']))
    except:
        audit_map = {}

    final_queue = {}
    skipped_count = 0
    
    for ticker, target_date in unique_tasks.items():
        if audit_map.get(ticker, 0) >= MIN_BAR_THRESHOLD:
            skipped_count += 1
        else:
            final_queue[ticker] = target_date

    log.info(f"📋 Manifest: {len(manifest_df)} signals | Queue: {len(final_queue)} contracts (Skipped {skipped_count})")

    # 4. DOWNLOAD & INSERT (Burst Mode)
    processed = 0
    total = len(final_queue)
    start_time = time.time()
    
    for i, (ticker, target_date) in enumerate(final_queue.items()):
        date_str = target_date.strftime('%Y-%m-%d')
        
        # Calculate speed for display
        elapsed = time.time() - start_time
        speed = (processed / elapsed) if elapsed > 0 else 0
        print(f"[{i+1}/{total}] ⚡ {speed:.1f} req/s | Fetching {ticker}...", end='\r')
        
        df, status = fetch_polygon_aggs(ticker, date_str)
        
        if not df.empty:
            exp, typ, strk = parse_ticker_metadata(ticker)
            df['expiration'] = exp
            df['type'] = typ
            df['strike'] = strk
            
            try:
                # Brief Write Lock
                with duckdb.connect(str(config.DB_FILE)) as con_write:
                    con_write.register('df', df)
                    con_write.execute(f"""
                        INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                        (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume)
                        SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume
                        FROM df
                    """)
                processed += 1
            except Exception as e:
                log.error(f"DB Write Error: {e}")

        # OPTIMISTIC DELAY
        # If we didn't hit 429, we only sleep a tiny bit to be polite.
        time.sleep(BURST_DELAY)

    log.info(f"\n🎉 Job Complete. Downloaded {processed} contracts.")

if __name__ == "__main__":
    run_fetch_pipeline()