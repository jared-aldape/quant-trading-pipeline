import sys
import duckdb
import pandas as pd
import requests
import time
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IndexIngest")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_KEY = config.POLYGON_API_KEY
BASE_URL = "https://api.polygon.io"

# ⚡ CONFIG UPDATE: REMOVED SPX.
# We only need XSP (Tradeable) and VIX (Context, if available).
TARGETS = {
    'VIX': 'I:VIX',
    'XSP': 'I:XSP' 
}
# Default historical start point if DB is empty
HISTORICAL_START_DATE = datetime(2024, 1, 1).date() 

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def get_download_range(con, ticker):
    """
    Determines the start date for the download.
    Start date = MAX(datetime_utc) in DB + 1 minute.
    If DB is empty, use HISTORICAL_START_DATE.
    """
    try:
        # Check if table exists
        tables = con.execute("SHOW TABLES").fetchall()
        if config.TBL_INDICES not in [t[0] for t in tables]:
            return HISTORICAL_START_DATE.strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')

        # Get max date for specific ticker
        res = con.execute(f"""
            SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = '{ticker}'
        """).fetchone()
        
        last_date = res[0]
        
        if last_date:
            # Start from next day/minute? API handles overlaps well, but let's be safe.
            # Polygon range is inclusive.
            start_dt = pd.to_datetime(last_date).date()
            return start_dt.strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')
        else:
            return HISTORICAL_START_DATE.strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')
            
    except Exception as e:
        log.error(f"Date Range Error: {e}")
        return datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d')

def fetch_index_data(ticker, start_date, end_date):
    """
    Fetches 1-minute bars from Polygon.
    """
    # If fetching today, might be partial.
    url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{start_date}/{end_date}"
    params = {
        "adjusted": "true", 
        "sort": "asc", 
        "limit": 50000, 
        "apiKey": POLYGON_KEY
    }
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        
        if resp.status_code == 403:
            log.warning(f"⚠️ Permission Denied for {ticker} (403). Skipping.")
            return pd.DataFrame()
            
        if resp.status_code != 200:
            log.error(f"❌ API Error {ticker}: {resp.status_code}")
            return pd.DataFrame()
            
        data = resp.json()
        if data.get('resultsCount', 0) > 0:
            df = pd.DataFrame(data['results'])
            # Standardize
            df.rename(columns={'t': 'datetime_utc', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
            df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
            
            # Map back to internal ticker name (e.g. I:XSP -> XSP)
            friendly_name = [k for k, v in TARGETS.items() if v == ticker][0]
            df['ticker'] = friendly_name
            
            return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
        else:
            log.warning(f"⚠️ No NEW data found for {ticker}")
            return pd.DataFrame()
            
    except Exception as e:
        log.error(f"Fetch Error {ticker}: {e}")
        return pd.DataFrame()

def run_ingest():
    """Main Entry Point called by Pipeline."""
    log.info("📊 STARTING INDEX HARVEST (XSP/VIX)")
    
    if not config.DB_FILE.exists():
        log.error("❌ No Database found.")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (
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
    
    total_rows = 0
    
    for friendly_name, poly_ticker in TARGETS.items():
        start_str, end_str = get_download_range(con, friendly_name)
        log.info(f"DB check: Starting {friendly_name} harvest from latest data: {start_str}")
        log.info(f"⬇️ Fetching {friendly_name} from {start_str} to {end_str}...")
        
        df = fetch_index_data(poly_ticker, start_str, end_str)
        
        if not df.empty:
            count = len(df)
            total_rows += count
            con.register('temp_idx', df)
            con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM temp_idx")
            
    con.close()
    log.info(f"🏁 Index Harvest Complete. Total Rows: {total_rows}")

if __name__ == "__main__":
    run_ingest()