import sys
import time
import shutil
import importlib
import duckdb
from datetime import datetime
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("DailyUpdate")

def backup_database():
    """
    INTEGRITY LAW: Creates a timestamped backup of the Vault before modification.
    """
    if not config.DB_FILE.exists():
        return

    backup_dir = config.DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d")
    backup_path = backup_dir / f"quant_strategy_{timestamp}.duckdb.bak"
    
    try:
        shutil.copy(config.DB_FILE, backup_path)
        log.info(f"🛡️  Vault Backup Secure: {backup_path.name}")
    except Exception as e:
        log.error(f"❌ Backup Failed: {e}")
        # We do not exit; we warn. Production must go on.

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

def check_todays_signals():
    """
    OBSERVABILITY LAW: Checks if today's run generated a new signal.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE))
        # Check for signals generated today
        today_str = datetime.now(config.TZ_UTC).strftime("%Y-%m-%d")
        
        # Query Manifest
        query = f"""
            SELECT count(*) 
            FROM {config.TBL_MANIFEST} 
            WHERE CAST(date AS DATE) = '{today_str}'
        """
        count = con.execute(query).fetchone()[0]
        con.close()

        if count > 0:
            log.info(f"🚨 ALERT: {count} NEW SIGNAL(S) DETECTED TODAY!")
        else:
            log.info("💤 No new signals detected today.")
            
    except Exception:
        pass # Silent fail on reporting is acceptable

def run_module(module_name, function_name):
    """
    Dynamically imports and executes pipeline stages.
    """
    try:
        log.info(f"\n>>> 🚀 Executing: {module_name}...")
        if module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            module = importlib.import_module(module_name)
        
        func = getattr(module, function_name)
        func()
        log.info(f"✅ {module_name} Success.")
        
    except Exception as e:
        log.error(f"❌ CRITICAL FAILURE in {module_name}: {e}")
        sys.exit(1)

def run_pipeline():
    start_time = time.time()
    log.info("="*60)
    log.info("🕹️  QUANT OS v2.0 - DAILY ORCHESTRATOR")
    log.info("="*60)

    # --- PHASE 0: SAFETY ---
    backup_database()

    # --- PHASE 1: INGESTION ---
    run_module("01_ingest_indices", "ingest_indices")

    # --- PHASE 2: PROCESSING ---
    run_module("02_scan_signals", "scan_signals")
    check_todays_signals() # <--- Immediate Feedback

    # --- PHASE 3: FETCHING ---
    run_module("03_fetch_options", "fetch_options")

    # --- PHASE 4: CALCULATIONS ---
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