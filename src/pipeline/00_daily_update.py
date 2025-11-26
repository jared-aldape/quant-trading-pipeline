import sys
import os
import time
import shutil
import duckdb
import importlib.util
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE V2.1: PATH CONSTITUTION
# ==============================================================================
# We are in: quant-trading-pipeline/src/pipeline/
# We need to reach: quant-trading-pipeline/ (Root)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Add Root to System Path to allow imports from 'src.utils'
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("DailyUpdate")

# ==============================================================================
# 2. OPS & MAINTENANCE FUNCTIONS
# ==============================================================================
def backup_database():
    """
    INTEGRITY LAW: Creates a timestamped backup of the Vault before modification.
    Uses Local Time for the filename (User convenience), but file content is UTC.
    """
    if not config.DB_FILE.exists():
        return

    backup_dir = config.DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    
    # Filename uses Local Time (PST) for easy sorting by the user
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup_path = backup_dir / f"quant_strategy_{timestamp}.duckdb.bak"
    
    try:
        shutil.copy(config.DB_FILE, backup_path)
        log.info(f"🛡️  Vault Backup Secure: {backup_path.name}")
    except Exception as e:
        log.error(f"❌ Backup Failed: {e}")

def optimize_database():
    """
    MAINTENANCE: Compresses and cleans the DuckDB file.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE))
        con.execute("VACUUM;")
        con.execute("CHECKPOINT;")
        con.close()
        log.info("🧹 Vault Optimized (VACUUM/CHECKPOINT complete).")
    except Exception as e:
        log.error(f"⚠️ DB Maintenance Error: {e}")

def check_recent_signals():
    """
    OBSERVABILITY LAW: Checks for signals generated in the last 24 hours.
    Updated to solve the 'UTC Rollover' issue (The Midnight Bug).
    """
    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # Calculate cutoff: 24 hours ago in Milliseconds (UTC)
        # We use .timestamp() which gives seconds, * 1000 for ms
        cutoff_ms = int((datetime.now(config.TZ_UTC).timestamp() - 86400) * 1000)
        
        # Query Manifest for RECENT signals
        query = f"""
            SELECT count(*), string_agg(signal_type, ', ')
            FROM {config.TBL_MANIFEST} 
            WHERE entry_timestamp_utc > {cutoff_ms}
        """
        result = con.execute(query).fetchone()
        count = result[0]
        types = result[1] if result[1] else "None"
        
        con.close()

        if count > 0:
            log.info(f"🚨 ALERT: {count} NEW SIGNAL(S) IN LAST 24H: {types}")
        else:
            log.info("💤 No new signals detected in the last 24h.")
            
    except Exception as e:
        log.warning(f"⚠️ Signal Check Warning: {e}")

# ==============================================================================
# 3. DYNAMIC PIPELINE ORCHESTRATOR
# ==============================================================================
def run_module(module_name, function_name):
    """
    Dynamically executes pipeline stages located in the SAME folder (src/pipeline).
    """
    try:
        log.info(f"\n>>> 🚀 Executing: {module_name}...")
        
        # Look for the file in the current directory (src/pipeline)
        file_path = Path(__file__).parent / f"{module_name}.py"
        
        if not file_path.exists():
            log.error(f"❌ File not found: {file_path}")
            sys.exit(1)

        # Import module from file path
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        func = getattr(module, function_name)
        func()
        log.info(f"✅ {module_name} Success.")
        
    except Exception as e:
        log.error(f"❌ CRITICAL FAILURE in {module_name}: {e}")
        sys.exit(1)

def run_pipeline():
    start_time = time.time()
    log.info("="*60)
    log.info("🕹️  QUANT OS v2.1 - PIPELINE ORCHESTRATOR")
    log.info("="*60)

    # --- PHASE 0: SAFETY ---
    backup_database()

    # --- PHASE 1: INGESTION (UTC Enforcement) ---
    # Now looks for 01_ingest_indices.py in src/pipeline/
    run_module("01_ingest_indices", "ingest_indices")

    # --- PHASE 2: PROCESSING (Signal Scan) ---
    run_module("02_scan_signals", "scan_signals")
    check_recent_signals() 

    # --- PHASE 3: FETCHING (Options) ---
    run_module("03_fetch_options", "fetch_options")

    # --- PHASE 4: CALCULATIONS (Greeks) ---
    run_module("04_calc_greeks", "run_greek_calculation")

    # --- PHASE 5: MAINTENANCE ---
    optimize_database()

    # --- SUMMARY ---
    elapsed = time.time() - start_time
    log.info("="*60)
    log.info(f"🏁 UPDATE COMPLETE. Time: {elapsed:.2f}s")
    log.info("   Dashboard Ready: python app.py")
    log.info("="*60)

if __name__ == "__main__":
    run_pipeline()