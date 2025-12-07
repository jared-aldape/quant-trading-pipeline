import sys
import time
import duckdb
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
import gc

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
import src.data.ingest_indices as ingest_indices

log = get_logger("HistoryBackfill")

# ==============================================================================
# 2. CONFIGURATION
# ==============================================================================
BACKFILL_DAYS = 365
THROTTLE_DELAY = 13  # 13s buffer for Polygon Basic

# PROXY MAP: Maps the Database Ticker -> The Available Polygon Ticker
# We use SPY instead of I:SPX because 'Stocks' data is usually available on Basic.
PROXY_MAP = {
    "SPX": "SPY",      # Proxy for S&P 500
    "VIX": "VXX",      # Proxy for Volatility (Pattern matching)
    "IRX": "^IRX"      # Use Yahoo for Rates (Daily)
}

def fetch_yahoo_daily(ticker, start_date):
    """Fetches daily data from Yahoo for Rates (Unlimited history)."""
    try:
        df = yf.download(ticker, start=start_date, interval="1d", progress=False)
        if df.empty: return None
        df = df.reset_index()
        df.columns = df.columns.str.lower()
        df.rename(columns={'date': 'datetime_utc', 'adj close': 'close'}, inplace=True)
        return df
    except: return None

def run_backfill():
    log.info(f"🕰️ STARTING PROXY BACKFILL ({BACKFILL_DAYS} Days)")
    log.info(f"⚡ Strategy: Using SPY/VXX Proxies to bypass Index Tier Limits")
    
    end_date = datetime.now().date() - timedelta(days=1)
    dates = [end_date - timedelta(days=x) for x in range(BACKFILL_DAYS)]
    
    # We only target the main indices, not futures yet
    targets = ["SPX", "VIX", "IRX"]
    
    total_ops = len(dates) * len(targets)
    current_op = 0
    
    for d in dates:
        date_str = d.strftime('%Y-%m-%d')
        
        for db_ticker in targets:
            current_op += 1
            proxy_ticker = PROXY_MAP.get(db_ticker, db_ticker)
            
            # --- SPECIAL CASE: IRX (Rates) ---
            # Rates don't need minute precision. We fetch entire history once via Yahoo.
            if db_ticker == "IRX":
                if current_op > 3: continue # Only run once
                print(f"[{current_op}/{total_ops}] ⬇️ Fetching Daily Rates ({proxy_ticker})...", end='\r')
                df = fetch_yahoo_daily(proxy_ticker, (end_date - timedelta(days=BACKFILL_DAYS)).strftime('%Y-%m-%d'))
                if df is not None:
                    con = duckdb.connect(str(config.DB_FILE))
                    ingest_indices.save_rates(con, df, db_ticker)
                    con.close()
                    log.info(f"💾 Saved IRX Rates (Yahoo Daily)")
                continue

            # --- STANDARD CASE: SPX/VIX (Minute Bars via Polygon Proxy) ---
            print(f"[{current_op}/{total_ops}] ⬇️ Fetching {db_ticker} (via {proxy_ticker}) {date_str}...", end='\r')
            
            try:
                # Fetch 1-minute bars for the PROXY (SPY/VXX)
                df = ingest_indices.fetch_polygon_day(proxy_ticker, date_str)
                
                if df is not None and not df.empty:
                    con_write = duckdb.connect(str(config.DB_FILE))
                    
                    # SCALE CORRECTION for SPX
                    # If using SPY, multiply by 10 to match SPX levels? 
                    # Actually, XSP trades at 1/10th SPX (approx SPY level).
                    # We will store RAW SPY price. The engine handles XSP scaling.
                    
                    ingest_indices.save_indices(con_write, df, db_ticker)
                    
                    con_write.close()
                    log.info(f"💾 Saved {db_ticker} (src: {proxy_ticker}) for {date_str} ({len(df)} bars)")
                    
                    del df
                    gc.collect()
                
            except Exception as e:
                log.error(f"❌ Error on {date_str}: {e}")

            # Strict Throttle for Polygon
            time.sleep(THROTTLE_DELAY)

    log.info("\n🏁 HISTORY BACKFILL COMPLETE.")

if __name__ == "__main__":
    run_backfill()