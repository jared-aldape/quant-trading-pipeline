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

# v3.2 MODULE IMPORTS
# Since we are at root, we import directly from 'src'
import src.data.ingest_indices as ingest_indices
import src.core.engine_macro_flow as engine_macro_flow 
import src.core.engine_scanner as engine_scanner
import src.data.ingest_options as ingest_options
import src.core.engine_greeks as engine_greeks
import src.core.engine_optimizer as engine_optimizer # <--- NEW MODULE: ADAPTIVE WARFARE

log = get_logger("DailyPipeline")

def run_daily_update():
    start_time = time.time()
    log.info("🌅 STARTING QUANT OS v3.2 PIPELINE")
    
    # ---------------------------------------------------------
    # STEP 1: INGEST MARKET INDICES (The Truth)
    # ---------------------------------------------------------
    # Fetches SPX, VIX, IRX from Polygon (or Yahoo Fallback)
    try:
        log.info("--- [1/6] Ingesting Indices (Hybrid) ---")
        ingest_indices.run_pipeline()
    except Exception as e:
        log.error(f"❌ Step 1 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 2: CALCULATE MACRO FLOW BIAS (The Bias Filter)
    # ---------------------------------------------------------
    # Calculates the 20-day rolling Bull/Bear bias to dynamically set allocation
    try:
        log.info("--- [2/6] Calculating Macro Flow Bias ---") 
        engine_macro_flow.run_pipeline()
    except Exception as e:
        log.error(f"❌ Step 2 Failed: {e}")
        
    # ---------------------------------------------------------
    # STEP 3: SCAN FOR FRACTAL SIGNALS (The Strategy)
    # ---------------------------------------------------------
    # Rebuilds trade_manifest based on strat_fractal.py logic
    try:
        log.info("--- [3/6] Scanning Signals (Fractal Flow) ---")
        engine_scanner.scan_and_generate_manifest()
    except Exception as e:
        log.error(f"❌ Step 3 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 4: FETCH OPTION DATA (The Vehicle)
    # ---------------------------------------------------------
    # Downloads 1-minute aggregates for identified signal dates
    try:
        log.info("--- [4/6] Fetching Option Contracts ---")
        ingest_options.run_fetch_pipeline()
    except Exception as e:
        log.error(f"❌ Step 4 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 5: CALCULATE GREEKS (The Math)
    # ---------------------------------------------------------
    # Calculates IV, Delta, Gamma for the Analysis Dashboard
    try:
        log.info("--- [5/6] Calculating Greeks ---")
        engine_greeks.run_greek_calculation()
    except Exception as e:
        log.error(f"❌ Step 5 Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 6: RUN EVOLUTIONARY OPTIMIZER (Adaptive Warfare)
    # ---------------------------------------------------------
    # Checks VIX Regime -> Updates strat_params.json
    try:
        log.info("--- [6/6] Running Strategy Evolution ---")
        engine_optimizer.run_optimization_cycle()
    except Exception as e:
        log.error(f"❌ Step 6 Failed: {e}")

    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE. Runtime: {elapsed:.2f} seconds.")

if __name__ == "__main__":
    run_daily_update()
    # ... inside run_daily_update() ...

    # ---------------------------------------------------------
    # STEP 7: BLACK BOX RECORDING (The Safety Net)
    # ---------------------------------------------------------
    try:
        log.info("--- [7/7] Running Black Box Recorder ---")
        # Dynamic import to handle the ops folder being a sibling
        import ops.backup_vault as backup_vault
        backup_vault.run_backup_procedure()
    except Exception as e:
        log.error(f"❌ Step 7 Failed: {e}")