import sys
import time
import requests
import duckdb
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("HybridIngest")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
POLYGON_KEY = config.POLYGON_API_KEY
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

TICKER_MAP = [
    {"poly": "I:SPX", "yf": "^GSPC", "db": "SPX", "name": "S&P 500"},
    {"poly": "I:VIX", "yf": "^VIX",  "db": "VIX", "name": "CBOE Volatility"},
    {"poly": "I:IRX", "yf": "^IRX",  "db": "IRX", "name": "13-Week Treasury"},
]

# ==============================================================================
# 3. FETCHING LOGIC
# ==============================================================================
def fetch_polygon_day(ticker, date_str):
    """Attempts to fetch 1-minute aggregates for a single day from Polygon."""
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_KEY
    }
    try:
        resp = config.GLOBAL_SESSION.get(url, params=params, timeout=10)
        
        if resp.status_code == 403:
            log.warning(f"⛔ Polygon Blocked {ticker} (Tier Limit).")
            return None
            
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                df = pd.DataFrame(data["results"])
                df.rename(columns={
                    't': 'datetime_utc', 'o': 'open', 'h': 'high', 
                    'l': 'low', 'c': 'close', 'v': 'volume'
                }, inplace=True)
                df['datetime_utc'] = pd.to_datetime(df['datetime_utc'], unit='ms')
                return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        log.debug(f"Polygon fetch failed: {e}")
    return None

def fetch_yfinance_fallback(yf_sym, period="5d"):
    """Fallback method using Yahoo Finance."""
    log.info(f"⚠️ Triggering YFinance Fallback for {yf_sym}...")
    try:
        df = yf.download(yf_sym, period=period, interval="5m", progress=False, auto_adjust=True)
        if df.empty: return pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        df.columns = df.columns.str.lower()
        df.rename(columns={'datetime': 'datetime_utc', 'date': 'datetime_utc'}, inplace=True)
        
        # Standardize UTC
        if df['datetime_utc'].dt.tz is None:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_NY).dt.tz_convert(config.TZ_UTC)
        else:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        log.error(f"YFinance failed for {yf_sym}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. PIPELINE RUNNER
# ==============================================================================
def run_pipeline():
    log.info("🛡️ Starting Hybrid Indices Ingest...")
    con = duckdb.connect(str(config.DB_FILE))
    
    # Ensure Table
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (
            datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, 
            low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)

    end_date = datetime.now().date()
    dates = [end_date - timedelta(days=x) for x in range(5)]
    dates.reverse()

    # Explicit Column Order for DB Insertion
    DB_ORDER = ['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']

    for target in TICKER_MAP:
        poly_sym = target['poly']
        yf_sym = target['yf']
        db_sym = target['db']
        
        log.info(f"🔍 Processing {db_sym} ({target['name']})...")
        
        poly_success_count = 0
        
        for d in dates:
            date_str = d.strftime('%Y-%m-%d')
            df = fetch_polygon_day(poly_sym, date_str)
            
            if df is not None and not df.empty:
                df['ticker'] = db_sym
                # FIX: Enforce Column Order
                df = df[DB_ORDER]
                con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM df")
                poly_success_count += 1
                time.sleep(12) 

        if poly_success_count < 3:
            log.info(f"📉 Low Polygon yield for {db_sym}. Running bulk fallback...")
            df_yf = fetch_yfinance_fallback(yf_sym)
            if not df_yf.empty:
                df_yf['ticker'] = db_sym
                # FIX: Enforce Column Order
                df_yf = df_yf[DB_ORDER]
                con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM df_yf")
                log.info(f"✅ Repaired {db_sym} via Yahoo ({len(df_yf)} rows).")
        else:
            log.info(f"✨ Secured {db_sym} via Polygon ({poly_success_count} days).")

    con.close()
    log.info("🏁 Hybrid Ingest Complete.")

if __name__ == "__main__":
    run_pipeline()