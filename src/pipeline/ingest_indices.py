import sys
import duckdb
import yfinance as yf
import pandas as pd
from pathlib import Path
import pytz

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
    
    # Create Table
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
    MACHINE_TZ = 'America/Los_Angeles'

    for sym in tickers:
        try:
            # 1. FETCH
            df = yf.download(sym, period="60d", interval="5m", progress=False, auto_adjust=True)
            if df.empty:
                log.warning(f"⚠️ No data found for {sym}")
                continue
                
            # 2. CLEAN
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            df.rename(columns={'datetime': 'datetime_utc', 'date': 'datetime_utc'}, inplace=True)
            df['ticker'] = friendly_names[sym]
            
            # 3. TIMEZONE STANDARDIZATION (The "Naive UTC" Fix)
            
            # A. Ensure we are physically at UTC first
            if df['datetime_utc'].dt.tz is None:
                # If naive input, assume PST -> convert to UTC
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(MACHINE_TZ).dt.tz_convert(config.TZ_UTC)
            else:
                # If aware input, just convert to UTC
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            
            # B. CRITICAL: Strip Timezone Info (Make Naive)
            # This prevents DuckDB from converting back to Local Time during insertion.
            # 14:30+00:00 -> 14:30 (Naive)
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)
            
            # 4. STORE
            con.execute(f"""
                INSERT OR IGNORE INTO {config.TBL_INDICES} 
                SELECT datetime_utc, ticker, open, high, low, close, volume 
                FROM df
            """)
            
            log.info(f"✅ Synced {friendly_names[sym]}: {len(df)} rows.")
            
        except Exception as e:
            log.error(f"Failed to ingest {sym}: {e}")

    # Validation
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_INDICES}").fetchone()[0]
        log.info(f"📊 Total Index Rows in Vault: {count}")
    except: pass

    con.close()

if __name__ == "__main__":
    run_pipeline()