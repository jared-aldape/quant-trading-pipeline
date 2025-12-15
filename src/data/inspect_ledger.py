import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# PATH & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("LedgerInspector")
TBL_RH_LEDGER = "active_rh_log"

def inspect_ledger():
    if not config.DB_FILE.exists():
        log.error("❌ No database found.")
        return

    try:
        log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Check Table Existence
        tables = con.execute("SHOW TABLES").fetchall()
        table_list = [t[0] for t in tables]
        
        if TBL_RH_LEDGER not in table_list:
            log.error(f"❌ Table '{TBL_RH_LEDGER}' does not exist!")
            con.close()
            return

        # 2. Fetch Data
        log.info(f"🔍 Querying {TBL_RH_LEDGER}...")
        df = con.execute(f"SELECT * FROM {TBL_RH_LEDGER} ORDER BY entry_time_utc DESC").df()
        con.close()

        if df.empty:
            log.warning("⚠️ Table is empty.")
            return

        # 3. FORENSIC REPORT
        print("\n" + "="*60)
        print(f"📊 LEDGER DIAGNOSTICS ({len(df)} Records)")
        print("="*60)
        
        # Check Column Types
        print("\n[COLUMN TYPES]")
        print(df.dtypes)

        # Check Fee Totals
        total_fees = df['fees'].sum()
        total_pnl = df['net_pnl'].sum()
        print(f"\n[TOTALS] Fees: ${total_fees:.2f} | Net PnL: ${total_pnl:.2f}")

        # Check for Non-Zero Fees
        non_zero_fees = df[df['fees'] > 0]
        print(f"[RECORDS WITH FEES] Count: {len(non_zero_fees)}")

        # Print Head
        print("\n[RECENT TRANSACTIONS (First 10)]")
        # Select specific columns for readability
        view_cols = ['entry_time_utc', 'action', 'root', 'strike', 'option_right', 'fill_price', 'net_pnl', 'fees', 'status']
        # Handle case where column might be missing if schema is old
        available_cols = [c for c in view_cols if c in df.columns]
        
        print(df[available_cols].head(10).to_string(index=False))

    except Exception as e:
        log.error(f"❌ Inspection Failed: {e}")

if __name__ == "__main__":
    inspect_ledger()