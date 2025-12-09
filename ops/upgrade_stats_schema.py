import sys
import duckdb
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config

def upgrade():
    print(f"🔧 UPGRADING SCHEMA: {config.TBL_SIM_LOG}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # Drop old table
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_SIM_LOG}")
    
    # Create Expanded Table (Added exit_time and duration)
    con.execute(f"""
        CREATE TABLE {config.TBL_SIM_LOG} (
            entry_time TIMESTAMP, 
            exit_time TIMESTAMP,
            ticker VARCHAR, 
            net_pnl DOUBLE, 
            return_pct DOUBLE, 
            reason VARCHAR, 
            entry_price DOUBLE, 
            exit_price DOUBLE,
            duration_mins DOUBLE
        )
    """)
    print("✅ Schema Upgraded: Added 'exit_time' and 'duration_mins'.")
    con.close()

if __name__ == "__main__":
    upgrade()