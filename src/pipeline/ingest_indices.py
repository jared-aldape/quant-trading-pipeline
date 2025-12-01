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
    log.info("📥 Fetching Market Indices & Futures...")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. SETUP TABLES
    # Indices Table
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (
            datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, 
            low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)
    
    # Futures Table (NEW)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_FUTURES} (
            datetime_utc TIMESTAMP, ticker VARCHAR, open DOUBLE, high DOUBLE, 
            low DOUBLE, close DOUBLE, volume DOUBLE,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)

    # 2. DEFINITIONS
    targets = [
        {"y_sym": "^GSPC", "db_sym": "SPX", "table": config.TBL_INDICES},
        {"y_sym": "^VIX",  "db_sym": "VIX", "table": config.TBL_INDICES},
        {"y_sym": "ES=F",  "db_sym": "ES",  "table": config.TBL_FUTURES} # Added Futures
    ]
    
    # We use machine local time for the "Handshake" to ensure YFinance relative time is anchored correctly
    MACHINE_TZ = 'America/Los_Angeles' 

    for target in targets:
        sym = target['y_sym']
        try:
            # A. FETCH (Respecting Rate-Limit Law via occasional sleeps if needed in bulk)
            df = yf.download(sym, period="5d", interval="5m", progress=False, auto_adjust=True)
            
            if df.empty:
                log.warning(f"⚠️ No data found for {sym}")
                continue
                
            # B. CLEAN
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            df.rename(columns={'datetime': 'datetime_utc', 'date': 'datetime_utc'}, inplace=True)
            df['ticker'] = target['db_sym']
            
            # C. TIMEZONE STANDARDIZATION (The "Naive UTC" Fix)
            # 1. Localize Naive input to Machine Time -> Convert to UTC
            if df['datetime_utc'].dt.tz is None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(MACHINE_TZ).dt.tz_convert(config.TZ_UTC)
            else:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            
            # 2. STRIP Timezone (Strict Enforcement for DuckDB Storage)
            df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(None)
            
            # D. STORE
            table_name = target['table']
            con.execute(f"""
                INSERT OR IGNORE INTO {table_name} 
                SELECT datetime_utc, ticker, open, high, low, close, volume 
                FROM df
            """)
            
            log.info(f"✅ Synced {target['db_sym']} -> {table_name}: {len(df)} rows.")
            
        except Exception as e:
            log.error(f"Failed to ingest {sym}: {e}")

    con.close()