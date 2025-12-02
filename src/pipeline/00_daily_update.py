import sys
import time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger
# UPDATED: Use the Hybrid Module
import src.pipeline.ingest_hybrid_indices as ingest_indices 
import src.pipeline.scan_signals as scan_signals
import src.pipeline.fetch_options as fetch_options

log = get_logger("DailyUpdate")

def run_daily_update():
    start_time = time.time()
    log.info("🌅 STARTING QUANT OS v2.4 PIPELINE (Hybrid)")
    
    # ---------------------------------------------------------
    # STEP 1: INGEST MARKET INDICES (Polygon > Yahoo Fallback)
    # ---------------------------------------------------------
    try:
        log.info("--- [1/3] Updating Indices (Hybrid Mode) ---")
        ingest_indices.run_pipeline()
    except Exception as e:
        log.error(f"❌ Step 1 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 2: SCAN FOR FRACTAL SIGNALS
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

    elapsed = time.time() - start_time
    log.info(f"✅ DAILY UPDATE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_daily_update()