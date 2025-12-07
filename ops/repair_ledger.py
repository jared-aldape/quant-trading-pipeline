import sys
import duckdb
from pathlib import Path
from datetime import datetime

# Path Constitution
# Assumes this script is in ops/ and project root is parents[1]
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

# Lazy import internal modules since the main script might fail before configuration loads
try:
    from src.utils import config
    from src.utils.logger import get_logger
    log = get_logger("LedgerRepair")
except ImportError:
    # Minimal logging fallback if internal structure is broken
    class MockLogger:
        def info(self, msg): print(f"{datetime.now().strftime('%H:%M:%S')} | INFO | [LedgerRepair] {msg}")
        def error(self, msg): print(f"{datetime.now().strftime('%H:%M:%S')} | ERROR | [LedgerRepair] {msg}")
    log = MockLogger()
    class MockConfig:
        DB_FILE = ROOT_DIR / "data" / "quant_strategy.duckdb"
        TBL_LIVE_LOG = "live_trade_ledger"
    config = MockConfig()


def force_repair():
    log.info(f"🔧 Starting Ledger Repair on: {config.DB_FILE}")
    
    try:
        # Check if DB file exists before connecting
        if not config.DB_FILE.exists():
             log.info("Database file not found. Creating new file structure.")
             config.DB_FILE.parent.mkdir(parents=True, exist_ok=True)

        con = duckdb.connect(str(config.DB_FILE))
        
        # 1. DROP EXISTING TABLE (Force Clean Slate)
        log.info(f"💥 Dropping old {config.TBL_LIVE_LOG}...")
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_LIVE_LOG}")
        
        # 2. CREATE NEW TRANSACTIONAL SCHEMA (11 Columns)
        # Matches engine_simulator.py insertion order and view_ledger.py selection exactly.
        log.info("🔨 Creating Transactional Schema (11 Columns)...")
        con.execute(f"""
        CREATE TABLE {config.TBL_LIVE_LOG} (
            trans_id VARCHAR PRIMARY KEY,   -- 1. UUID
            timestamp TIMESTAMP,            -- 2. Time
            ticker VARCHAR,                 -- 3. Ticker
            action VARCHAR,                 -- 4. Action (BUY/SELL)
            qty DOUBLE,                     -- 5. Qty
            price DOUBLE,                   -- 6. Price (Fill Price)
            fees DOUBLE,                    -- 7. Fees
            amount DOUBLE,                  -- 8. Amount (+/- cash flow)
            balance_snapshot DOUBLE,        -- 9. Account Balance After Transaction
            strategy_tag VARCHAR,           -- 10. Tag (e.g., MANUAL)
            notes VARCHAR                   -- 11. Notes
        )""")
        
        # 3. VERIFICATION
        cols = con.execute(f"DESCRIBE {config.TBL_LIVE_LOG}").fetchall()
        col_names = [c[0] for c in cols]
        
        if len(col_names) == 11 and 'amount' in col_names:
            log.info(f"✅ SUCCESS: Table rebuilt with {len(col_names)} columns.")
            log.info("   Columns: " + ", ".join(col_names))
        else:
            log.error("❌ FAILURE: Schema mismatch detected. Expected 11 columns.")
            
        con.close()
        
    except Exception as e:
        log.error(f"❌ REPAIR FAILED: {e}")
        log.error("HINT: Ensure 'python app.py' is NOT running and the DuckDB file is not locked.")

if __name__ == "__main__":
    force_repair()