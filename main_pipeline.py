import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# IMPORT ENGINES
import src.data.ingest_indices as ingest_indices      
import src.data.ingest_options_daily as ingest_options 
import src.core.engine_scanner as engine_scanner
import src.core.engine_backtest as engine_backtest 
import src.core.engine_ml_precision as engine_ml_precision

log = get_logger("DailyPipeline")

def run_pipeline():
    start_time = time.time()
    log.info("🚀 QUANT-OS MAIN PIPELINE INITIATED")
    
    # ---------------------------------------------------------
    # STEP 1: INDEX DATA (The Map)
    # ---------------------------------------------------------
    try:
        log.info("--- [1/5] Updating Market Indices (XSP/VIX) ---")
        ingest_indices.run_ingest()
    except Exception as e:
        log.error(f"❌ Step 1 Failed (Index Ingest): {e}")

    # ---------------------------------------------------------
    # STEP 2: OPTION DATA (The Terrain)
    # ---------------------------------------------------------
    try:
        log.info("--- [2/5] Harvesting Option Chains ---")
        # Ingests T-1 data for Oracle validation
        ingest_options.run_daily_harvest()
    except Exception as e:
        log.error(f"❌ Step 2 Failed (Option Harvest): {e}")

    # ---------------------------------------------------------
    # STEP 3: SCANNING (The Signals)
    # ---------------------------------------------------------
    try:
        log.info("--- [3/5] Scanning for Fractal Signals ---")
        
        # [FIXED] Aligned with Magitek v3.4 Unified Standard
        # Consolidates legacy 'scan_and_generate_manifest' into unified run loop
        engine_scanner.run_scanner()
        
    except Exception as e:
        log.error(f"❌ Step 3 Failed (Scanner): {e}")

    # ---------------------------------------------------------
    # STEP 4: ORACLE TRAINING (The Brain)
    # ---------------------------------------------------------
    try:
        log.info("--- [4/5] Retraining AI Oracles ---")
        engine_ml_precision.train_precision_oracle()
    except Exception as e:
        log.error(f"❌ Step 4 Failed (ML Training): {e}")

    # ---------------------------------------------------------
    # STEP 5: SIMULATION (The Test)
    # ---------------------------------------------------------
    try:
        log.info("--- [5/5] Running Daily Simulation ---")
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        # ADAPTIVE LOGIC: Handles version shifts in backtest engine
        if hasattr(engine_backtest, 'run_simulation'):
            engine_backtest.run_simulation(
                start_date=start_date, end_date=end_date,
                initial_balance=10000, profile='Standard'
            )
        elif hasattr(engine_backtest, 'run_backtest'):
            engine_backtest.run_backtest(
                start_date=start_date, end_date=end_date,
                initial_balance=10000, profile='Standard'
            )
        else:
            log.error("❌ Could not find execution attribute in engine_backtest.")
            
    except Exception as e:
        log.error(f"❌ Step 5 Failed (Backtest): {e}")

    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_pipeline()