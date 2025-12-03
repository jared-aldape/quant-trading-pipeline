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
# File: src/data/ingest_indices.py
# Root: ../../
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

# Map Tickers to their specific processing logic and FALLBACK PERIOD
# NOTE: Yahoo Finance 5m data is strictly limited to the last 60 days.
# We set fallback_period to '59d' to safely stay within this limit.
TICKER_MAP = [
    {"poly": "I:SPX", "yf": "^GSPC", "db": "SPX", "type": "INDEX", "name": "S&P 500", "fallback_period": "59d"},
    {"poly": "I:VIX", "yf": "^VIX",  "db": "VIX", "type": "INDEX", "name": "CBOE Volatility", "fallback_period": "59d"},
    
    # NEW: Futures Overlay (Use Yahoo 'ES=F' as primary for Continuous Contract)
    # We leave 'poly' empty or dummy because continuous futures on Polygon require complex tickers
    {"poly": "---",   "yf": "ES=F",  "db": "ES",  "type": "FUTURE", "name": "E-Mini S&P 500", "fallback_period": "59d"},

    # IRX is just for rate data, 5d is sufficient as it only needs a daily close
    {"poly": "I:IRX", "yf": "^IRX",  "db": "IRX", "type": "RATE",  "name": "13-Week Treasury", "fallback_period": "5d"},
]

# ==============================================================================
# 3. FETCHING LOGIC
# ==============================================================================
def fetch_polygon_day(ticker, date_str):
    """Attempts to fetch 1-minute aggregates for a single day from Polygon."""
    if ticker == "---": return None # Skip if no Polygon ticker defined

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
            log.warning(f"⛔ Polygon Blocked {ticker} (Tier Limit or Data Unavailable).")
            return None
            
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("resultsCount", 0) > 0:
                df = pd.DataFrame(data["results"])
                # Standard Polygon Map
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
    log.info(f"⚠️ Triggering YFinance Fallback for {yf_sym} using period={period}...")
    try:
        # Fetch data
        df = yf.download(yf_sym, period=period, interval="5m", progress=False, auto_adjust=True)
        if df.empty: return pd.DataFrame()
        
        # Flatten MultiIndex (Yahoo 0.2+ quirk)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        df.columns = df.columns.str.lower()
        df.rename(columns={'datetime': 'datetime_utc', 'date': 'datetime_utc'}, inplace=True)
        
        # Standardize UTC (Timezone Law)
        if df['datetime_utc'].dt.tz is None:
            # Assume NY if naive, then convert to UTC
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_NY).dt.tz_convert(config.TZ_UTC)
        else:
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            
        # Strip TZ for DuckDB compatibility
        df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)
        
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        log.error(f"YFinance failed for {yf_sym}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. INGESTION ROUTINES
# ==============================================================================
def save_indices(con, df, db_sym):
    """Saves High-Frequency Index Data (SPX, VIX)."""
    if df.empty: return
    df['ticker'] = db_sym
    # Enforce Schema Order: datetime_utc, ticker, open, high, low, close, volume
    df = df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
    con.execute(f"INSERT OR IGNORE INTO {config.TBL_INDICES} SELECT * FROM df")

def save_futures(con, df, db_sym):
    """Saves Futures Data to TBL_FUTURES."""
    if df.empty: return
    df['ticker'] = db_sym
    # Enforce Schema Order matching TBL_FUTURES in db_schema.py
    df = df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
    con.execute(f"INSERT OR IGNORE INTO {config.TBL_FUTURES} SELECT * FROM df")
    
def save_rates(con, df, db_sym):
    """
    Saves Daily Risk-Free Rate (IRX).
    Converts intraday bars to a single daily close rate.
    """
    if df.empty: return
    
    # Create a daily view: Take the last close of each day
    df['date'] = df['datetime_utc'].dt.date
    daily_rates = df.sort_values('datetime_utc').groupby('date').last().reset_index()
    
    # Prepare for TBL_IRX (date, rate)
    daily_rates = daily_rates[['date', 'close']]
    daily_rates.rename(columns={'close': 'rate'}, inplace=True)
    
    # Upsert Logic
    con.execute(f"""
        INSERT OR REPLACE INTO {config.TBL_IRX} (date, rate)
        SELECT date, rate FROM daily_rates
    """)

# ==============================================================================
# 5. PIPELINE RUNNER
# ==============================================================================
def run_pipeline():
    log.info("🛡️ Starting Hybrid Ingest (Indices + Futures + Rates)...")
    con = duckdb.connect(str(config.DB_FILE))
    
    # Lookback window for Polygon (still 5 days for the latest history)
    end_date = datetime.now().date()
    dates = [end_date - timedelta(days=x) for x in range(5)]
    dates.reverse()

    for target in TICKER_MAP:
        poly_sym = target['poly']
        yf_sym = target['yf']
        db_sym = target['db']
        asset_type = target['type']
        fallback_period = target.get('fallback_period', '5d')
        
        log.info(f"🔍 Processing {db_sym} ({target['name']})...")
        
        poly_success_count = 0
        
        # 1. Try Polygon (The Truth) - Skipped if poly_sym is "---"
        if poly_sym != "---":
            for d in dates:
                date_str = d.strftime('%Y-%m-%d')
                df = fetch_polygon_day(poly_sym, date_str)
                
                if df is not None and not df.empty:
                    if asset_type == "INDEX": save_indices(con, df, db_sym)
                    elif asset_type == "FUTURE": save_futures(con, df, db_sym)
                    elif asset_type == "RATE": save_rates(con, df, db_sym)
                        
                    poly_success_count += 1
                    time.sleep(12) 

        # 2. Try Yahoo Fallback (The Backup) - Use extended period
        # For Futures (ES), we ALWAYS hit this because poly_sym is "---", effectively making Yahoo the primary.
        if poly_success_count < 3:
            log.info(f"📉 Low Polygon yield for {db_sym}. Running bulk fallback...")
            df_yf = fetch_yfinance_fallback(yf_sym, period=fallback_period)
            
            if not df_yf.empty:
                if asset_type == "INDEX": save_indices(con, df_yf, db_sym)
                elif asset_type == "FUTURE": save_futures(con, df_yf, db_sym)
                elif asset_type == "RATE": save_rates(con, df_yf, db_sym)
                log.info(f"✅ Repaired {db_sym} via Yahoo ({len(df_yf)} rows).")
        else:
            log.info(f"✨ Secured {db_sym} via Polygon ({poly_success_count} days).")

    con.close()
    log.info("🏁 Hybrid Ingest Complete.")

if __name__ == "__main__":
    run_pipeline()