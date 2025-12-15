import sys
import time
import pandas as pd
import duckdb
import requests
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# The script is in 'ops/', so the Project Root is two levels up relative to file resolution
# or one level up if 'ops' is a direct child of 'QUANT-OS'
# Adjustment: Path(__file__).resolve().parent is 'ops'. .parent.parent is Root.
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
except ImportError:
    # Fallback if running standalone without strict package structure
    print("⚠️  WARNING: Using standalone configuration (src not found).")
    class MockConfig:
        DB_FILE = ROOT_DIR / "data" / "quant_strategy.duckdb"
        POLYGON_API_KEY = "REPLACE_WITH_YOUR_KEY_IF_NEEDED"
        GLOBAL_SESSION = requests.Session()
    config = MockConfig()
    
    import logging
    logging.basicConfig(level=logging.INFO)
    def get_logger(name): return logging.getLogger(name)

log = get_logger("DeepFieldIngest")

# ==============================================================================
# 2. MISSION PARAMETERS (FREE TIER OPTIMIZED)
# ==============================================================================
# Exact filename provided by user
CSV_FILENAME = "spx mini 1-yr - Sheet1.csv"
CSV_PATH = CURRENT_DIR / CSV_FILENAME 

BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# ⚠️ CRITICAL: FREE TIER LIMIT IS 5 REQ/MIN
# 60s / 5 = 12s. We use 13s to be absolutely safe from 10-min IP bans.
THROTTLE_DELAY = 13.0 

# TARGET RANGE (Kill Zone)
# Captures 2 strikes below the Low and 2 strikes above the High
STRIKE_BUFFER_LOW = 2  
STRIKE_BUFFER_HIGH = 2 

# 2025 HOLIDAY CALENDAR (Source: Nasdaq/CBOE)
# Dates skipped to prevent 404 errors and wasted requests
HOLIDAYS_2025 = {
    "2025-01-01", # New Year
    "2025-01-20", # MLK Jr.
    "2025-02-17", # Presidents
    "2025-04-18", # Good Friday
    "2025-05-26", # Memorial
    "2025-06-19", # Juneteenth
    "2025-07-04", # Independence Day
    "2025-09-01", # Labor Day
    "2025-11-27", # Thanksgiving
    "2025-12-25"  # Christmas
}

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def parse_csv_map():
    """Reads the User's CSV to determine the 'Kill Zone' for each day."""
    if not CSV_PATH.exists():
        log.error(f"❌ CSV NOT FOUND: {CSV_PATH}")
        log.error("Please ensure the file is in the 'ops' folder with the exact name.")
        return []

    try:
        df = pd.read_csv(CSV_PATH)
        tasks = []
        
        # Verify required columns exist
        required_cols = ['Date', 'Rounded Low', 'Rounded High']
        if not all(col in df.columns for col in required_cols):
            log.error(f"❌ CSV Missing Columns. Found: {df.columns}")
            return []

        for _, row in df.iterrows():
            try:
                # Parse Date (Handles "Dec 8, 2025" format automatically via pandas)
                raw_date = row['Date']
                dt = pd.to_datetime(raw_date)
                date_str = dt.strftime('%Y-%m-%d')
                
                # Skip Holidays
                if date_str in HOLIDAYS_2025:
                    continue
                
                # Get Range from Columns
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
                
            except Exception as e:
                # Silently skip empty lines or footer text
                pass
                
        return tasks
    except Exception as e:
        log.error(f"CSV Parse Failed: {e}")
        return []

def generate_tickers(date_obj, strike_int):
    """Generates both CALL and PUT tickers for XSP (0DTE)."""
    # Format: O:XSP251208C00682000 (Strike is * 1000, padded to 8 chars)
    yymmdd = date_obj.strftime('%y%m%d')
    strike_str = f"{strike_int * 1000:08d}"
    
    call_ticker = f"O:XSP{yymmdd}C{strike_str}"
    put_ticker = f"O:XSP{yymmdd}P{strike_str}"
    
    return call_ticker, put_ticker

def fetch_polygon(ticker, date_str):
    """Downloads 1-minute bars with strict error handling."""
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": config.POLYGON_API_KEY
    }
    
    try:
        resp = config.GLOBAL_SESSION.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                df = pd.DataFrame(data["results"])
                # Map Polygon keys to our Schema
                df.rename(columns={
                    't': 'datetime_utc', 'o': 'open', 'h': 'high', 
                    'l': 'low', 'c': 'close', 'v': 'volume'
                }, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                return df
        elif resp.status_code == 429:
            log.warning("⚠️ RATE LIMIT HIT! Sleeping 65s...")
            time.sleep(65)
            return None # Retry logic handles this in the outer loop if needed
            
    except Exception as e:
        log.error(f"Fetch Error {ticker}: {e}")
        
    return pd.DataFrame() 

def save_to_vault(df, ticker, exp_date, strike, opt_type):
    """Commits data to DuckDB."""
    if df.empty: return
    
    df['ticker'] = ticker
    df['expiration'] = exp_date
    df['strike'] = float(strike)
    df['type'] = opt_type
    
    try:
        con = duckdb.connect(str(config.DB_FILE))
        # Use INSERT OR IGNORE to prevent duplicates
        con.execute(f"""
            INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
            (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume)
            SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume
            FROM df
        """)
        con.close()
    except Exception as e:
        log.error(f"DB Write Error: {e}")

# ==============================================================================
# 4. EXECUTION LOOP
# ==============================================================================
def run_deep_field():
    print(f"🚀 INITIALIZING DEEP FIELD PROTOCOL")
    print(f"📂 MAP: {CSV_PATH}")
    print(f"🐢 MODE: Free Tier (Throttle {THROTTLE_DELAY}s)")
    
    # 1. Load Map
    daily_tasks = parse_csv_map()
    if not daily_tasks:
        print("❌ ABORTING: No tasks generated. Check CSV.")
        return

    print(f"📅 TARGETS: {len(daily_tasks)} Trading Days")
    
    # 2. Audit Existing Data (Smart Resume)
    try:
        if config.DB_FILE.exists():
            con = duckdb.connect(str(config.DB_FILE), read_only=True)
            existing = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS}").df()
            existing_tickers = set(existing['ticker'])
            con.close()
        else:
            existing_tickers = set()
    except Exception as e:
        existing_tickers = set()
        print(f"⚠️ Vault check skipped: {e}")

    # 3. Build Download Queue
    queue = []
    for task in daily_tasks:
        d_obj = task['date']
        d_str = task['date_str']
        for k in task['strikes']:
            c_tick, p_tick = generate_tickers(d_obj, k)
            
            # Check if Call exists
            if c_tick not in existing_tickers:
                queue.append((c_tick, d_str, d_obj, k, 'C'))
            
            # Check if Put exists
            if p_tick not in existing_tickers:
                queue.append((p_tick, d_str, d_obj, k, 'P'))
                
    print(f"📥 DOWNLOAD QUEUE: {len(queue)} Contracts (Skipped {len(existing_tickers)} existing)")
    
    if not queue:
        print("✅ MISSION COMPLETE: All targets are already in the Vault.")
        return

    # 4. The Long March (Execution)
    total = len(queue)
    for i, (ticker, date_str, exp_date, strike, o_type) in enumerate(queue):
        
        # Visual Progress Bar
        pct = ((i+1) / total) * 100
        print(f"[{i+1}/{total}] {pct:.1f}% | ⬇️ {ticker} ... ", end='', flush=True)
        
        # Fetch
        df = fetch_polygon(ticker, date_str)
        
        # Save
        if df is not None and not df.empty:
            save_to_vault(df, ticker, exp_date, strike, o_type)
            print(f"✅ ({len(df)} bars)")
        else:
            print("⚠️ (No Data)")
        
        # ⚠️ THROTTLE (Mandatory for Free Tier)
        time.sleep(THROTTLE_DELAY)

    print("\n🎉 DEEP FIELD INGESTION COMPLETE.")

if __name__ == "__main__":
    run_deep_field()