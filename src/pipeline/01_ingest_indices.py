import sys
import os
import yfinance as yf
import pandas as pd
import duckdb
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/pipeline/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IngestIndices")

# Standard Schema Map
SCHEMA_MAP = {
    "Date": "datetime_utc", 
    "Datetime": "datetime_utc",
    "Open": "open", 
    "High": "high", 
    "Low": "low", 
    "Close": "close", 
    "Volume": "volume"
}

def fetch_and_clean(ticker_symbol, db_ticker, interval="5m"):
    """
    Fetches data, strictly enforces Timezone Law (UTC), and prepares for DB.
    """
    log.info(f"⬇️ Fetching {ticker_symbol} ({interval})...")
    try:
        # Period depends on interval (60d is max for 5m in yfinance)
        period = "60d" if interval == "5m" else "5y"
        
        # Download data
        df = yf.download(ticker_symbol, period=period, interval=interval, progress=False)
        if df.empty:
            log.error(f"❌ No data for {ticker_symbol}")
            return None
        
        # 1. Handle MultiIndex Columns (common with newer yfinance versions)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ==============================================================================
        # 2. TIMEZONE ENFORCEMENT (THE TIMEZONE LAW)
        # Operation: Localize Naive (NY) -> Convert to UTC
        # ==============================================================================
        if interval == "5m":
            if df.index.tz is None:
                df.index = df.index.tz_localize(config.TZ_NY)
            
            # Now convert to the Vault Standard: UTC
            df.index = df.index.tz_convert(config.TZ_UTC)

        # 3. Reset Index to move the Timestamp into a column
        df.reset_index(inplace=True)
        
        # 4. Standardize Column Names
        df.rename(columns=SCHEMA_MAP, inplace=True)
        
        # 5. Final Schema Selection
        if interval == "5m":
            df['ticker'] = db_ticker
            return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
        else:
            # For IRX (Daily Data)
            df['date'] = df['datetime_utc'].dt.date
            df['rate'] = df['close']
            return df[['date', 'rate']]
        
    except Exception as e:
        log.error(f"❌ Error processing {ticker_symbol}: {e}")
        return None

def ingest_indices():
    """
    Main execution loop for populating indices_1m and risk_free_rate_daily.
    """
    log.info(f"Connecting to Golden Source: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. INTRADAY TARGETS (5m) -> indices_1m
    intraday_targets = [
        ("^GSPC", "SPX", config.TBL_INDICES),
        ("^VIX", "VIX", config.TBL_INDICES),
        ("ES=F", "ES", config.TBL_FUTURES) 
    ]
    
    for yf_sym, db_sym, tbl in intraday_targets:
        df = fetch_and_clean(yf_sym, db_sym, interval="5m")
        if df is not None:
            log.info(f"   💾 Inserting {db_sym} into {tbl} (Rows: {len(df)})...")
            try:
                con.register('df_temp', df)
                con.execute(f"""
                INSERT INTO {tbl} SELECT * FROM df_temp
                ON CONFLICT (datetime_utc, ticker) DO UPDATE SET
                    close = EXCLUDED.close, 
                    volume = EXCLUDED.volume,
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low
                """)
                log.info(f"   ✅ {db_sym} Inserted Successfully.")
            except Exception as e:
                log.error(f"   ❌ Insert Error for {db_sym}: {e}")

    # 2. DAILY TARGETS (IRX) -> risk_free_rate_daily
    log.info("⬇️ Fetching Risk Free Rate (^IRX)...")
    irx_df = fetch_and_clean("^IRX", "IRX", interval="1d")
    if irx_df is not None:
        try:
            con.register('df_irx', irx_df)
            con.execute(f"""
            INSERT INTO {config.TBL_IRX} SELECT * FROM df_irx
            ON CONFLICT (date) DO UPDATE SET rate = EXCLUDED.rate
            """)
            log.info(f"   ✅ IRX Inserted ({len(irx_df)} days).")
        except Exception as e:
            log.error(f"   ❌ IRX Insert Error: {e}")

    con.close()
    log.info("🏁 Ingestion Complete.")

if __name__ == "__main__":
    ingest_indices()