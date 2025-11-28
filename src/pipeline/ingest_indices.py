import sys
import duckdb
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IngestIndices")

# ==============================================================================
# 2. CORE LOGIC
# ==============================================================================
def run_pipeline():
    log.info("📥 Fetching Market Indices (SPX, VIX)...")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # Create Table if needed
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

    tickers = ["^GSPC", "^VIX"]
    friendly_names = {"^GSPC": "SPX", "^VIX": "VIX"}
    
    for sym in tickers:
        try:
            # Download 60 days of 5m data (Max allowable by Yahoo)
            df = yf.download(sym, period="60d", interval="5m", progress=False)
            
            if df.empty:
                log.warning(f"⚠️ No data found for {sym}")
                continue
                
            # Flatten Yahoo's MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            # Normalize Headers
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            df.rename(columns={'datetime': 'datetime_utc'}, inplace=True)
            
            # Add Ticker Column (using friendly name e.g. SPX instead of ^GSPC)
            df['ticker'] = friendly_names[sym]
            
            # Timezone Standardization (UTC)
            # Yahoo 5m data is usually 'America/New_York'
            if df['datetime_utc'].dt.tz is None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_NY)
            else:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_NY)
            
            # Convert to UTC for storage
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            
            # Upsert into DuckDB (Insert or Ignore duplicates)
            # Since we defined a PRIMARY KEY, we can use ON CONFLICT DO NOTHING
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_INDICES} 
                SELECT datetime_utc, ticker, open, high, low, close, volume 
                FROM df
            """)
            
            log.info(f"✅ Synced {friendly_names[sym]}: {len(df)} rows.")
            
        except Exception as e:
            log.error(f"Failed to ingest {sym}: {e}")

    con.close()

if __name__ == "__main__":
    run_pipeline()