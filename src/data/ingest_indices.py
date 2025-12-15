import sys
import duckdb
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

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
TARGETS = {
    'VIX': '^VIX',
    'XSP': '^XSP' 
}
HISTORICAL_START_DATE = datetime(2024, 1, 1).date() 

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def get_start_date(con, ticker):
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if config.TBL_INDICES not in [t[0] for t in tables]:
            return HISTORICAL_START_DATE

        # Query by clean ticker (e.g., 'XSP')
        clean_ticker = ticker.replace('^', '')
        res = con.execute(f"""
            SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = '{clean_ticker}'
        """).fetchone()
        
        last_date = res[0]
        if last_date:
            return pd.to_datetime(last_date).date()
        else:
            return HISTORICAL_START_DATE
            
    except Exception as e:
        log.error(f"Date Check Error ({ticker}): {e}")
        return HISTORICAL_START_DATE

def fetch_yahoo_data(y_ticker, start_date):
    end_date = datetime.now().date() + timedelta(days=1)
    
    if start_date >= datetime.now().date():
        log.info(f"   ⏳ {y_ticker} is up to date.")
        return pd.DataFrame()

    log.info(f"   ⬇️ Fetching {y_ticker} from {start_date} to {end_date}...")
    
    try:
        df = yf.download(y_ticker, start=start_date, end=end_date, interval="1m", progress=False)
        
        if df.empty: return pd.DataFrame()

        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.rename(columns={
            "Datetime": "datetime_utc", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume"
        }, inplace=True)
        
        df['ticker'] = y_ticker.replace('^', '')
        
        if pd.api.types.is_datetime64_any_dtype(df['datetime_utc']):
            if df['datetime_utc'].dt.tz is not None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC').dt.tz_localize(None)

        # CRITICAL FIX: Match the exact schema order of the existing table
        # Structure: [datetime_utc, open, high, low, close, volume, ticker]
        return df[['datetime_utc', 'open', 'high', 'low', 'close', 'volume', 'ticker']]

    except Exception as e:
        log.error(f"   ❌ Yahoo Fetch Error {y_ticker}: {e}")
        return pd.DataFrame()

def run_ingest():
    log.info("📊 STARTING INDEX HARVEST (Source: Yahoo Finance)")
    
    if not config.DB_FILE.exists():
        log.error("❌ No Database found.")
        return 

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Create table with correct schema (if it doesn't exist)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (
            datetime_utc TIMESTAMP,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            ticker VARCHAR,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)
    
    total_new_rows = 0
    
    for friendly, y_ticker in TARGETS.items():
        start_dt = get_start_date(con, y_ticker)
        df = fetch_yahoo_data(y_ticker, start_dt)
        
        if not df.empty:
            count = len(df)
            total_new_rows += count
            con.register('temp_idx', df)
            
            # CRITICAL FIX: Explicit Column Mapping
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_INDICES} 
                (datetime_utc, open, high, low, close, volume, ticker)
                SELECT datetime_utc, open, high, low, close, volume, ticker 
                FROM temp_idx
            """)
            con.unregister('temp_idx')
            log.info(f"   ✅ {friendly}: Saved {count} new candles.")
            
    con.close()
    log.info(f"🏁 Index Harvest Complete. Total New Rows: {total_new_rows}")

if __name__ == "__main__":
    run_ingest()