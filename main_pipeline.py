import sys
import time
import importlib
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils.logger import get_logger
from src.utils import config

log = get_logger("DailyPipeline")

# --- CONFIGURATION (VACATION PROOFING) ---
# Always check last 30 days to auto-repair gaps from weekends/holidays/downtime
DEEP_LOOKBACK = 60

# ==============================================================================
# 2. DYNAMIC IMPORTER (The Adapter Layer)
# ==============================================================================
def safe_import(module_path, fallback_path=None):
    """Attempts to import a module, optionally falling back to an alternative."""
    try:
        return importlib.import_module(module_path)
    except ImportError:
        if fallback_path:
            try:
                log.warning(f"⚠️ Module '{module_path}' not found. Falling back to '{fallback_path}'...")
                return importlib.import_module(fallback_path)
            except ImportError as e:
                log.error(f"❌ Critical Import Error: Could not load '{module_path}' or '{fallback_path}'. {e}")
                return None
        log.error(f"❌ Critical Import Error: Could not load '{module_path}'")
        return None

def execute_step(step_name, module, potential_funcs, *args, **kwargs):
    """Executes a step by trying a list of potential function names."""
    if not module:
        log.error(f"❌ {step_name} Skipped (Module Missing)")
        return False

    for func_name in potential_funcs:
        if hasattr(module, func_name):
            try:
                log.info(f"▶️  {step_name} ({func_name})...")
                func = getattr(module, func_name)
                # CRITICAL: Pass arguments (like lookback_days) if the function accepts them
                try:
                    func(*args, **kwargs)
                except TypeError:
                    # Fallback for older functions that don't accept args yet
                    log.warning(f"⚠️ {func_name} does not accept args. Running without params.")
                    func()
                return True
            except Exception as e:
                log.error(f"❌ {step_name} Failed during execution: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    available = [x for x in dir(module) if not x.startswith("__")]
    log.error(f"❌ {step_name} Failed: No entry point found in {module.__name__}. Available: {available}")
    return False

# ==============================================================================
# 3. MAIN EXECUTION PROTOCOL
# ==============================================================================
def run_daily_update():
    start_time = time.time()
    log.info("🚀 QUANT-OS MAIN PIPELINE INITIATED (VACATION PROOF MODE)")

    # --- PRE-FLIGHT CHECKS ---
    if not config.DB_FILE.parent.exists():
        log.warning(f"📁 Creating Data Directory: {config.DB_FILE.parent}")
        config.DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # STEP 1: INDEX INGESTION (Hybrid 1m/5m)
    # ---------------------------------------------------------
    # Forces 30-day deep scan to ensure VIX/SPX history is contiguous
    mod_indices = safe_import("src.data.ingest_indices")
    execute_step(
        "Index Ingestion", 
        mod_indices, 
        ["run_ingest", "run_pipeline"], 
        lookback_days=DEEP_LOOKBACK 
    )

    # ---------------------------------------------------------
    # STEP 2: OPTION HARVEST (Surgical)
    # ---------------------------------------------------------
    # Forces 30-day scan to fill any gaps in the Option Chain
    mod_options = safe_import("src.data.ingest_options_daily", fallback_path="src.data.ingest_options")
    execute_step(
        "Option Harvest", 
        mod_options, 
        ["run_daily_harvest", "run_fetch_pipeline"], 
        lookback_days=DEEP_LOOKBACK
    )

    # ---------------------------------------------------------
    # STEP 3: FRACTAL SCANNER (Signal Generation)
    # ---------------------------------------------------------
    # Re-scans last 30 days to regenerate any missing signals in Manifest
    mod_scanner = safe_import("src.core.engine_scanner", fallback_path="src.core.engine_macro_scanner")
    execute_step(
        "Fractal Scanner", 
        mod_scanner, 
        ["run_scanner", "run_macro_scan"], 
        lookback_days=DEEP_LOOKBACK
    )

    # ---------------------------------------------------------
    # STEP 4: AI ORACLE RETRAINING (Precision Model)
    # ---------------------------------------------------------
    mod_ml = safe_import("src.core.engine_ml_precision", fallback_path="src.core.engine_ml")
    execute_step(
        "AI Retraining", 
        mod_ml, 
        ["train_precision_oracle", "train_oracle"]
    )

    # ---------------------------------------------------------
    # STEP 5: SIMULATION (Daily PnL Check)
    # ---------------------------------------------------------
    # Simulation only needs to run for "Yesterday" to update the ledger, 
    # as history is built by the previous steps.
    mod_backtest = safe_import("src.core.engine_backtest")
    if mod_backtest:
        try:
            log.info("▶️  Daily Simulation...")
            if hasattr(mod_backtest, 'run_backtest_session'):
                mod_backtest.run_backtest_session(days=1)
            elif hasattr(mod_backtest, 'run_simulation'):
                mod_backtest.run_simulation()
            else:
                log.warning("⚠️ No simulation entry point found in engine_backtest.")
        except Exception as e:
            log.error(f"❌ Simulation Failed: {e}")

    elapsed = time.time() - start_time
    log.info(f"✅ PIPELINE COMPLETE in {elapsed:.2f}s")

if __name__ == "__main__":
    run_daily_update()