import sys
import duckdb
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE SETUP
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
    log = get_logger("Hybrid_Ingest_v3")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("Hybrid_Ingest_v3")
    class MockConfig:
        DB_FILE = "quant_strategy.duckdb"
        TBL_INDICES = "indices_1m"
    config = MockConfig()

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
FILENAME = "vix-1yr.csv"
SYSTEM_TICKER = "VIX"
YAHOO_TICKER = "^VIX"

def find_file(filename):
    """Tactical Search: Checks Root and Ops folders."""
    locations = [
        ROOT_DIR / filename,
        CURRENT_DIR / filename,
        Path(filename)
    ]
    for path in locations:
        if path.exists(): return path
    return None

def clean_and_store(df, source_label):
    if df.empty:
        log.warning(f"⚠️ {source_label} DataFrame is empty.")
        return

    # 1. Normalize Columns
    df.columns = [c.lower() for c in df.columns]
    
    col_map = {
        'date': 'datetime_utc', 'datetime': 'datetime_utc',
        'adj close': 'close', 
    }
    df.rename(columns=col_map, inplace=True)

    # 2. Enforce Timezone Law
    if pd.api.types.is_object_dtype(df['datetime_utc']):
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
    
    if df['datetime_utc'].dt.tz is not None:
        df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC').dt.tz_localize(None)

    # 3. Add Ticker Identity
    df['ticker'] = SYSTEM_TICKER

    # 4. Volume Fix (Robust)
    if 'volume' not in df.columns: 
        df['volume'] = 0.0
    else:
        # Force numeric, turning '-' into NaN, then filling with 0
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)

    # 5. Filter for Truth
    final_df = df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']].copy()
    final_df.dropna(subset=['close'], inplace=True)

    # 6. Commit (Explicit Column Mapping)
    try:
        con = duckdb.connect(str(config.DB_FILE))
        min_date = final_df['datetime_utc'].min()
        max_date = final_df['datetime_utc'].max()
        
        log.info(f"🔌 Writing {source_label}: {min_date} -> {max_date} ({len(final_df)} rows)")
        
        con.execute("BEGIN TRANSACTION")
        
        # Surgical Delete
        con.execute(f"""
            DELETE FROM {config.TBL_INDICES}
            WHERE ticker = '{SYSTEM_TICKER}'
            AND datetime_utc >= '{min_date}'
            AND datetime_utc <= '{max_date}'
        """)
        
        # Explicit Insert (The Fix)
        con.register('df_stage', final_df)
        con.execute(f"""
            INSERT INTO {config.TBL_INDICES} 
            (datetime_utc, ticker, open, high, low, close, volume)
            SELECT datetime_utc, ticker, open, high, low, close, volume 
            FROM df_stage
        """)
        
        con.execute("COMMIT")
        con.close()
        log.info(f"✅ {source_label} Commit Complete.")
        
    except Exception as e:
        log.critical(f"❌ {source_label} DB Error: {e}")

def run_hybrid_pipeline():
    print(f"\n⚔️  QUANT OS v3.3: HYBRID INGEST PROTOCOL (Final Patch)")
    print("==========================================================")

    # LAYER 1: CSV
    log.info("--- [1/2] Ingesting CSV (Macro Foundation) ---")
    csv_path = find_file(FILENAME)
    if csv_path:
        try:
            df_csv = pd.read_csv(csv_path)
            clean_and_store(df_csv, "CSV_LAYER")
        except Exception as e:
            log.error(f"❌ CSV Error: {e}")
    else:
        log.error("❌ CSV Not Found.")

    # LAYER 2: YAHOO
    log.info("--- [2/2] Ingesting Yahoo (Fractal Precision) ---")
    try:
        df_yahoo = yf.download(
            tickers=YAHOO_TICKER, 
            period="59d", 
            interval="5m", 
            progress=False,
            auto_adjust=False, 
            multi_level_index=False
        )
        df_yahoo.reset_index(inplace=True)
        clean_and_store(df_yahoo, "YAHOO_LAYER")
    except Exception as e:
        log.error(f"❌ Yahoo Error: {e}")

    print("\n✅ SYSTEM READY.")

if __name__ == "__main__":
    run_hybrid_pipeline()