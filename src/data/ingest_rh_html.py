import sys
import duckdb
from pathlib import Path

# ==============================================================================
# PATH & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("LedgerReset")
TBL_RH_LEDGER = "active_rh_log"

def reset_ledger():
    if not config.DB_FILE.exists():
        log.warning("⚠️ No database found to reset.")
        return

    try:
        log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
        con = duckdb.connect(str(config.DB_FILE))
        
        # CHECK IF EXISTS
        tables = con.execute("SHOW TABLES").fetchall()
        table_list = [t[0] for t in tables]
        
        if TBL_RH_LEDGER in table_list:
            log.info(f"💣 DROPPING TABLE: {TBL_RH_LEDGER}")
            con.execute(f"DROP TABLE {TBL_RH_LEDGER}")
            log.info("✅ Table eradicated. The slate is clean.")
        else:
            log.info(f"ℹ️ Table {TBL_RH_LEDGER} not found. Nothing to delete.")
            
        con.close()

    except Exception as e:
        log.error(f"❌ Reset Failed: {e}")

if __name__ == "__main__":
    print("\n⚠️  DANGER: LEDGER WIPE ⚠️")
    print(f"This will permanently delete '{TBL_RH_LEDGER}'.")
    confirm = input("Type 'DELETE' to execute: ")
    
    if confirm == "DELETE":
        reset_ledger()
    else:
        print("🚫 Operation Aborted.")