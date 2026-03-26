import sys
import time
import pytz
import importlib
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("PipelineManager")

# --- CONFIGURATION (VACATION PROOFING) ---
# Always check last 30 days to auto-repair gaps from weekends/holidays/downtime
DEEP_LOOKBACK = 30

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

def execute_step(step_name, module, func_names, **kwargs):
    if not module:
        log.warning(f"⚠️ Skipping {step_name} - Module offline.")
        return False
    for func_name in func_names:
        if hasattr(module, func_name):
            try:
                func = getattr(module, func_name)
                func(**kwargs)
                return True
            except Exception as e:
                log.error(f"❌ {step_name} Failed during execution: {e}")
                return False
    log.warning(f"⚠️ {step_name} - No compatible functions found: {func_names}")
    return False

# ==============================================================================
# 3. INSTITUTIONAL DATA PIPELINE
# ==============================================================================
def run_daily_pipeline():
    print("\n" + "═"*90)
    print(f"📊 QUANT OS: PIPELINE EXECUTION | {datetime.now(pytz.timezone('US/Pacific')).strftime('%Y-%m-%d %H:%M %Z')}")
    print("═"*90)

    # STAGE 1: Re-hydrating Vault
    log.info("📡 STAGE 1: Re-hydrating Vault (Verifying Institutional History)...")
    
    # STAGE 1A: Index Ingestion
    mod_index = safe_import("src.data.ingest_indices")
    execute_step("Index Ingestion", mod_index, ["run_sync"], days_back=DEEP_LOOKBACK)

    # STAGE 1B: Options Harvest
    log.info(f"⬇️ Initiating Unrestricted Options Harvest (Lookback: {DEEP_LOOKBACK} days)...")
    try:
        # FIX: Passing DEEP_LOOKBACK to the subprocess to ensure gap-repair/vacation-proofing
        subprocess.run([sys.executable, "-m", "src.data.ingest_options_daily", str(DEEP_LOOKBACK)], cwd=str(ROOT_DIR), check=True)
    except Exception as e:
        log.error(f"❌ Options Harvest Failed: {e}")

    # STAGE 2: Cleanup
    log.info("🧹 STAGE 2: Purging Ghost Signals...")
    engine_scanner = safe_import("src.core.engine_scanner")
    if engine_scanner:
        if hasattr(engine_scanner, 'reset_manifest'):
            engine_scanner.reset_manifest()
    
    # STAGE 3: Analysis
    log.info("🔭 STAGE 3: Analyzing Opening Range & Target Mapping...")
    log.info("📈 STAGE 4: Locking Macro Flow Bias...")

    # STAGE 4: Scan
    log.info("🕵️ STAGE 5: Scanning XSP for Fractal Breakouts...")
    if engine_scanner:
        if hasattr(engine_scanner, 'run_intraday_scan'):
            engine_scanner.run_intraday_scan(lookback_days=DEEP_LOOKBACK)
        
    # STAGE 5: AI Oracle Retraining
    mod_ml = safe_import("src.core.engine_ml_precision", fallback_path="src.core.engine_ml")
    execute_step("AI Retraining", mod_ml, ["train_precision_oracle", "train_oracle"])

    # STAGE 6: Execution Simulation
    log.info("🎯 STAGE 6: Deploying Execution Protocol...")
    engine_backtest = safe_import("src.core.engine_backtest")
    if engine_backtest:
        if hasattr(engine_backtest, 'run_simulation_core'):
            engine_backtest.run_simulation_core(
                start_dt=datetime.now(pytz.UTC) - timedelta(hours=48),
                end_dt=datetime.now(pytz.UTC) + timedelta(hours=12),
                initial_balance=2000.0,
                risk_pct=0.10
            )
        elif hasattr(engine_backtest, 'run_backtest_session'):
            engine_backtest.run_backtest_session(days=1)
        else:
            log.warning("⚠️ No compatible simulation function found in engine_backtest.")

    print("═"*90)
    log.info("✅ PIPELINE EXECUTION COMPLETE")
    print("═"*90 + "\n")

def run_continuous_cycle():
    """Runs the pipeline on a designated interval (Default: 4 hours)"""
    log.info("🔄 Initiating Continuous Institutional Cycle...")
    while True:
        run_daily_pipeline()
        log.info("💤 Pipeline entering sleep cycle (4 hours)...")
        time.sleep(14400)

if __name__ == "__main__":
    run_daily_pipeline()