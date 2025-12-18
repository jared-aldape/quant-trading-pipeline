import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("LedgerExport")

def export_robinhood_ledger():
    """
    Retrieves the full Robinhood transaction history from the Vault.
    Exports to CSV for forensic strategy review.
    """
    # Define paths based on config
    db_path = config.DB_FILE
    output_path = config.REPORTS_DIR / "robinhood_export_for_review.csv"

    if not db_path.exists():
        log.error(f"❌ VAULT NOT FOUND: {db_path}")
        return

    try:
        log.info(f"🚀 CONNECTING TO VAULT: {db_path.name}")
        con = duckdb.connect(str(db_path), read_only=True)
        
        # Querying the active Robinhood log
        query = "SELECT * FROM active_rh_log ORDER BY entry_time_utc ASC"
        df = con.execute(query).df()
        
        if df.empty:
            log.warning("⚠️ THE LEDGER IS EMPTY. NO TRADES TO EXPORT.")
            return

        # Export to CSV
        df.to_csv(output_path, index=False)
        log.info(f"✅ EXPORT COMPLETE: {output_path}")
        print(f"\n[SYSTEM]: File generated at {output_path.absolute()}")
        print("[SYSTEM]: Please upload this file or paste the content to initiate the review.")

    except Exception as e:
        log.error(f"❌ EXPORT FAILED: {e}")
    finally:
        con.close()

if __name__ == "__main__":
    export_robinhood_ledger()