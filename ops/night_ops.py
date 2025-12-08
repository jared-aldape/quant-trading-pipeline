import sys
import time
import duckdb
import pandas as pd
import requests
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
import src.data.ingest_indices as ingest_indices
import src.core.engine_scanner as engine_scanner  # <--- USES YOUR UPLOADED LOGIC
import src.data.ingest_options as ingest_options

# ==============================================================================
# 2. NIGHT OPS LOGGER (The Heartbeat)
# ==============================================================================
# This setup ensures logs go to BOTH the console (screen) and a file (disk).
log = logging.getLogger("NightOps")
log.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Console Handler (Visual Confirmation)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)
log.addHandler(ch)

# File Handler (Permanent Record for AWS)
log_file = config.LOGS_DIR / "night_ops.log"
fh = logging.FileHandler(log_file, mode='a', encoding='utf-8')
fh.setFormatter(formatter)
log.addHandler(fh)

# ==============================================================================
# 3. MISSION PARAMETERS
# ==============================================================================
BACKFILL_DAYS = 365       # 1 Year Lookback
THROTTLE_SPEED = 20.0     # ⚠️ SET TO 0.5 IF PAYING POLYGON. KEEP 20.0 IF FREE TIER.

def system_check():
    log.info("==========================================")
    log.info("      🌙 NIGHT OPS: DEEP BACKFILL        ")
    log.info("==========================================")
    log.info(f"Target History: {BACKFILL_DAYS} Days")
    log.info(f"Throttle Speed: {THROTTLE_SPEED}s")
    log.info(f"Log File Path : {log_file}")
    
    if not config.DB_FILE.parent.exists():
        log.error(f"❌ DATA DIR MISSING: {config.DATA_DIR}")
        sys.exit(1)
    
    log.info("✅ System Check Passed. Engaging...")

# ==============================================================================
# PHASE 1: FOUNDATION (Indices)
# ==============================================================================
def step_1_indices():
    log.info("\n[PHASE 1/3] BACKFILLING INDICES (SPX, VIX)...")
    try:
        end_date = datetime.now().date()
        dates = [end_date - timedelta(days=x) for x in range(BACKFILL_DAYS)]
        
        con = duckdb.connect(str(config.DB_FILE))
        
        # Smart Resume: Check what days we already have
        existing = con.execute(f"SELECT DISTINCT CAST(datetime_utc AS DATE) FROM {config.TBL_INDICES}").df()
        existing_set = set(existing.iloc[:,0].astype(str)) if not existing.empty else set()
        
        needed = [d for d in dates if str(d) not in existing_set]
        log.info(f"📊 Indices Gap: Found {len(existing_set)} days. Downloading {len(needed)} missing days.")
        
        for i, d in enumerate(needed):
            d_str = d.strftime('%Y-%m-%d')
            log.info(f"   ⬇️ Fetching {d_str} ({i+1}/{len(needed)})...")
            
            # SPX (via SPY Proxy)
            df_spx = ingest_indices.fetch_polygon_day("SPY", d_str)
            if df_spx is not None: ingest_indices.save_indices(con, df_spx, "SPX")
            
            # VIX (via VXX Proxy)
            df_vix = ingest_indices.fetch_polygon_day("VXX", d_str)
            if df_vix is not None: ingest_indices.save_indices(con, df_vix, "VIX")
            
            time.sleep(15) # Safety buffer for index requests
            
        con.close()
        log.info("✅ PHASE 1 COMPLETE.")
    except Exception as e:
        log.error(f"❌ PHASE 1 CRITICAL FAILURE: {e}")
        sys.exit(1)

# ==============================================================================
# PHASE 2: INTELLIGENCE (Scanner)
# ==============================================================================
def step_2_scanner():
    log.info("\n[PHASE 2/3] RUNNING SIGNAL SCANNER...")
    log.info("   (Using 'engine_scanner.py' & 'strat_fractal.py' logic)")
    try:
        # This calls your uploaded code directly
        engine_scanner.scan_and_generate_manifest()
        log.info("✅ PHASE 2 COMPLETE. Trade Manifest Updated.")
    except Exception as e:
        log.error(f"❌ PHASE 2 CRITICAL FAILURE: {e}")
        sys.exit(1)

# ==============================================================================
# PHASE 3: ACQUISITION (Options)
# ==============================================================================
def step_3_options():
    log.info("\n[PHASE 3/3] DOWNLOADING OPTION CONTRACTS...")
    
    # 1. Read the Manifest generated in Phase 2
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    manifest = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC").df()
    con.close()
    
    if manifest.empty:
        log.error("❌ MANIFEST EMPTY. Scanner found 0 signals.")
        sys.exit(1)

    # 2. Build the Download Queue
    queue = []
    for _, row in manifest.iterrows():
        entry_date = pd.to_datetime(row['date']).date()
        # Uses ingest_options logic to find the specific ATM contracts
        cluster = ingest_options.construct_ticker_cluster(entry_date, row['xsp_price'], row['trade_type'])
        for ticker in cluster:
            queue.append((ticker, entry_date))
    
    # 3. Filter out what we already have (Smart Resume)
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    existing_counts = con.execute(f"SELECT ticker, COUNT(*) as cnt FROM {config.TBL_OPTIONS} GROUP BY ticker").df()
    con.close()
    
    existing_map = dict(zip(existing_counts['ticker'], existing_counts['cnt']))
    
    final_queue = []
    for ticker, date_obj in queue:
        # If we have < 30 bars, assume it's corrupt/incomplete and re-download
        if existing_map.get(ticker, 0) < 30:
            final_queue.append((ticker, date_obj))
            
    total_tasks = len(final_queue)
    log.info(f"📋 Total Signals: {len(manifest)} | Total Contracts: {len(queue)}")
    log.info(f"📉 Already Archived: {len(queue) - total_tasks}")
    log.info(f"🚀 REMAINING DOWNLOADS: {total_tasks}")
    
    if total_tasks == 0:
        log.info("✅ All contracts are already archived.")
        return

    # 4. EXECUTE (The Long Haul)
    start_time = time.time()
    
    for i, (ticker, target_date) in enumerate(final_queue):
        date_str = target_date.strftime('%Y-%m-%d')
        
        # ETA Calculation
        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        remaining_sec = avg_time * (total_tasks - (i + 1))
        eta = str(timedelta(seconds=int(remaining_sec)))
        
        status_msg = "UNKNOWN"
        bars = 0
        
        try:
            # The Network Call
            df = ingest_options.fetch_polygon_aggs(ticker, date_str)
            
            if not df.empty:
                bars = len(df)
                # Parse Metadata
                exp, typ, strk = ingest_options.parse_ticker_metadata(ticker)
                df['expiration'] = exp
                df['type'] = typ
                df['strike'] = strk
                
                # Commit to Vault
                with duckdb.connect(str(config.DB_FILE)) as con_write:
                    con_write.register('df_opt', df)
                    con_write.execute(f"""
                        INSERT OR IGNORE INTO {config.TBL_OPTIONS} 
                        (datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume)
                        SELECT datetime_utc, ticker, expiration, strike, type, open, high, low, close, volume
                        FROM df_opt
                    """)
                status_msg = "✅ OK"
            else:
                status_msg = "⚠️ EMPTY"
                
        except Exception as e:
            status_msg = f"❌ ERR: {str(e)}"

        # THE HEARTBEAT LOG (Per Transaction)
        log.info(f"[{i+1}/{total_tasks}] {ticker} | {status_msg} ({bars} bars) | ETA: {eta}")
        
        # Throttle
        time.sleep(THROTTLE_SPEED)

if __name__ == "__main__":
    system_check()
    step_1_indices()  # Get the raw data
    step_2_scanner()  # Find the trade signals
    step_3_options()  # Get the contract data
    log.info("\n🎉 NIGHT OPS COMPLETE. Vault Secure.")