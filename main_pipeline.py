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
import src.core.engine_scanner as engine_scanner
import src.core.engine_backtest as engine_backtest 
import src.data.ingest_indices as ingest_indices      
import src.data.ingest_options_daily as ingest_options 
# NEW: Import ML Brains
import src.core.engine_ml_precision as engine_ml_precision
import src.core.engine_ml as engine_ml

log = get_logger("DailyPipeline")

def run_pipeline():
    start_time = time.time()
    log.info("🚀 QUANT-OS PIPELINE INITIATED")
    
    # ---------------------------------------------------------
    # STEP 1: INGESTION (The Feed)
    # ---------------------------------------------------------
    try:
        log.info("--- [1/6] Checking Market Data Freshness ---")
        if hasattr(ingest_indices, 'run_ingest'):
            ingest_indices.run_ingest()
        ingest_options.run_daily_harvest()
    except Exception as e:
        log.error(f"❌ Step 1 Failed (Ingestion): {e}")

    # ---------------------------------------------------------
    # STEP 2: SCANNER (The Eyes)
    # ---------------------------------------------------------
    try:
        log.info("--- [2/6] Scanning for Fractal Signals ---")
        engine_scanner.scan_and_generate_manifest()
    except Exception as e:
        log.error(f"❌ Step 2 Failed (Scanner): {e}")
        return

    # ---------------------------------------------------------
    # STEP 3: NEURAL TRAINING (The Brain) -- NEW
    # ---------------------------------------------------------
    try:
        log.info("--- [3/6] Retraining Precision Oracle (v3) ---")
        engine_ml_precision.train_precision_oracle()
        
        log.info("--- [4/6] Retraining Directional Oracle (v2) ---")
        engine_ml.train_oracle()
    except Exception as e:
        log.error(f"❌ Step 3/4 Failed (ML Training): {e}")

    # ---------------------------------------------------------
    # STEP 5: SIMULATION (The Test)
    # ---------------------------------------------------------
    try:
        log.info("--- [5/6] Running Historical Backtest ---")
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        if hasattr(engine_backtest, 'run_simulation'):
            engine_backtest.run_simulation(
                start_date=start_date,
                end_date=end_date,
                initial_balance=10000,
                profile='Standard'
            )
        elif hasattr(engine_backtest, 'run_backtest'):
            engine_backtest.run_backtest(
                start_date=start_date,
                end_date=end_date,
                initial_balance=10000,
                profile='Standard'
            )
    except Exception as e:
        log.error(f"❌ Step 5 Failed (Backtest): {e}")

    # ---------------------------------------------------------
    # STEP 6: REPORTING
    # ---------------------------------------------------------
    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE. Duration: {elapsed/60:.1f} min")

if __name__ == "__main__":
    run_pipeline()