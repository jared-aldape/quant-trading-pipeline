import sys
import duckdb
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def repair():
    print(f"🔧 REPAIRING: {config.TBL_SIM_LOG}")
    
    if not config.DB_FILE.exists():
        print("❌ DB File not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Drop the mismatched table
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_SIM_LOG}")
    print("🗑️  Old table dropped.")
    
    # 2. Recreate with EXACTLY 7 columns (Matches view_backtest.py)
    con.execute(f"""
        CREATE TABLE {config.TBL_SIM_LOG} (
            entry_time TIMESTAMP, 
            ticker VARCHAR, 
            net_pnl DOUBLE, 
            return_pct DOUBLE, 
            reason VARCHAR, 
            entry_price DOUBLE, 
            exit_price DOUBLE
        )
    """)
    print("✅ New table created (7 Columns).")
    con.close()

if __name__ == "__main__":
    repair()