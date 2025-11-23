import yfinance as yf
import pandas as pd
import duckdb
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("IngestIndices")

# Standard Schema Map
SCHEMA_MAP = {
    "Date": "datetime_utc", "Datetime": "datetime_utc",
    "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
}

def fetch_and_clean(ticker_symbol, db_ticker, interval="5m"):
    """
    Fetches data, normalizes to UTC, and prepares for DB.
    """
    log.info(f"⬇️ Fetching {ticker_symbol} ({interval})...")
    try:
        # Period depends on interval
        period = "60d" if interval == "5m" else "5y" # Get 5 years of IRX history
        
        df = yf.download(ticker_symbol, period=period, interval=interval, progress=False)
        if df.empty:
            log.error(f"❌ No data for {ticker_symbol}")
            return None
            
        df.reset_index(inplace=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.rename(columns=SCHEMA_MAP, inplace=True)
        
        # --- TIMEZONE LAW ---
        # If it's intraday (has time), convert to UTC.
        # If it's daily (IRX), keep as Date.
        if interval == "5m":
            if df['datetime_utc'].dt.tz is None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_localize(config.TZ_NY)
            df['datetime_utc'] = df['datetime_utc'].dt.tz_convert(config.TZ_UTC)
            df['ticker'] = db_ticker
            # Return strictly ordered columns
            return df[['datetime_utc', 'ticker', 'open', 'high', 'low', 'close', 'volume']]
        else:
            # For IRX (Daily)
            df['date'] = df['datetime_utc'].dt.date
            df['rate'] = df['close']
            return df[['date', 'rate']]
        
    except Exception as e:
        log.error(f"❌ Error {ticker_symbol}: {e}")
        return None

def ingest_indices():
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. INTRADAY TARGETS (5m)
    intraday_targets = [
        ("^GSPC", "SPX", config.TBL_INDICES),
        ("^VIX", "VIX", config.TBL_INDICES),
        ("ES=F", "ES", config.TBL_FUTURES) # <-- Futures Added
    ]
    
    for yf_sym, db_sym, tbl in intraday_targets:
        df = fetch_and_clean(yf_sym, db_sym, interval="5m")
        if df is not None:
            log.info(f"   💾 Inserting {db_sym} into {tbl}...")
            try:
                con.register('df_temp', df)
                con.execute(f"""
                INSERT INTO {tbl} SELECT * FROM df_temp
                ON CONFLICT (datetime_utc, ticker) DO UPDATE SET
                    close = EXCLUDED.close, volume = EXCLUDED.volume
                """)
                log.info(f"   ✅ {db_sym} Inserted.")
            except Exception as e:
                log.error(f"   ❌ Insert Error: {e}")

    # 2. DAILY TARGETS (IRX)
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