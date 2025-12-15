import sys
import time
import pandas as pd
import duckdb
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# This script is in 'ops/', so the Project Root is one level up
# Adjust: If ops/ is at root, parent is root.
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
except ImportError:
    # Fallback for standalone
    print("⚠️  Using Standalone Config.")
    class MockConfig:
        DB_FILE = ROOT_DIR / "data" / "quant_strategy.duckdb"
        POLYGON_API_KEY = "YOUR_KEY_HERE"
        TBL_OPTIONS = "options_1m"
        GLOBAL_SESSION = requests.Session()
    config = MockConfig()
    import logging
    logging.basicConfig(level=logging.INFO)
    def get_logger(name): return logging.getLogger(name)

log = get_logger("DeepFieldIngest")

# ==============================================================================
# 2. MISSION PARAMETERS
# ==============================================================================
# 🎯 TARGET CSV: Ensure this file is in your 'ops/' folder
CSV_FILENAME = "spx mini 1-yr - Sheet1.csv"
CSV_PATH = CURRENT_DIR / CSV_FILENAME 

BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# 🐢 FREE TIER THROTTLE: 13s (Safe)
THROTTLE_DELAY = 13.0 

# 🎯 KILL ZONE DEFINITION
STRIKE_BUFFER_LOW = 2   # Low - 2
STRIKE_BUFFER_HIGH = 2  # High + 2

# 🛑 HOLIDAY SKIP LIST (2025)
HOLIDAYS_2025 = {
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
    "2025-11-27", "2025-12-25"
}

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def parse_csv_map():
    """Reads User CSV (Cols G & H) to define the daily Kill Zone."""
    if not CSV_PATH.exists():
        log.error(f"❌ MAP NOT FOUND: {CSV_PATH}")
        return []

    try:
        # ⚡ Optimization: Only read what we need
        df = pd.read_csv(CSV_PATH)
        tasks = []
        
        # Verify Columns
        # Expecting: 'Date', 'Rounded Low', 'Rounded High'
        # If names differ, adjust here.
        if 'Rounded Low' not in df.columns or 'Rounded High' not in df.columns:
            log.error(f"❌ CSV Column Mismatch. Found: {df.columns}")
            return []

        for _, row in df.iterrows():
            try:
                raw_date = row['Date']
                dt = pd.to_datetime(raw_date)
                date_str = dt.strftime('%Y-%m-%d')
                
                if date_str in HOLIDAYS_2025: continue
                
                # 🎯 THE STRATEGY: High/Low Ranges
                low_target = int(row['Rounded Low'])
                high_target = int(row['Rounded High'])
                
                # Generate Strike List: [Low-2 ... High+2]
                start_strike = low_target - STRIKE_BUFFER_LOW
                end_strike = high_target + STRIKE_BUFFER_HIGH
                
                tasks.append({
                    'date': dt.date(),
                    'date_str': date_str,
                    'strikes': list(range(start_strike, end_strike + 1))
                })
            except Exception:
                pass
        return tasks
    except Exception as e:
        log.error(f"CSV Parse Error: {e}")
        return []

def generate_tickers(date_obj, strike_int):
    """Generates XSP Tickers (0DTE)."""
    yymmdd = date_obj.strftime('%y%m%d')
    strike_str = f"{strike_int * 1000:08d}"
    return f"O:XSP{yymmdd}C{strike_str}", f"O:XSP{yymmdd}P{strike_str}"

def fetch_polygon(ticker, date_str):
    """Downloads 1-minute bars (Free Tier Optimized)."""
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": config.POLYGON_API_KEY}
    
    try:
        resp = config.GLOBAL_SESSION.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("resultsCount", 0) > 0:
                df = pd.DataFrame(data["results"])
                df.rename(columns={'t':'datetime_utc', 'o':'open', 'h':'high', 'l':'low', 'c':'close', 'v':'volume'}, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                return df
        elif resp.status_code == 429:
            log.warning("⚠️ Rate Limit! Sleeping 65s...")
            time.sleep(65)
            return None
    except Exception as e:
        log.error(f"Fetch Error: {e}")
    return pd.DataFrame()

def save_to_vault(df, ticker, exp_date, strike, opt_type):
    """Commits to DuckDB Options Table."""
    if df.empty: return
    df['ticker'] = ticker
    df['expiration'] = exp_date
    df['strike'] = float(strike)
    df['type'] = opt_type
    
    try:
        con = duckdb.connect(str(config.DB_FILE))
        # ⚡ Optimization: Insert relevant cols
        con.execute(f"INSERT OR IGNORE INTO {config.TBL_OPTIONS} (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume) SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume FROM df")
        con.close()
    except Exception as e:
        log.error(f"DB Write Error: {e}")

# ==============================================================================
# 4. EXECUTION
# ==============================================================================
def run_deep_field():
    log.info("🚀 INITIALIZING DEEP FIELD PROTOCOL (CSV DRIVEN)")
    
    # 1. Load Map
    tasks = parse_csv_map()
    if not tasks: return

    # 2. SMART RESUME (The Optimizer)
    # Check what we already have in the Vault to skip it
    try:
        log.info("🔍 Scanning Vault for existing options...")
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Fast Set Lookup
        existing = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS}").df()
        existing_tickers = set(existing['ticker'])
        con.close()
        log.info(f"✅ Found {len(existing_tickers)} existing contracts. Skipping these.")
    except:
        existing_tickers = set()

    # 3. Build Queue
    queue = []
    for task in tasks:
        d_obj, d_str = task['date'], task['date_str']
        for k in task['strikes']:
            c_tick, p_tick = generate_tickers(d_obj, k)
            
            # ⚡ Optimization: Only add if missing
            if c_tick not in existing_tickers: queue.append((c_tick, d_str, d_obj, k, 'C'))
            if p_tick not in existing_tickers: queue.append((p_tick, d_str, d_obj, k, 'P'))

    log.info(f"📥 DOWNLOAD QUEUE: {len(queue)} Contracts.")
    if not queue:
        log.info("✅ ALL DATA PRESENT. NO ACTION NEEDED.")
        return

    # 4. Execute
    total = len(queue)
    for i, (ticker, date_str, exp_date, strike, o_type) in enumerate(queue):
        pct = ((i+1)/total)*100
        print(f"[{i+1}/{total}] {pct:.1f}% | ⬇️ {ticker} ... ", end='', flush=True)
        
        df = fetch_polygon(ticker, date_str)
        
        if df is not None and not df.empty:
            save_to_vault(df, ticker, exp_date, strike, o_type)
            print(f"✅ ({len(df)} bars)")
        else:
            print("⚠️ (No Data)")
        
        time.sleep(THROTTLE_DELAY)

if __name__ == "__main__":
    run_deep_field()