import sys
import duckdb
import yfinance as yf
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("VaultPrimer")

# ==============================================================================
# 2. SYNTHETIC DATA GENERATOR (The Hologram)
# ==============================================================================
def generate_ghost_data(ticker, days=5):
    """Generates realistic synthetic data if live feeds fail."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    freq = '1min'
    
    dates = pd.date_range(start=start_date, end=end_date, freq=freq)
    n = len(dates)
    
    if ticker == 'XSP':
        # Sine wave with trend and noise
        base_price = 580.0
        trend = np.linspace(0, 10, n)
        cycle = 5 * np.sin(np.linspace(0, 20, n))
        noise = np.random.normal(0, 0.5, n)
        prices = base_price + trend + cycle + noise
    else: # VIX
        # Mean reverting noise
        base_price = 15.0
        noise = np.random.normal(0, 0.2, n)
        prices = np.clip(base_price + np.cumsum(noise), 10, 40)

    df = pd.DataFrame({
        'datetime_utc': dates,
        'open': prices,
        'high': prices + 0.1,
        'low': prices - 0.1,
        'close': prices,
        'volume': np.random.randint(100, 1000, n),
        'ticker': ticker
    })
    return df

# ==============================================================================
# 3. CORE LOGIC
# ==============================================================================
def prime_vault():
    log.info("⚡ INITIATING VAULT PRIMING SEQUENCE...")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Ensure Schema
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {config.TBL_INDICES} (
            datetime_utc TIMESTAMP,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            ticker VARCHAR,
            PRIMARY KEY (datetime_utc, ticker)
        )
    """)
    
    targets = [('VIX', '^VIX'), ('XSP', '^XSP')]
    snapshot_data = {'updated': datetime.now().isoformat()}

    for symbol, yahoo_ticker in targets:
        log.info(f"Targeting {symbol}...")
        
        # A. TRY LIVE FEED (SAFE MODE: 5 DAYS)
        try:
            df = yf.Ticker(yahoo_ticker).history(period="5d", interval="1m")
            
            if df.empty:
                raise ValueError("Yahoo returned empty dataframe")
                
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df.rename(columns={'datetime': 'datetime_utc'}, inplace=True)
            df['ticker'] = symbol
            
            # UTC Normalization
            if df['datetime_utc'].dt.tz is not None:
                df['datetime_utc'] = df['datetime_utc'].dt.tz_convert('UTC').dt.tz_localize(None)
            else:
                 df['datetime_utc'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_localize(None)
                 
            log.info(f"✅ ACQUIRED LIVE DATA: {len(df)} rows")

        except Exception as e:
            # B. FALLBACK TO HOLOGRAM
            log.warning(f"⚠️ LIVE FEED FAILED ({e}). ENGAGING HOLOGRAPHIC GENERATOR.")
            df = generate_ghost_data(symbol)
            log.info(f"👻 HOLOGRAPHIC DATA GENERATED: {len(df)} rows")

        # C. INJECT INTO VAULT
        try:
            # Database Insert
            con.execute(f"DELETE FROM {config.TBL_INDICES} WHERE ticker='{symbol}'") 
            con.execute(f"INSERT INTO {config.TBL_INDICES} SELECT datetime_utc, open, high, low, close, volume, ticker FROM df")
            
            # Prepare Snapshot Data (JSON SERIALIZATION FIX)
            # Create a copy and convert Timestamps to Strings
            snap_df = df.tail(390).copy()
            snap_df['datetime_utc'] = snap_df['datetime_utc'].apply(lambda x: x.isoformat() if pd.notnull(x) else str(x))
            
            snapshot_data[symbol.lower()] = snap_df.to_dict('records')
            
        except Exception as db_e:
            log.error(f"❌ DATABASE ERROR: {db_e}")

    con.close()
    
    # 2. GENERATE SNAPSHOT (For ATB Scope)
    snap_path = config.DATA_DIR / "live_snapshot.json"
    try:
        with open(snap_path, 'w') as f:
            json.dump(snapshot_data, f)
        log.info(f"📸 SNAPSHOT SAVED: {snap_path}")
        log.info("✅ VAULT PRIMED. SYSTEM READY.")
    except Exception as e:
        log.error(f"❌ JSON DUMP FAILED: {e}")

if __name__ == "__main__":
    prime_vault()