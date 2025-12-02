import sys
import time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# File: main_pipeline.py
# Location: Project Root (QUANT-OS/)
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

# v2.5 MODULE IMPORTS
# Since we are at root, we import directly from 'src'
import src.data.ingest_indices as ingest_indices
import src.core.engine_scanner as engine_scanner
import src.data.ingest_options as ingest_options
import src.core.engine_greeks as engine_greeks

log = get_logger("DailyPipeline")

def run_daily_update():
    start_time = time.time()
    log.info("🌅 STARTING QUANT OS v2.5 PIPELINE")
    
    # ---------------------------------------------------------
    # STEP 1: INGEST MARKET INDICES (The Truth)
    # ---------------------------------------------------------
    # Fetches SPX, VIX, IRX from Polygon (or Yahoo Fallback)
    try:
        log.info("--- [1/4] Ingesting Indices (Hybrid) ---")
        ingest_indices.run_pipeline()
    except Exception as e:
        log.error(f"❌ Step 1 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 2: SCAN FOR FRACTAL SIGNALS (The Strategy)
    # ---------------------------------------------------------
    # Rebuilds trade_manifest based on strat_fractal.py logic
    try:
        log.info("--- [2/4] Scanning Signals (Fractal Flow) ---")
        engine_scanner.scan_and_generate_manifest()
    except Exception as e:
        log.error(f"❌ Step 2 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 3: FETCH OPTION DATA (The Vehicle)
    # ---------------------------------------------------------
    # Downloads 1-minute aggregates for identified signal dates
    try:
        log.info("--- [3/4] Fetching Option Contracts ---")
        ingest_options.run_fetch_pipeline()
    except Exception as e:
        log.error(f"❌ Step 3 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 4: CALCULATE GREEKS (The Math)
    # ---------------------------------------------------------
    # Calculates IV, Delta, Gamma for the Analysis Dashboard
    try:
        log.info("--- [4/4] Calculating Greeks ---")
        engine_greeks.run_greek_calculation()
    except Exception as e:
        log.error(f"❌ Step 4 Failed: {e}")
        return

    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_daily_update()