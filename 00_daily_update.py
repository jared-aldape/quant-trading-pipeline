import sys
import time
import importlib
from src.utils.logger import get_logger

log = get_logger("DailyUpdate")

def run_module(module_name, function_name):
    """
    Dynamically imports and runs a specific function from a module.
    Needed because Python files starting with numbers (01_...) cannot be imported normally.
    """
    try:
        log.info(f"\n>>> 🚀 Executing: {module_name}...")
        
        # Force reload in case of cached imports during dev
        if module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            module = importlib.import_module(module_name)
            
        # Get the specific function
        func = getattr(module, function_name)
        
        # Execute
        func()
        log.info(f"✅ {module_name} Success.")
        
    except ImportError as e:
        log.error(f"❌ Could not find script '{module_name}.py'. Is it in the root folder?")
        log.error(e)
        sys.exit(1)
    except AttributeError as e:
        log.error(f"❌ Script '{module_name}.py' exists but is missing function '{function_name}()'.")
        log.error(e)
        sys.exit(1)
    except Exception as e:
        log.error(f"❌ CRITICAL FAILURE in {module_name}: {e}")
        sys.exit(1)

def run_pipeline():
    start_time = time.time()
    log.info("="*60)
    log.info("🕹️  QUANT PIPELINE V2.0 - DAILY UPDATE")
    log.info("="*60)

    # --- STEP 1: INGESTION ---
    # File: 01_ingest_indices.py | Function: ingest_indices()
    # Fetches SPX, VIX, Futures, and Interest Rates
    run_module("01_ingest_indices", "ingest_indices")

    # --- STEP 2: PROCESSING ---
    # File: 02_scan_signals.py | Function: scan_signals()
    # Detects VIX crossovers and creates the Trade Manifest
    run_module("02_scan_signals", "scan_signals")

    # --- STEP 3: FETCHING ---
    # File: 03_fetch_options.py | Function: fetch_options()
    # Downloads Option Chains for every signal in the Manifest
    run_module("03_fetch_options", "fetch_options")

    # --- STEP 4: CALCULATIONS ---
    # File: 04_calc_greeks.py | Function: run_greek_calculation()
    # Calculates IV, Delta, Gamma using dynamic interest rates
    run_module("04_calc_greeks", "run_greek_calculation")

    # --- SUMMARY ---
    elapsed = time.time() - start_time
    log.info("="*60)
    log.info(f"🏁 PIPELINE COMPLETE. Total Time: {elapsed:.2f} seconds")
    log.info("   Ready to launch: python 09_simulator.py")
    log.info("="*60)

if __name__ == "__main__":
    run_pipeline()