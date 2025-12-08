import sys
import duckdb
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("OptionsRepair")

def repair_options_table():
    log.info(f"🔧 Repairing Options Schema in: {config.DB_FILE}")
    
    try:
        con = duckdb.connect(str(config.DB_FILE))
        
        # 1. DROP OLD TABLE
        log.info(f"💥 Dropping old {config.TBL_OPTIONS}...")
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_OPTIONS}")
        
        # 2. CREATE NEW SCHEMA (Matching ingest_options.py)
        # 17 Columns Expected by Ingest Script
        log.info("🔨 Creating New Options Schema (17 Columns)...")
        con.execute(f"""
        CREATE TABLE {config.TBL_OPTIONS} (
            datetime_utc TIMESTAMP,
            ticker VARCHAR,
            expiration DATE,
            strike DOUBLE,
            type VARCHAR,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            iv DOUBLE,         -- 11
            delta DOUBLE,      -- 12
            gamma DOUBLE,      -- 13
            vega DOUBLE,       -- 14
            theta DOUBLE,      -- 15
            underlying_price DOUBLE, -- 16 (Calculated Later)
            risk_free_rate DOUBLE,   -- 17 (Calculated Later)
            PRIMARY KEY (datetime_utc, ticker)
        )""")
        
        # 3. VERIFICATION
        cols = con.execute(f"DESCRIBE {config.TBL_OPTIONS}").fetchall()
        col_count = len(cols)
        
        if col_count == 17:
            log.info(f"✅ SUCCESS: Table rebuilt with {col_count} columns.")
        else:
            log.error(f"❌ FAILURE: Created {col_count} columns, expected 17.")
            
        con.close()
        
    except Exception as e:
        log.error(f"❌ REPAIR FAILED: {e}")

if __name__ == "__main__":
    repair_options_table()