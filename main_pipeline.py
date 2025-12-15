import sys
import time
from pathlib import Path
from datetime import datetime, timedelta # Added timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# IMPORT ENGINES
import src.core.engine_scanner as engine_scanner
import src.core.engine_backtest as engine_backtest 
import src.data.ingest_indices as ingest_indices      
import src.data.ingest_options_daily as ingest_options 

log = get_logger("DailyPipeline")

def run_pipeline():
    start_time = time.time()
    log.info("🚀 QUANT-OS PIPELINE INITIATED")
    
    # ---------------------------------------------------------
    # STEP 1: INGESTION
    # ---------------------------------------------------------
    try:
        log.info("--- [1/5] Checking Market Data Freshness ---")
        if hasattr(ingest_indices, 'run_ingest'):
            ingest_indices.run_ingest()
        ingest_options.run_daily_harvest()
    except Exception as e:
        log.error(f"❌ Step 1 Failed (Ingestion): {e}")
        # Continue to allow scanner to run on existing data

    # ---------------------------------------------------------
    # STEP 2: MACRO FLOW
    # ---------------------------------------------------------
    # engine_macro.update_context()

    # ---------------------------------------------------------
    # STEP 3: SCANNER
    # ---------------------------------------------------------
    try:
        log.info("--- [3/5] Scanning for Fractal Signals ---")
        engine_scanner.scan_and_generate_manifest()
    except Exception as e:
        log.error(f"❌ Step 3 Failed (Scanner): {e}")
        return

    # ---------------------------------------------------------
    # STEP 4: SIMULATION (FIXED ARGUMENTS)
    # ---------------------------------------------------------
    try:
        log.info("--- [4/5] Running Historical Backtest ---")
        
        # Calculate Defaults
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        if hasattr(engine_backtest, 'run_simulation'):
            # Pass required arguments
            engine_backtest.run_simulation(
                start_date=start_date,
                end_date=end_date,
                initial_balance=10000,
                profile='Standard'
            )
        elif hasattr(engine_backtest, 'run_backtest'):
            # Pass required arguments
            engine_backtest.run_backtest(
                start_date=start_date,
                end_date=end_date,
                initial_balance=10000,
                profile='Standard'
            )
        else:
            log.warning("⚠️ engine_backtest.py found, but no entry point detected.")
            
    except Exception as e:
        log.error(f"❌ Step 4 Failed (Backtest): {e}")

    # ---------------------------------------------------------
    # STEP 5: REPORTING
    # ---------------------------------------------------------
    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE. Duration: {elapsed/60:.1f} min")

if __name__ == "__main__":
    run_pipeline()