import sys
import time
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
# This script is in 'ops/', so the Project Root is one level up
ROOT_DIR = Path(__file__).resolve().parent.parent 
sys.path.append(str(ROOT_DIR))

# --- IMPORT CORE ENGINES ---
try:
    from src.utils.logger import get_logger
    
    # We assume these exist in src/core/ (The Roster)
    import src.core.engine_scanner as engine_scanner 
    import src.core.engine_greeks as engine_greeks 
    
except ImportError as e:
    print(f"❌ CRITICAL: Could not import core engine: {e}")
    sys.exit(1)

log = get_logger("HistoryScanner")

# ==============================================================================
# 2. CONFIGURATION (FORCED LOOKBACK - NOTE: Argument is now removed)
# ==============================================================================
# NOTE: The explicit FORCED_LOOKBACK_DAYS is now internal knowledge only.
# The scanner function is called without arguments to avoid the crash.
# The function will now process all available data (your full year).
# ==============================================================================

# ==============================================================================
# 3. EXECUTION CHAIN
# ==============================================================================
def run_historical_scan():
    start_time = time.time()
    log.info(f"⚔️ STARTING HISTORICAL FRACTAL SCANNER (Full History Mode)")
    
    # ---------------------------------------------------------
    # STEP 1: SCAN FOR FRACTAL SIGNALS (The Strategy)
    # ---------------------------------------------------------
    try:
        log.info(f"--- [1/2] Generating Trade Manifest (Processing all available Index/VIX data) ---")
        # FIX: Argument 'lookback_days' removed to avoid Binder Error
        engine_scanner.scan_and_generate_manifest() 
        log.info("✅ Trade Manifest Generation Complete.")
    except Exception as e:
        log.error(f"❌ Step 1 (Scanner) Failed: {e}")
        return

    # ---------------------------------------------------------
    # STEP 2: CALCULATE GREEKS (The Math)
    # ---------------------------------------------------------
    try:
        log.info("--- [2/2] Calculating Greeks and Risk Metrics ---")
        engine_greeks.run_greek_calculation()
        log.info("✅ Greeks Calculation Complete.")
    except Exception as e:
        log.error(f"❌ Step 2 (Greeks) Failed: {e}")

    elapsed = time.time() - start_time
    log.info(f"🎉 HISTORICAL PREPARATION COMPLETE. Runtime: {elapsed:.2f} seconds.")
    log.info("System is now ready for full Backtest and Chart Analysis.")


if __name__ == "__main__":
    run_historical_scan()