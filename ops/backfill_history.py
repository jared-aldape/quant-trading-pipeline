import sys
import time
import duckdb
import pandas as pd
import gc
from datetime import datetime, timedelta
from pathlib import Path

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
# 2. CONFIGURATION (AWS SAFE MODE)
# ==============================================================================
BACKFILL_DAYS = 365
THROTTLE_DELAY = 13  # 13s = ~4.6 requests/min (Safe)

def run_backfill():
    log.info(f"🕰️ STARTING DEEP HISTORY BACKFILL ({BACKFILL_DAYS} Days)")
    log.info(f"💾 RAM Protection: ON (Aggressive GC & Conn Recycling)")
    
    end_date = datetime.now().date() - timedelta(days=1)
    dates = [end_date - timedelta(days=x) for x in range(BACKFILL_DAYS)]
    
    # Only Polygon-capable tickers
    targets = [t for t in ingest_indices.TICKER_MAP if t['poly'] != "---"]
    
    total_ops = len(dates) * len(targets)
    current_op = 0
    
    for d in dates:
        date_str = d.strftime('%Y-%m-%d')
        
        for target in targets:
            current_op += 1
            ticker_db = target['db']
            ticker_poly = target['poly']
            
            # 1. CHECK EXISTENCE (Open/Close Conn immediately to save RAM)
            exists = False
            try:
                con = duckdb.connect(str(config.DB_FILE), read_only=True)
                table = config.TBL_IRX if ticker_db == "IRX" else config.TBL_INDICES
                if ticker_db == "IRX":
                    query = f"SELECT 1 FROM {table} WHERE date = '{date_str}' LIMIT 1"
                else:
                    query = f"SELECT 1 FROM {table} WHERE ticker = '{ticker_db}' AND CAST(datetime_utc AS DATE) = '{date_str}' LIMIT 1"
                
                if con.execute(query).fetchone():
                    exists = True
                con.close()
            except Exception: pass

            if exists:
                print(f"[{current_op}/{total_ops}] ✅ Skipping {ticker_db} {date_str}", end='\r')
                continue

            # 2. FETCH DATA
            print(f"[{current_op}/{total_ops}] ⬇️ Fetching {ticker_db} {date_str}...", end='\r')
            
            try:
                df = ingest_indices.fetch_polygon_day(ticker_poly, date_str)
                
                if df is not None and not df.empty:
                    # 3. WRITE TO DB (Fresh Connection)
                    con_write = duckdb.connect(str(config.DB_FILE))
                    
                    if target['type'] == 'RATE':
                        ingest_indices.save_rates(con_write, df, ticker_db)
                    else:
                        ingest_indices.save_indices(con_write, df, ticker_db)
                    
                    con_write.close()
                    log.info(f"💾 Saved {ticker_db} for {date_str} ({len(df)} bars)")
                    
                    # 4. MEMORY FLUSH (Crucial for AWS)
                    del df
                    gc.collect()
                
            except Exception as e:
                log.error(f"❌ Error on {date_str}: {e}")

            # 5. THROTTLE
            time.sleep(THROTTLE_DELAY)

    log.info("\n🏁 INDEX BACKFILL COMPLETE.")
    log.info("📢 NEXT STEPS:")
    log.info("1. Run 'python src/core/engine_scanner.py' (Generates Signals)")
    log.info("2. Run 'python src/data/ingest_options.py' (Fetches Options)")

if __name__ == "__main__":
    run_backfill()