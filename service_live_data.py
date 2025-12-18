import time
import sys
from datetime import datetime
from pathlib import Path

# SETUP
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# IMPORT ENGINES
import src.data.ingest_catalyst as ingest_catalyst
import src.data.ingest_indices as ingest_indices
import src.core.engine_scanner as engine_scanner
import src.core.engine_macro_scanner as engine_macro_scanner

# Import market status logic from your dashboard script
from src.interface.view_live_scope import get_market_status

log = get_logger("LiveService")

def run_live_cycle():
    """Executes the high-frequency parts of the pipeline."""
    log.info("🔔 STARTING LIVE UPDATE CYCLE...")
    
    # STEP 0: MACRO INTELLIGENCE (3 API CALLS)
    try:
        ingest_catalyst.update_intelligence()
    except Exception as e: log.error(f"❌ Catalyst Failed: {e}")

    # STEP 1: INDEX REFRESH (XSP/VIX)
    try:
        ingest_indices.run_ingest()
    except Exception as e: log.error(f"❌ Index Ingest Failed: {e}")

    # STEP 3: SCAN FOR FRACTALS & REGIME
    try:
        engine_scanner.run_scanner()
        engine_macro_scanner.run_macro_scan()
    except Exception as e: log.error(f"❌ Scanner Failed: {e}")

    log.info("✅ CYCLE COMPLETE. Waiting 60s...")

def main():
    log.info("🚀 QUANT-OS LIVE DATA SERVICE INITIALIZED")
    
    while True:
        # Check if Market is Open (PST/EST Awareness)
        _, _, is_open = get_market_status()
        
        if is_open:
            start_time = time.time()
            run_live_cycle()
            
            # Ensure we don't loop faster than once a minute
            elapsed = time.time() - start_time
            sleep_time = max(60 - elapsed, 10)
            time.sleep(sleep_time)
        else:
            # Market Closed: Check every 5 minutes
            log.info("💤 Market Closed. Sleeping for 5 minutes...")
            time.sleep(300)

if __name__ == "__main__":
    main()