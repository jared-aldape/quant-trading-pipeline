import duckdb
import pandas as pd
import yfinance as yf
import sys
from pathlib import Path
from datetime import datetime

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("Ingestion")

# Ticker Mapping (YFinance symbols can differ)
TICKERS = {
    'SPX': '^GSPC',  # S&P 500
    'VIX': '^VIX'    # CBOE Volatility Index
}

def fetch_data(symbol, friendly_name):
    """
    Fetches max history from Yahoo Finance with 1-minute granularity 
    (or best available for long durations).
    """
    log.info(f"⬇️ Downloading {friendly_name} ({symbol})...")
    
    try:
        # 1. Fetch Data (Max history, 1d interval is safest for long backtests)
        # Note: 1m data is limited to 7 days by Yahoo. 
        # For scanner operations, we might need granular data, but for deep history, 1h or 1d is standard.
        # We will fetch '1h' to support the fractal macro view.
        ticker = yf.Ticker(symbol)
        
        # '730d' is approx 2 years, the max for hourly data on YF free tier
        df = ticker.history(period="730d", interval="1h")
        
        if df.empty:
            log.warning(f"⚠️ No data found for {friendly_name}")
            return None
            
        # 2. Format Data
        df.reset_index(inplace=True)
        
        # Standardize Columns
        # YF returns: Date/Datetime, Open, High, Low, Close, Volume...
        # We need: datetime_utc, open, high, low, close, volume, ticker
        
        # Rename index col (usually 'Datetime' or 'Date') to 'datetime_utc'
        if 'Datetime' in df.columns:
            df.rename(columns={'Datetime': 'datetime_utc'}, inplace=True)
        elif 'Date' in df.columns:
            df.rename(columns={'Date': 'datetime_utc'}, inplace=True)
            
        # Ensure UTC and remove timezone offset for SQLite/DuckDB compatibility
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc']).dt.tz_convert(None)
        
        # Add Ticker Column
        df['ticker'] = friendly_name
        
        # Clean Columns (Keep only what we need)
        cols_to_keep = ['datetime_utc', 'Open', 'High', 'Low', 'Close', 'Volume', 'ticker']
        # Map to lowercase
        df = df[[c for c in cols_to_keep if c in df.columns]]
        df.columns = [c.lower() for c in df.columns]
        
        return df
        
    except Exception as e:
        log.error(f"❌ Failed to fetch {friendly_name}: {e}")
        return None

def ingest_market_data():
    log.info("📡 INGESTION ENGINE STARTED")
    
    if not config.DATA_DIR.exists():
        config.DATA_DIR.mkdir(parents=True)

    con = duckdb.connect(str(config.DB_FILE))
    
    # Create Table if not exists (Schema Definition)
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
    
    for friendly_name, yf_symbol in TICKERS.items():
        df = fetch_data(yf_symbol, friendly_name)
        
        if df is not None:
            log.info(f"💾 Saving {len(df)} rows for {friendly_name}...")
            
            # Upsert Logic: Insert, but on conflict do nothing (or replace)
            # Since we did a wipe, simple INSERT is fine, but INSERT OR IGNORE is safer
            con.register('temp_df', df)
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_INDICES} 
                SELECT * FROM temp_df
            """)
            con.unregister('temp_df')

    # Verification
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_INDICES}").fetchone()[0]
        log.info(f"✅ INGESTION COMPLETE. Total Rows in DB: {count}")
    except Exception as e:
        log.error(f"❌ Verification failed: {e}")
    
    con.close()

if __name__ == "__main__":
    ingest_market_data()