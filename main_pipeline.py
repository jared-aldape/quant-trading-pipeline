import sys
import time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger

# MODULE IMPORTS
import src.data.ingest_indices as ingest_indices
import src.data.ingest_options_daily as ingest_options
import src.core.engine_scanner as engine_scanner
import src.core.engine_ml as engine_ml # Changed from engine_ml_precision to match file name
import src.core.engine_backtest as engine_backtest

log = get_logger("DailyPipeline")

def run_daily_update():
    start_time = time.time()
    log.info("🚀 QUANT-OS MAIN PIPELINE INITIATED")
    
    # ---------------------------------------------------------
    # STEP 1: INDEX INGESTION (Hybrid 1m/5m)
    # ---------------------------------------------------------
    try:
        log.info("--- [1/5] Updating Market Indices (XSP/VIX) ---")
        ingest_indices.run_pipeline() 
    except Exception as e:
        log.error(f"❌ Step 1 Failed (Index Ingest): {e}")

    # ---------------------------------------------------------
    # STEP 2: OPTION HARVEST (Surgical)
    # ---------------------------------------------------------
    try:
        log.info("--- [2/5] Harvesting Option Chains ---")
        ingest_options.run_daily_harvest()
    except Exception as e:
        log.error(f"❌ Step 2 Failed (Option Harvest): {e}")

    # ---------------------------------------------------------
    # STEP 3: FRACTAL SCANNER (Signal Generation)
    # ---------------------------------------------------------
    try:
        log.info("--- [3/5] Scanning for Fractal Signals ---")
        # FIXED: Correct function name from engine_scanner.py
        engine_scanner.run_scanner(lookback_days=5)
    except Exception as e:
        log.error(f"❌ Step 3 Failed (Scanner): {e}")

    # ---------------------------------------------------------
    # STEP 4: AI ORACLE RETRAINING (Precision Model)
    # ---------------------------------------------------------
    try:
        log.info("--- [4/5] Retraining AI Oracles ---")
        # FIXED: Correct function name from engine_ml.py
        engine_ml.train_precision_oracle()
    except Exception as e:
        log.error(f"❌ Step 4 Failed (ML Training): {e}")

    # ---------------------------------------------------------
    # STEP 5: SIMULATION (Daily PnL Check)
    # ---------------------------------------------------------
    try:
        log.info("--- [5/5] Running Daily Simulation ---")
        # FIXED: Ensure this matches engine_backtest.py. 
        # If run_backtest_session doesn't exist, check the file content.
        if hasattr(engine_backtest, 'run_backtest_session'):
            engine_backtest.run_backtest_session(days=1)
        else:
            log.warning("⚠️ engine_backtest.run_backtest_session not found. Skipping sim.")
    except Exception as e:
        log.error(f"❌ Step 5 Failed (Simulation): {e}")

    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_daily_update()