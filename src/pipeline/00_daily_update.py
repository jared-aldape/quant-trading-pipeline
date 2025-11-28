import sys
import time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger
import src.pipeline.ingest_indices as ingest_indices
import src.pipeline.scan_signals as scan_signals
import src.pipeline.fetch_options as fetch_options
# import src.pipeline.calc_greeks as calc_greeks # OPTIMIZATION: Skipped

log = get_logger("DailyUpdate")

def run_daily_update():
    start_time = time.time()
    log.info("🌅 STARTING DAILY QUANT PIPELINE")
    
    # ---------------------------------------------------------
    # STEP 1: INGEST MARKET INDICES (SPX, VIX) - Yahoo Finance
    # ---------------------------------------------------------
    try:
        log.info("--- [1/3] Updating Indices ---")
        ingest_indices.run_pipeline()
    except Exception as e:
        log.error(f"❌ Step 1 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 2: SCAN FOR SIGNALS (VIX RSI Logic)
    # ---------------------------------------------------------
    try:
        log.info("--- [2/3] Scanning Signals ---")
        scan_signals.scan_and_generate_manifest()
    except Exception as e:
        log.error(f"❌ Step 2 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 3: FETCH OPTION DATA (Polygon - Free Tier Safe)
    # ---------------------------------------------------------
    try:
        log.info("--- [3/3] Fetching Options ---")
        fetch_options.run_fetch_pipeline()
    except Exception as e:
        log.error(f"❌ Step 3 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 4: CALCULATE GREEKS (Skipped for Price-Action Strategy)
    # ---------------------------------------------------------
    # try:
    #     log.info("--- [4/4] Calculating Greeks ---")
    #     calc_greeks.calc_greeks_for_new_options()
    # except Exception as e:
    #     log.error(f"❌ Step 4 Failed: {e}")
    #     return

    elapsed = time.time() - start_time
    log.info(f"✅ DAILY UPDATE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_daily_update()