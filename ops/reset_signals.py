import sys
from pathlib import Path
import duckdb

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1] # Adjust depending on where you save this
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SurgicalTeam")

def clear_manifest_only():
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. VERIFY OPTION DATA IS SAFE
    opt_count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_OPTIONS}").fetchone()[0]
    log.info(f"💰 VERIFIED: Vault contains {opt_count:,} Option contracts. THESE WILL BE SAVED.")
    
    if opt_count == 0:
        log.warning("⚠️ WARNING: Option table appears empty. Did you point to the right DB?")
        # proceed anyway to clear manifest
    
    # 2. SURGICAL STRIKE ON MANIFEST
    log.info(f"🧹 Clearing corrupted signals from {config.TBL_MANIFEST}...")
    con.execute(f"DELETE FROM {config.TBL_MANIFEST}")
    
    # 3. VERIFY
    rem_count = con.execute(f"SELECT COUNT(*) FROM {config.TBL_MANIFEST}").fetchone()[0]
    if rem_count == 0:
        log.info("✅ SUCCESS: Signal Manifest is clean.")
    else:
        log.error("❌ ERROR: Could not clear manifest.")
        
    con.close()
    log.info("🛡️ OPERATION COMPLETE. You may now run 'scan_full_history.py'.")

if __name__ == "__main__":
    clear_manifest_only()